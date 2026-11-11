"""
Water quality reports built from the device's minute log.

A report is a snapshot: it is computed once from /readings (Realtime
Database), the configured thresholds, the alerts collection and the bloom
model, then saved to Firestore so it reads the same later even after the
underlying data changes.

Readings a probe cannot physically produce (pH 0, turbidity pinned at the
1000 NTU ceiling, EC above seawater) are counted as sensor faults and left
out of the averages, so one bad probe does not distort the summary.
"""

import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from firebase_admin import db

from firebase_config import initialize_firebase
from app.alert_helpers import MANILA, normalize_alerts
from app.ml_service import load_model, predict_features
from app.salinity import salinity_psu
from app.threshold_service import classify_value, get_thresholds

READINGS_PATH = '/readings'

PERIODS = {
    '1': ('Daily', timedelta(days=1)),
    '7': ('Weekly', timedelta(days=7)),
    '30': ('Monthly', timedelta(days=30)),
}

# (key, label, unit, decimals, (lowest plausible, highest plausible))
SENSORS: Tuple[Tuple[str, str, str, int, Tuple[float, float]], ...] = (
    ('temperature', 'Temperature', '°C', 1, (-2.0, 45.0)),
    ('ph', 'pH', '', 2, (1.0, 13.0)),
    ('turbidity', 'Turbidity', 'NTU', 1, (0.0, 999.0)),
    ('orp', 'ORP', 'mV', 0, (-1000.0, 1000.0)),
    ('ec', 'EC', 'µS/cm', 0, (1.0, 100000.0)),
    ('salinity', 'Salinity', 'ppt', 2, (0.0, 45.0)),
)
# The firmware logs about one reading a minute.
EXPECTED_INTERVAL_S = 60.0

_PUSH_CHARS = '-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz'


def _push_key_prefix(epoch_ms: int) -> str:
    """Firebase push keys start with their creation time, so they sort by time."""
    chars = []
    for _ in range(8):
        chars.append(_PUSH_CHARS[epoch_ms % 64])
        epoch_ms //= 64
    return ''.join(reversed(chars))


