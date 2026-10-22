"""
Bloom risk assessment based on live sensor readings and configurable thresholds.
"""

from typing import Dict, Optional

from app.threshold_service import (
    DEFAULT_THRESHOLDS,
    SENSOR_ORDER,
    classify_value,
    get_thresholds,
)

LEVEL_SCORES = {
    'normal': 0,
    'warning': 1,
    'high': 2,
    'unknown': 0,
    'disconnected': 0,
}

LEVEL_LABELS = {
    'normal': 'Normal',
    'warning': 'Warning',
    'high': 'High Risk',
    'unknown': 'Unknown',
    'disconnected': 'Disconnected',
}

# Overall levels that mean "no verdict": risk is never stated from stale data.
NO_VERDICT_LEVELS = frozenset({'offline', 'checking', 'nodata', 'idle'})

OVERALL_MESSAGES = {
    'normal': 'All monitored parameters are within configured safe ranges.',
    'warning': 'One or more parameters are in the warning band. Monitor closely.',
    'high': 'Alert thresholds exceeded. Possible algal bloom conditions.',
}

CONNECTION_FLAGS = {
    'temperature': 'temperature_connected',
    'ph': 'ph_connected',
    'turbidity': 'turbidity_connected',
    'orp': 'orp_connected',
    'ec': 'ec_connected',
}

# Kept for any legacy imports
SENSOR_THRESHOLDS = DEFAULT_THRESHOLDS


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {
        'disconnected', 'offline', 'n/a', 'na', 'none', 'null', '',
    }:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sensor_connected(sensor_data: Dict, sensor_key: str) -> bool:
    flag = CONNECTION_FLAGS.get(sensor_key)
    if flag and flag in sensor_data:
        return bool(sensor_data.get(flag))
    return _to_float(sensor_data.get(sensor_key)) is not None


def _format_display(key: str, value: float, unit: str) -> str:
    if key == 'temperature':
        return f'{value:.1f}{unit}'
    if key == 'ph':
        return f'{value:.2f}'
    if key in ('turbidity', 'orp', 'ec'):
        return f'{value:.1f}{unit.strip()}'
    return f'{value:.1f}{unit}'


def _assess_parameter(key: str, value: Optional[float], connected: bool, thresholds: Dict) -> Dict:
    cfg = thresholds.get(key) or DEFAULT_THRESHOLDS.get(key, {})
    name = cfg.get('label', key)
    unit = cfg.get('unit', '')

    if not connected or value is None:
        return {
            'key': key,
            'name': name,
            'value': None,
            'display': 'Disconnected',
            'level': 'disconnected',
            'label': 'Disconnected',
        }

    level = classify_value(key, value, thresholds)
    return {
        'key': key,
        'name': name,
        'value': value,
        'display': _format_display(key, value, unit),
        'level': level if level != 'unknown' else 'unknown',
        'label': LEVEL_LABELS.get(level, 'Unknown'),
    }


def assess_bloom_risk(sensor_data: Optional[Dict]) -> Dict:
    if not sensor_data:
        return _empty_assessment('nodata')

    link_state = sensor_data.get('link_state') or (
        'live' if sensor_data.get('is_online', True) else 'offline'
    )
    if link_state == 'checking':
        return _empty_assessment('checking')
    if link_state != 'live':
        empty = _empty_assessment('offline')
        last = sensor_data.get('last_update')
        if last and last != 'unknown':
            empty['message'] = f'Device offline. Last reading {last}. Risk is not assessed on old data.'
        return empty

    thresholds = get_thresholds()
    parameters = []
    calibrated = sensor_data.get('calibrated') or {}
    for key in SENSOR_ORDER:
        connected = _sensor_connected(sensor_data, key)
        value = _to_float(sensor_data.get(key)) if connected else None
        param = _assess_parameter(key, value, connected, thresholds)
        if connected and value is not None and calibrated.get(key) is False:
            param['level'] = 'uncalibrated'
            param['label'] = 'Not calibrated'
        parameters.append(param)

    active_parameters = [
        p for p in parameters
        if p['level'] not in ('unknown', 'disconnected', 'uncalibrated')
    ]

    if not active_parameters:
        empty = _empty_assessment('idle')
        empty['parameters'] = parameters
        if any(p['level'] == 'uncalibrated' for p in parameters):
            empty['overall_label'] = 'Needs calibration'
            empty['message'] = 'Probes are reading, but none is calibrated yet, so no risk verdict is given.'
        return empty

    distribution = {'normal': 0, 'warning': 0, 'high': 0}
    max_score = 0
    overall_level = 'normal'

    for param in active_parameters:
        distribution[param['level']] = distribution.get(param['level'], 0) + 1
        score = LEVEL_SCORES.get(param['level'], 0)
        if score > max_score:
            max_score = score
            overall_level = param['level']

    total = len(active_parameters)
    risk_score = round((max_score / 2) * 100 + (distribution.get('warning', 0) / total) * 15, 1)
    ui = _ui_for_level(overall_level)

    return {
        'overall_level': overall_level,
        'overall_label': ui['label'],
        'overall_score': risk_score,
        'message': OVERALL_MESSAGES[overall_level],
        'card_class': ui['card_class'],
        'card_bg': ui['card_bg'],
        'dial_class': ui['dial_class'],
        'dial_color': ui['dial_color'],
        'dial_bg': ui['dial_bg'],
        'parameters': parameters,
        'distribution': distribution,
        'has_verdict': True,
        'triggered': [p for p in active_parameters if p['level'] != 'normal'],
        'disconnected': [p for p in parameters if p['level'] == 'disconnected'],
        'thresholds': thresholds,
    }


def _ui_for_level(level: str) -> Dict:
    mapping = {
        'normal': {
            'label': 'Normal',
            'card_class': 'text-white',
            'card_bg': 'bg-success',
            'dial_class': 'risk-dial-normal',
            'dial_color': '#1f8a5a',
            'dial_bg': 'rgba(31, 138, 90, 0.12)',
        },
        'warning': {
            'label': 'Warning',
            'card_class': 'text-dark',
            'card_bg': 'bg-warning',
            'dial_class': 'risk-dial-warning',
            'dial_color': '#c47a1a',
            'dial_bg': 'rgba(196, 122, 26, 0.12)',
        },
        'high': {
            'label': 'High Risk',
            'card_class': 'text-white',
            'card_bg': 'bg-danger',
            'dial_class': 'risk-dial-high',
            'dial_color': '#c44536',
            'dial_bg': 'rgba(196, 69, 54, 0.12)',
        },
    }
    return mapping.get(level, mapping['normal'])


EMPTY_STATES = {
    'nodata': ('No data', 'No reading from the device has reached Firebase yet.'),
    'checking': ('Connecting', 'Checking whether the device is still publishing.'),
    'offline': ('No live data', 'Device offline. Risk is not assessed on old data.'),
    'idle': ('No probes reading', 'The device is online but every probe is disconnected.'),
}


def _empty_assessment(level: str = 'nodata') -> Dict:
    ui = _ui_for_level('normal')
    label, message = EMPTY_STATES.get(level, EMPTY_STATES['nodata'])
    return {
        'overall_level': level,
        'overall_label': label,
        'overall_score': None,
        'message': message,
        'card_class': ui['card_class'],
        'card_bg': ui['card_bg'],
        'dial_class': ui['dial_class'],
        'dial_color': ui['dial_color'],
        'dial_bg': ui['dial_bg'],
        'parameters': [],
        'distribution': {'normal': 0, 'warning': 0, 'high': 0},
        'has_verdict': False,
        'triggered': [],
        'disconnected': [],
        'thresholds': get_thresholds(),
    }
