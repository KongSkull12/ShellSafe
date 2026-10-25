"""
Train and compare Decision Tree, SVM and Random Forest for algal bloom
prediction from ShellSafe probe readings, then export the best one for the
web app.

Labeled data can come from:
  1. ShellSafe's own readings + field observations (recommended):
       python ml/train.py --readings ml/data/readings.csv --observations ml/data/observations.csv
  2. Any CSV that already has the feature columns and a 'label' column:
       python ml/train.py --dataset path/to/labeled.csv
  3. Pipeline test only (labels copied from the alert thresholds, so the
     scores are NOT valid results):
       python ml/train.py --readings ml/data/readings.csv --demo

Outputs:
  app/ml_models/metrics.json      comparison shown on the web app's Model page
  app/ml_models/bloom_model.json  best model, run by app/ml_service.py
  ml/reports/metrics.csv          table for the paper
  ml/reports/*.png                confusion matrices and comparison chart
"""

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import (
    GridSearchCV,
    StratifiedGroupKFold,
    StratifiedKFold,
    train_test_split,
)
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, 'app', 'ml_models')
REPORT_DIR = os.path.join(ROOT, 'ml', 'reports')
LOCAL_TZ = 'Asia/Manila'

ALL_FEATURES = ['temperature', 'ph', 'turbidity', 'orp', 'ec']
SEED = 42

# Same limits as the firmware's SMS alerts (shellsafev2.ino). Used only by
# --demo, which is why demo scores say nothing about real bloom prediction.
DEMO_RULE = {
    'ph': (6.5, 8.5),
    'turbidity': (None, 50.0),
    'temperature': (None, 35.0),
    'orp': (200.0, None),
}

MODELS = {
    'decision_tree': (
        'Decision Tree',
        DecisionTreeClassifier(class_weight='balanced', random_state=SEED),
        {'max_depth': [3, 5, 8, 12], 'min_samples_leaf': [1, 5, 20]},
    ),
    'svm': (
        'Support Vector Machine',
        Pipeline([
            ('scale', StandardScaler()),
            ('svc', SVC(kernel='rbf', class_weight='balanced')),
        ]),
        {'svc__C': [0.1, 1, 10, 100], 'svc__gamma': ['scale', 0.01, 0.1, 1]},
    ),
    'random_forest': (
        'Random Forest',
        RandomForestClassifier(n_estimators=100, class_weight='balanced',
                               random_state=SEED, n_jobs=-1),
        {'max_depth': [4, 8, 12], 'min_samples_leaf': [1, 5, 20]},
    ),
}


# ---------------------------------------------------------------- data ---

def _truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(['true', '1', 'yes'])


def load_readings(path: str, features: list) -> pd.DataFrame:
    """ShellSafe readings exported by ml/export_readings.py."""
    df = pd.read_csv(path)
    df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True)
    keep = df[features].notna().all(axis=1)
    for key in features:
        cal = f'cal_{key}'
        if cal in df.columns:
            keep &= _truthy(df[cal])
    dropped = int((~keep).sum())
    if dropped:
        print(f'Skipped {dropped} readings with a missing or uncalibrated probe.')
    return df[keep].copy()


def apply_observations(df: pd.DataFrame, path: str) -> pd.DataFrame:
    """Label each reading from the field observation window it falls in."""
    obs = pd.read_csv(path, comment='#')
    obs = obs.dropna(subset=['start', 'end', 'label'])
    label = pd.Series(np.nan, index=df.index)
    conflict = pd.Series(False, index=df.index)
    for row in obs.itertuples():
        start = pd.Timestamp(row.start).tz_localize(LOCAL_TZ).tz_convert('UTC')
        end = pd.Timestamp(row.end).tz_localize(LOCAL_TZ).tz_convert('UTC')
        value = 1 if str(row.label).strip().lower() in ('bloom', '1', 'yes', 'true') else 0
        inside = (df['time'] >= start) & (df['time'] <= end)
        conflict |= inside & label.notna() & (label != value)
        label[inside] = value
    if conflict.any():
        print(f'Dropped {int(conflict.sum())} readings covered by observations that disagree.')
    df = df.assign(label=label)[label.notna() & ~conflict]
    df['label'] = df['label'].astype(int)
    print(f'{len(df)} readings fall inside an observation window.')
    return df


