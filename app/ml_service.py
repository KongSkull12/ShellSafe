"""
Algal bloom prediction from the model trained by ml/train.py.

train.py exports the best model (Decision Tree, SVM or Random Forest) to
app/ml_models/bloom_model.json, and this module runs it in plain Python so
the web app does not need scikit-learn (too large for the Vercel bundle).
train.py checks that these predictions match scikit-learn's before saving.

No prediction is made from a reading unless every model input is connected
and calibrated: a model fed raw uncalibrated values would give a confident
but meaningless answer.
"""

import json
import math
import os
import struct
from typing import Dict, List, Optional

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_models')
MODEL_PATH = os.path.join(MODEL_DIR, 'bloom_model.json')
METRICS_PATH = os.path.join(MODEL_DIR, 'metrics.json')

FEATURE_LABELS = {
    'temperature': 'Temperature',
    'ph': 'pH',
    'turbidity': 'Turbidity',
    'orp': 'ORP',
    'ec': 'EC',
}

_cache: Dict[str, Dict] = {}


def _load_json(path: str) -> Optional[Dict]:
    """Read a JSON file, reloading only when it changes on disk."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _cache.pop(path, None)
        return None
    cached = _cache.get(path)
    if cached and cached['mtime'] == mtime:
        return cached['data']
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    _cache[path] = {'mtime': mtime, 'data': data}
    return data


def load_model() -> Optional[Dict]:
    return _load_json(MODEL_PATH)


def load_metrics() -> Optional[Dict]:
    return _load_json(METRICS_PATH)


def _f32(value: float) -> float:
    # scikit-learn trees compare float32 inputs; match that exactly.
    return struct.unpack('f', struct.pack('f', float(value)))[0]


def _tree_bloom_probability(tree: Dict, x: List[float]) -> float:
    left, right = tree['left'], tree['right']
    feature, threshold = tree['feature'], tree['threshold']
    node = 0
    while left[node] != -1:
        node = left[node] if _f32(x[feature[node]]) <= threshold[node] else right[node]
    return tree['p'][node]


def predict_features(model: Dict, x: List[float]) -> Dict:
    """
    Run the exported model on one feature vector (in model['features'] order).
    Returns {'label': 0|1, 'probability': float|None, 'score': float}.
    Trees give a bloom probability; the SVM gives a signed decision value.
    """
    kind = model['kind']
    if kind == 'decision_tree':
        p = _tree_bloom_probability(model['tree'], x)
        return {'label': 1 if p > 0.5 else 0, 'probability': p, 'score': p}
    if kind == 'random_forest':
        trees = model['trees']
        p = sum(_tree_bloom_probability(t, x) for t in trees) / len(trees)
        return {'label': 1 if p > 0.5 else 0, 'probability': p, 'score': p}
    if kind == 'svm':
        mean, scale = model['scaler_mean'], model['scaler_scale']
        z = [(v - m) / s for v, m, s in zip(x, mean, scale)]
        gamma = model['gamma']
        decision = model['intercept']
        for coef, sv in zip(model['dual_coef'], model['support_vectors']):
            dist = sum((a - b) * (a - b) for a, b in zip(sv, z))
            decision += coef * math.exp(-gamma * dist)
        return {'label': 1 if decision > 0 else 0, 'probability': None, 'score': decision}
    raise ValueError(f'Unknown model kind: {kind}')


def predict_bloom(reading: Optional[Dict]) -> Dict:
    """Prediction view model for the dashboard."""
    model = load_model()
    if not model:
        return {
            'available': False,
            'has_prediction': False,
            'message': 'No prediction model has been trained yet.',
        }

    base = {
        'available': True,
        'has_prediction': False,
        'model_name': model.get('name'),
        'demo': bool(model.get('demo')),
        'test_f1': model.get('test_f1'),
    }

    if not reading or reading.get('link_state') != 'live':
        base['message'] = 'Waiting for live readings.'
        return base

    calibrated = reading.get('calibrated') or {}
    missing = []
    x = []
    for key in model['features']:
        value = reading.get(key)
        connected = reading.get(f'{key}_connected', value is not None)
        if value is None or not connected or calibrated.get(key) is False:
            missing.append(FEATURE_LABELS.get(key, key))
        else:
            x.append(float(value))
    if missing:
        base['message'] = 'Needs a calibrated reading from: ' + ', '.join(missing) + '.'
        return base

    result = predict_features(model, x)
    bloom = result['label'] == 1
    base.update({
        'has_prediction': True,
        'label': 'bloom' if bloom else 'no_bloom',
        'title': 'Bloom likely' if bloom else 'No bloom expected',
        'probability': result['probability'],
        'score': result['score'],
        'message': (
            f"{model.get('name')} predicts "
            + ('bloom conditions' if bloom else 'no bloom')
            + (f" ({result['probability'] * 100:.0f}% bloom probability)."
               if result['probability'] is not None else '.')
        ),
    })
    return base
