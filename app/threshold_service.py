"""
Configurable sensor thresholds (Normal / Warning / Alert) stored in Firebase RTDB.
Used by web risk assessment and in-app alerts. Device SMS still uses firmware constants
until the ESP is updated to read this config.
"""

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

from firebase_admin import db

from firebase_config import initialize_firebase

THRESHOLD_CONFIG_PATH = '/threshold_config'

# Defaults aligned with shellsafev2.ino alert edges + sensible warning bands
DEFAULT_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    'temperature': {
        'label': 'Temperature',
        'unit': '°C',
        'normal_min': 20.0,
        'normal_max': 30.0,
        'warning_min': 15.0,
        'warning_max': 32.0,
        'alert_min': None,
        'alert_max': 35.0,
    },
    'ph': {
        'label': 'pH',
        'unit': '',
        'normal_min': 6.8,
        'normal_max': 8.2,
        'warning_min': 6.5,
        'warning_max': 8.5,
        'alert_min': 6.0,
        'alert_max': 9.0,
    },
    'turbidity': {
        'label': 'Turbidity',
        'unit': ' NTU',
        'normal_min': 0.0,
        'normal_max': 30.0,
        'warning_min': 0.0,
        'warning_max': 50.0,
        'alert_min': None,
        'alert_max': 100.0,
    },
    'orp': {
        'label': 'ORP',
        'unit': ' mV',
        'normal_min': 0.0,
        'normal_max': 1000.0,
        'warning_min': -100.0,
        'warning_max': 1100.0,
        'alert_min': -200.0,
        'alert_max': None,
    },
    'ec': {
        'label': 'EC',
        'unit': ' µS/cm',
        'normal_min': 0.0,
        'normal_max': 1500.0,
        'warning_min': 0.0,
        'warning_max': 2000.0,
        'alert_min': None,
        'alert_max': 2500.0,
    },
}

SENSOR_ORDER = ('temperature', 'ph', 'turbidity', 'orp', 'ec')

_cache: Dict[str, Any] = {'data': None, 'expires': 0.0}
_CACHE_TTL = 5.0


def _to_optional_float(value) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_sensor(key: str, raw: Optional[Dict]) -> Dict[str, Any]:
    base = deepcopy(DEFAULT_THRESHOLDS[key])
    if not isinstance(raw, dict):
        return base
    for field in (
        'normal_min', 'normal_max',
        'warning_min', 'warning_max',
        'alert_min', 'alert_max',
    ):
        if field in raw:
            base[field] = _to_optional_float(raw.get(field))
    return base


def get_default_thresholds() -> Dict[str, Dict[str, Any]]:
    return deepcopy(DEFAULT_THRESHOLDS)


def get_thresholds(use_cache: bool = True) -> Dict[str, Dict[str, Any]]:
    """Return full threshold map for all sensors."""
    import time
    now = time.time()
    if use_cache and _cache['data'] is not None and now < _cache['expires']:
        return deepcopy(_cache['data'])

    initialize_firebase()
    try:
        raw = db.reference(THRESHOLD_CONFIG_PATH).get() or {}
    except Exception:
        raw = {}

    sensors_raw = raw.get('sensors') if isinstance(raw, dict) else {}
    if not isinstance(sensors_raw, dict):
        sensors_raw = raw if isinstance(raw, dict) else {}

    result = {}
    for key in SENSOR_ORDER:
        result[key] = _merge_sensor(key, sensors_raw.get(key))

    _cache['data'] = result
    _cache['expires'] = now + _CACHE_TTL
    return deepcopy(result)


_BAND_ORDER = (
    ('alert_min', 'Alert below'),
    ('normal_min', 'Normal from'),
    ('normal_max', 'Normal to'),
    ('alert_max', 'Alert above'),
)


def validate_bands(key: str, cfg: Dict[str, Any]) -> None:
    """
    Limits must run low to high: Alert below <= Normal from <= Normal to
    <= Alert above (empty alert limits are skipped). classify_value checks
    the alert edges first, so an alert limit inside the normal range would
    flag normal readings as High Risk.
    """
    if cfg.get('normal_min') is None or cfg.get('normal_max') is None:
        raise ValueError(f"{DEFAULT_THRESHOLDS[key]['label']}: fill in both ends of the normal range.")
    label = DEFAULT_THRESHOLDS[key]['label']
    set_limits = [(name, cfg.get(field)) for field, name in _BAND_ORDER
                  if cfg.get(field) is not None]
    for (low_name, low), (high_name, high) in zip(set_limits, set_limits[1:]):
        if low > high:
            raise ValueError(
                f'{label}: {low_name} ({low:g}) must not be higher than {high_name} ({high:g}).'
            )


def set_thresholds(sensors: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Persist threshold config and refresh cache."""
    cleaned = {}
    for key in SENSOR_ORDER:
        cleaned[key] = _merge_sensor(key, sensors.get(key) if isinstance(sensors, dict) else None)
        # Warning is simply "outside normal, inside the alert limits", so the
        # stored warning band mirrors the normal range. Kept for older readers.
        cleaned[key]['warning_min'] = cleaned[key]['normal_min']
        cleaned[key]['warning_max'] = cleaned[key]['normal_max']
        validate_bands(key, cleaned[key])

    payload = {
        'sensors': cleaned,
        'updated_at': datetime.utcnow().isoformat() + 'Z',
    }
    initialize_firebase()
    db.reference(THRESHOLD_CONFIG_PATH).set(payload)

    import time
    _cache['data'] = cleaned
    _cache['expires'] = time.time() + _CACHE_TTL
    return deepcopy(cleaned)


def thresholds_for_form() -> List[Dict[str, Any]]:
    """Flat list for settings template."""
    data = get_thresholds()
    rows = []
    for key in SENSOR_ORDER:
        row = {'key': key, **data[key]}
        rows.append(row)
    return rows


def classify_value(sensor_key: str, value: Optional[float], thresholds: Optional[Dict] = None) -> str:
    """
    Return 'normal' | 'warning' | 'high' | 'unknown'.
    Past an alert limit is 'high'; outside the normal range is 'warning'.
    """
    if value is None:
        return 'unknown'

    cfg = (thresholds or get_thresholds()).get(sensor_key) or DEFAULT_THRESHOLDS.get(sensor_key)
    if not cfg:
        return 'unknown'

    alert_min = cfg.get('alert_min')
    alert_max = cfg.get('alert_max')
    if alert_min is not None and value < alert_min:
        return 'high'
    if alert_max is not None and value > alert_max:
        return 'high'

    normal_min = cfg.get('normal_min')
    normal_max = cfg.get('normal_max')
    if normal_min is not None and value < normal_min:
        return 'warning'
    if normal_max is not None and value > normal_max:
        return 'warning'

    return 'normal'