def apply_demo_labels(df: pd.DataFrame) -> pd.DataFrame:
    bloom = pd.Series(False, index=df.index)
    for key, (low, high) in DEMO_RULE.items():
        if key not in df.columns:
            continue
        if low is not None:
            bloom |= df[key] < low
        if high is not None:
            bloom |= df[key] > high
    return df.assign(label=bloom.astype(int))


def load_dataset(path: str, features: list) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in features + ['label'] if c not in df.columns]
    if missing:
        sys.exit(f'{path} is missing columns: {", ".join(missing)}')
    df = df.dropna(subset=features + ['label']).copy()
    df['label'] = df['label'].map(
        lambda v: 1 if str(v).strip().lower() in ('bloom', '1', '1.0', 'yes', 'true') else 0
    )
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    return df


# --------------------------------------------------------------- split ---

def split_data(df: pd.DataFrame, features: list):
    """
    Hold out whole days when possible. Readings a minute apart are nearly
    identical, so a random split would put near-copies of the test rows in
    the training set and inflate every score.
    """
    X = df[features].to_numpy(dtype=float)
    y = df['label'].to_numpy(dtype=int)
    groups = None
    if 'time' in df.columns and df['time'].notna().all():
        groups = df['time'].dt.tz_convert(LOCAL_TZ).dt.strftime('%Y-%m-%d').to_numpy()

    if groups is not None:
        days_per_class = [len(set(groups[y == c])) for c in (0, 1)]
        if min(days_per_class) >= 2 and len(set(groups)) >= 5:
            splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
            train_idx, test_idx = next(splitter.split(X, y, groups))
            g_train, y_train = groups[train_idx], y[train_idx]
            # Every CV fold needs a day of each class, so no more folds
            # than the rarer class has training days.
            folds = min([5] + [len(set(g_train[y_train == c])) for c in (0, 1)])
            if len(set(y[test_idx])) == 2 and folds >= 2:
                cv = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=SEED)
                return (X[train_idx], X[test_idx], y_train, y[test_idx],
                        g_train, cv, 'held-out days')

    print('WARNING: not enough labeled days with both classes for a by-day split.\n'
          '         Falling back to a random split, which overstates the scores.')
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=SEED)
    return X_train, X_test, y_train, y_test, None, StratifiedKFold(5, shuffle=True, random_state=SEED), 'random 80/20'


# -------------------------------------------------------------- export ---

def _export_tree(estimator) -> dict:
    t = estimator.tree_
    bloom_col = list(estimator.classes_).index(1)
    values = t.value[:, 0, :]
    totals = values.sum(axis=1)
    totals[totals == 0] = 1
    leaf = t.children_left == -1
    p = np.where(leaf, values[:, bloom_col] / totals, 0.0)
    return {
        'left': t.children_left.tolist(),
        'right': t.children_right.tolist(),
        'feature': [int(f) if f >= 0 else 0 for f in t.feature],
        'threshold': [float(v) for v in t.threshold],
        'p': [round(float(v), 6) for v in p],
    }


def export_model(key: str, model, features: list) -> dict:
    out = {'kind': key, 'features': features}
    if key == 'decision_tree':
        out['tree'] = _export_tree(model)
    elif key == 'random_forest':
        out['trees'] = [_export_tree(est) for est in model.estimators_]
    elif key == 'svm':
        scaler, svc = model.named_steps['scale'], model.named_steps['svc']
        if list(svc.classes_) != [0, 1]:
            raise ValueError('SVM export expects classes [0, 1]')
        out.update({
            'scaler_mean': scaler.mean_.tolist(),
            'scaler_scale': scaler.scale_.tolist(),
            'gamma': float(svc._gamma),
            'intercept': float(svc.intercept_[0]),
            'dual_coef': svc.dual_coef_[0].tolist(),
            'support_vectors': svc.support_vectors_.tolist(),
        })
    return out