def _num(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _epoch(value) -> Optional[float]:
    t = _num(value)
    if t is None:
        return None
    return t / 1000.0 if t > 10_000_000_000 else t


def _fetch_readings(start: datetime, end: datetime) -> List[Dict]:
    initialize_firebase()
    prefix = _push_key_prefix(int(start.timestamp() * 1000))
    raw = db.reference(READINGS_PATH).order_by_key().start_at(prefix).get() or {}
    rows = []
    lo, hi = start.timestamp(), end.timestamp()
    for record in (raw.values() if isinstance(raw, dict) else []):
        if not isinstance(record, dict):
            continue
        t = _epoch(record.get('t'))
        if t is None or not lo <= t <= hi:
            continue
        row = {'t': t, 'cal': record.get('cal') or {}}
        for key, *_ in SENSORS:
            row[key] = _num(record.get(key))
        if row['salinity'] is None and row['ec'] is not None and row['temperature'] is not None:
            row['salinity'] = salinity_psu(row['ec'], row['temperature'])
        rows.append(row)
    rows.sort(key=lambda r: r['t'])
    return rows


def _local(ts: float) -> str:
    return datetime.fromtimestamp(ts, MANILA).strftime('%b %d, %I:%M %p')


def _duration(seconds: float) -> str:
    hours = seconds / 3600.0
    if hours >= 48:
        return f'{hours / 24:.1f} days'
    if hours >= 1:
        return f'{hours:.1f} hours'
    return f'{max(seconds / 60.0, 0):.0f} minutes'


def _valid(key: str, value: Optional[float], cal: Dict) -> bool:
    if value is None:
        return False
    if key in cal and cal.get(key) is False:
        return False
    low, high = next(s[4] for s in SENSORS if s[0] == key)
    return low <= value <= high


def _sensor_stats(rows: List[Dict], thresholds: Dict) -> List[Dict]:
    out = []
    for key, label, unit, decimals, _ in SENSORS:
        present = [r for r in rows if r.get(key) is not None]
        good = [r for r in present
                if _valid(key, r[key], r['cal'])
                and (key != 'salinity' or _valid('ec', r.get('ec'), r['cal']))]
        values = [r[key] for r in good]
        levels = Counter(classify_value(key, v, thresholds) for v in values) if key in thresholds else Counter()
        n = len(values)
        stat = {
            'key': key,
            'label': label,
            'unit': unit,
            'readings': len(present),
            'faulty': len(present) - n,
            'faulty_pct': round(100.0 * (len(present) - n) / len(present), 1) if present else 0.0,
            'min': round(min(values), decimals) if values else None,
            'avg': round(sum(values) / n, decimals) if values else None,
            'max': round(max(values), decimals) if values else None,
            'latest': round(good[-1][key], decimals) if good else None,
            'has_thresholds': key in thresholds,
            'normal_pct': round(100.0 * levels.get('normal', 0) / n, 1) if n and levels else None,
            'warning_pct': round(100.0 * levels.get('warning', 0) / n, 1) if n and levels else None,
            'alert_pct': round(100.0 * levels.get('high', 0) / n, 1) if n and levels else None,
        }
        if values:
            top = max(good, key=lambda r: r[key])
            stat['max_at'] = _local(top['t'])
        out.append(stat)
    return out


def _coverage(rows: List[Dict], start: datetime, end: datetime) -> Dict:
    span = (end - start).total_seconds()
    expected = max(int(span // EXPECTED_INTERVAL_S), 1)
    edges = [start.timestamp()] + [r['t'] for r in rows] + [end.timestamp()]
    gaps = [(edges[i + 1] - edges[i], edges[i]) for i in range(len(edges) - 1)]
    longest, gap_start = max(gaps) if gaps else (span, start.timestamp())
    return {
        'readings': len(rows),
        'expected': expected,
        'pct': round(min(100.0, 100.0 * len(rows) / expected), 1),
        'first': _local(rows[0]['t']) if rows else None,
        'last': _local(rows[-1]['t']) if rows else None,
        'longest_gap': _duration(longest),
        'longest_gap_s': longest,
        'longest_gap_from': _local(gap_start),
    }


def _hourly(rows: List[Dict]) -> List[Dict]:
    buckets: Dict[int, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        hour = int(r['t'] // 3600) * 3600
        for key, *_ in SENSORS:
            v = r.get(key)
            ok = _valid(key, v, r['cal']) and (key != 'salinity' or _valid('ec', r.get('ec'), r['cal']))
            if ok:
                buckets[hour][key].append(v)
    hours = []
    for hour in sorted(buckets):
        means = {k: sum(v) / len(v) for k, v in buckets[hour].items() if v}
        hours.append({'t': hour, **means})
    return hours


def _risk_and_model(hours: List[Dict], thresholds: Dict) -> Dict:
    rank = {'normal': 0, 'warning': 1, 'high': 2}
    risk = Counter()
    for h in hours:
        levels = [classify_value(k, h[k], thresholds) for k in thresholds if k in h]
        levels = [lv for lv in levels if lv in rank]
        if levels:
            risk[max(levels, key=rank.get)] += 1

    model = load_model()
    result = {
        'hours': len(hours),
        'risk_normal': risk.get('normal', 0),
        'risk_warning': risk.get('warning', 0),
        'risk_high': risk.get('high', 0),
        'model_name': model.get('name') if model else None,
        'model_hours': 0,
        'bloom_hours': 0,
        'peak_probability': None,
        'peak_at': None,
    }
    if not model:
        return result
    features = model.get('features') or []
    for h in hours:
        if not all(f in h for f in features):
            continue
        pred = predict_features(model, [h[f] for f in features])
        result['model_hours'] += 1
        result['bloom_hours'] += pred['label']
        p = pred.get('probability')
        if p is not None and (result['peak_probability'] is None or p > result['peak_probability']):
            result['peak_probability'] = round(p, 3)
            result['peak_at'] = _local(h['t'])
    return result


def _alerts(start: datetime, end: datetime) -> Dict:
    from app.firestore_service import get_firestore_service
    try:
        raw = get_firestore_service().get_all_alerts(exclude_deleted=True)
    except Exception:
        raw = []
    alerts = [a for a in normalize_alerts(raw) if start <= a['created_at'] <= end]
    by_level = Counter(a['risk_level'] or 'Unknown' for a in alerts)
    by_source = Counter()
    for a in alerts:
        msg = a['alert_message'] or ''
        source = msg.split(' alert', 1)[0].strip() if ' alert' in msg[:40] else a['alert_title']
        by_source[source] += 1
    recent = [
        {'at': a['created_at'].astimezone(MANILA).strftime('%b %d, %I:%M %p'),
         'level': a['risk_level'], 'message': (a['alert_message'] or a['alert_title'])[:160]}
        for a in sorted(alerts, key=lambda a: a['created_at'], reverse=True)[:10]
    ]
    return {
        'total': len(alerts),
        'by_level': dict(by_level.most_common()),
        'by_source': dict(by_source.most_common(6)),
        'recent': recent,
    }


def _findings(coverage: Dict, sensors: List[Dict], risk: Dict, alerts: Dict) -> List[Dict]:
    """Plain-language key points, most important first."""
    out = []
    if coverage['readings'] == 0:
        return [{'level': 'high', 'text': 'No readings reached Firebase in this period. Check the device power and connection.'}]
    if coverage['pct'] < 90:
        out.append({'level': 'warning', 'text':
                    f"The device reported {coverage['pct']}% of the time. Its longest silence was "
                    f"{coverage['longest_gap']}, starting {coverage['longest_gap_from']}."})
    for s in sensors:
        if s['readings'] and s['faulty_pct'] >= 5:
            out.append({'level': 'warning', 'text':
                        f"{s['label']}: {s['faulty']} readings ({s['faulty_pct']}%) were impossible values "
                        f"and were left out. Check or recalibrate this probe."})
    for s in sensors:
        if s['alert_pct']:
            out.append({'level': 'high', 'text':
                        f"{s['label']} was past its alert limit {s['alert_pct']}% of the time "
                        f"(highest {s['max']}{(' ' + s['unit']) if s['unit'] else ''}, {s.get('max_at', '')})."})
    if risk['model_hours']:
        if risk['bloom_hours']:
            out.append({'level': 'high', 'text':
                        f"The {risk['model_name']} model predicted bloom conditions in {risk['bloom_hours']} "
                        f"of {risk['model_hours']} hours (peak {round((risk['peak_probability'] or 0) * 100)}% "
                        f"on {risk['peak_at']})."})
        else:
            out.append({'level': 'normal', 'text':
                        f"The {risk['model_name']} model predicted no bloom in any of {risk['model_hours']} hours."})
    if alerts['total']:
        top = next(iter(alerts['by_source']), None)
        out.append({'level': 'warning', 'text':
                    f"{alerts['total']} alerts were raised"
                    + (f"; most came from {top} ({alerts['by_source'][top]})." if top else '.')})
    if not any(f['level'] in ('warning', 'high') for f in out):
        out.insert(0, {'level': 'normal', 'text': 'All valid readings stayed within the configured safe ranges.'})
    return out


def build_report(period: str, now: Optional[datetime] = None) -> Dict:
    if period not in PERIODS:
        raise ValueError('Unknown report period')
    report_type, span = PERIODS[period]
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = end - span
    started = time.time()

    rows = _fetch_readings(start, end)
    thresholds = get_thresholds()
    sensors = _sensor_stats(rows, thresholds)
    coverage = _coverage(rows, start, end)
    risk = _risk_and_model(_hourly(rows), thresholds)
    alerts = _alerts(start, end)

    local_start, local_end = start.astimezone(MANILA), end.astimezone(MANILA)
    if period == '1':
        name_range = f"{local_start:%b %d, %I:%M %p} – {local_end:%b %d, %Y %I:%M %p}"
    else:
        name_range = f"{local_start:%b %d} – {local_end:%b %d, %Y}"
    return {
        'report_name': f'Water quality report · {name_range}',
        'report_type': report_type,
        'summary': {
            'period': period,
            'start': start,
            'end': end,
            'start_label': f'{local_start:%b %d, %Y %I:%M %p}',
            'end_label': f'{local_end:%b %d, %Y %I:%M %p}',
            'coverage': coverage,
            'sensors': sensors,
            'risk': risk,
            'alerts': alerts,
            'findings': _findings(coverage, sensors, risk, alerts),
            'build_seconds': round(time.time() - started, 2),
        },
    }