def _load_ml_service():
    # Load by path so training does not import the Flask app package.
    path = os.path.join(ROOT, 'app', 'ml_service.py')
    spec = importlib.util.spec_from_file_location('shellsafe_ml_service', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_export(exported: dict, model, X: np.ndarray) -> float:
    """Share of rows where the web app's prediction matches scikit-learn's."""
    service = _load_ml_service()
    ours = np.array([service.predict_features(exported, list(row))['label'] for row in X])
    return float((ours == model.predict(X)).mean())


# --------------------------------------------------------------- report ---

def save_figures(results: list, labels: list) -> None:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print('matplotlib not installed; skipping figures.')
        return

    for r in results:
        cm = np.array(r['confusion_matrix'])
        fig, ax = plt.subplots(figsize=(3.6, 3.2), dpi=150)
        ax.imshow(cm, cmap='Blues')
        for (i, j), v in np.ndenumerate(cm):
            ax.text(j, i, str(v), ha='center', va='center',
                    color='white' if v > cm.max() / 2 else 'black')
        ax.set_xticks([0, 1], labels)
        ax.set_yticks([0, 1], labels)
        ax.set_xlabel('Predicted')
        ax.set_ylabel('Actual')
        ax.set_title(r['name'], fontsize=10)
        fig.tight_layout()
        fig.savefig(os.path.join(REPORT_DIR, f"confusion_{r['key']}.png"))
        plt.close(fig)

    names = [r['name'] for r in results]
    metrics = ['accuracy', 'precision', 'recall', 'f1']
    width = 0.2
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    for i, m in enumerate(metrics):
        ax.bar(np.arange(len(names)) + (i - 1.5) * width,
               [r['test'][m] for r in results], width, label=m.capitalize())
    ax.set_xticks(np.arange(len(names)), names)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel('Score on test set')
    ax.legend(ncol=4, fontsize=8, loc='lower center', bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout()
    fig.savefig(os.path.join(REPORT_DIR, 'model_comparison.png'))
    plt.close(fig)


# ----------------------------------------------------------------- main ---

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--readings', help='CSV from ml/export_readings.py')
    parser.add_argument('--observations', help='field observations CSV (start,end,label,...)')
    parser.add_argument('--dataset', help='CSV that already has a label column')
    parser.add_argument('--demo', action='store_true',
                        help='label readings with the alert thresholds (pipeline test only)')
    parser.add_argument('--features', default=','.join(ALL_FEATURES),
                        help='comma-separated model inputs (default: all five probes)')
    args = parser.parse_args()

    features = [f.strip() for f in args.features.split(',') if f.strip()]
    unknown = [f for f in features if f not in ALL_FEATURES]
    if unknown:
        sys.exit(f'Unknown feature(s): {", ".join(unknown)}. Choose from {", ".join(ALL_FEATURES)}.')

    if args.dataset:
        df = load_dataset(args.dataset, features)
        source = os.path.basename(args.dataset)
    elif args.readings and (args.observations or args.demo):
        df = load_readings(args.readings, features)
        if args.demo:
            df = apply_demo_labels(df)
            source = 'ShellSafe readings, threshold labels (DEMO)'
        else:
            df = apply_observations(df, args.observations)
            source = 'ShellSafe readings + field observations'
    else:
        parser.error('give --dataset, or --readings with --observations (or --demo)')

    counts = df['label'].value_counts().to_dict()
    n_bloom, n_clear = int(counts.get(1, 0)), int(counts.get(0, 0))
    print(f'Labeled rows: {len(df)}  (bloom {n_bloom}, no bloom {n_clear})')
    if min(n_bloom, n_clear) < 10:
        sys.exit('Need at least 10 labeled rows of each class (bloom and no bloom) to train.')

    X_train, X_test, y_train, y_test, groups, cv, split_name = split_data(df, features)
    print(f'Split: {split_name}  train {len(y_train)}, test {len(y_test)}\n')

    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    results, fitted = [], {}
    for key, (name, estimator, grid) in MODELS.items():
        started = time.time()
        search = GridSearchCV(clone(estimator), grid, scoring='f1', cv=cv, n_jobs=-1)
        search.fit(X_train, y_train, groups=groups)
        model = search.best_estimator_
        pred = model.predict(X_test)
        tn, fp, fn, tp = confusion_matrix(y_test, pred, labels=[0, 1]).ravel()
        result = {
            'key': key,
            'name': name,
            'best_params': {k.replace('svc__', ''): v for k, v in search.best_params_.items()},
            'cv_f1_mean': float(search.best_score_),
            'cv_f1_std': float(search.cv_results_['std_test_score'][search.best_index_]),
            'test': {
                'accuracy': float(accuracy_score(y_test, pred)),
                'precision': float(precision_score(y_test, pred, zero_division=0)),
                'recall': float(recall_score(y_test, pred, zero_division=0)),
                'f1': float(f1_score(y_test, pred, zero_division=0)),
            },
            'confusion_matrix': [[int(tn), int(fp)], [int(fn), int(tp)]],
            'train_seconds': round(time.time() - started, 2),
        }
        results.append(result)
        fitted[key] = model
        t = result['test']
        print(f"{name:24s} acc {t['accuracy']:.3f}  prec {t['precision']:.3f}  "
              f"rec {t['recall']:.3f}  F1 {t['f1']:.3f}  (CV F1 {result['cv_f1_mean']:.3f})")

    best = max(results, key=lambda r: (r['test']['f1'], r['cv_f1_mean']))
    print(f"\nBest by test F1: {best['name']}")

    exported = export_model(best['key'], fitted[best['key']], features)
    agreement = verify_export(exported, fitted[best['key']], X_test)
    if agreement < 1.0:
        sys.exit(f'Exported model disagrees with scikit-learn on {100 * (1 - agreement):.2f}% '
                 'of test rows; not saving it.')

    trained_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    exported.update({
        'name': best['name'],
        'demo': bool(args.demo),
        'test_f1': best['test']['f1'],
        'trained_at': trained_at,
    })
    with open(os.path.join(MODEL_DIR, 'bloom_model.json'), 'w', encoding='utf-8') as fh:
        json.dump(exported, fh, separators=(',', ':'))

    metrics = {
        'trained_at': trained_at,
        'demo': bool(args.demo),
        'source': source,
        'features': features,
        'rows': len(df),
        'class_counts': {'bloom': n_bloom, 'no_bloom': n_clear},
        'split': split_name,
        'train_rows': int(len(y_train)),
        'test_rows': int(len(y_test)),
        'best': best['key'],
        'models': results,
    }
    with open(os.path.join(MODEL_DIR, 'metrics.json'), 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, indent=2)

    pd.DataFrame([{
        'Model': r['name'],
        'Accuracy': round(r['test']['accuracy'], 4),
        'Precision': round(r['test']['precision'], 4),
        'Recall': round(r['test']['recall'], 4),
        'F1-Score': round(r['test']['f1'], 4),
        'CV F1 (mean)': round(r['cv_f1_mean'], 4),
        'CV F1 (std)': round(r['cv_f1_std'], 4),
        'Best parameters': json.dumps(r['best_params']),
    } for r in results]).to_csv(os.path.join(REPORT_DIR, 'metrics.csv'), index=False)

    save_figures(results, ['No bloom', 'Bloom'])
    print(f'Saved model and metrics to {MODEL_DIR}, report to {REPORT_DIR}')
    if args.demo:
        print('\nDEMO MODE: labels came from the alert thresholds, so these scores only show\n'
              'the pipeline works. Do not report them as results.')


if __name__ == '__main__':
    main()
