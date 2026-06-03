"""
Bloom risk assessment based on live sensor readings.
"""

from typing import Dict, List, Optional


# Thresholds: (normal_min, normal_max, warning_low, warning_high, high triggers)
SENSOR_THRESHOLDS = {
    'temperature': {
        'label': 'Temperature',
        'unit': '°C',
        'normal': (20.0, 30.0),
        'warning': (15.0, 32.0),
        'high_below': 15.0,
        'high_above': 32.0,
    },
    'ph': {
        'label': 'pH',
        'unit': '',
        'normal': (6.5, 8.5),
        'warning': (6.0, 9.0),
        'high_below': 6.0,
        'high_above': 9.0,
    },
    'turbidity': {
        'label': 'Turbidity',
        'unit': ' NTU',
        'normal': (0.0, 50.0),
        'warning': (50.0, 100.0),
        'high_above': 100.0,
    },
    'dissolved_oxygen': {
        'label': 'Dissolved Oxygen',
        'unit': ' mg/L',
        'normal': (5.0, 14.0),
        'warning': (3.0, 5.0),
        'high_below': 3.0,
    },
    'salinity': {
        'label': 'Salinity',
        'unit': ' ppt',
        'normal': (28.0, 36.0),
        'warning': (25.0, 38.0),
        'high_below': 25.0,
        'high_above': 38.0,
    },
}

LEVEL_SCORES = {
    'normal': 0,
    'warning': 1,
    'high': 2,
    'unknown': 0,
}

LEVEL_LABELS = {
    'normal': 'Normal',
    'warning': 'Warning',
    'high': 'High Risk',
    'unknown': 'Unknown',
}

OVERALL_MESSAGES = {
    'normal': 'All monitored parameters are within safe coastal water thresholds.',
    'warning': 'One or more parameters are outside normal range. Monitor closely.',
    'high': 'Critical conditions detected. Possible algal bloom formation.',
}


def _assess_parameter(key: str, value: Optional[float]) -> Dict:
    if value is None:
        return {
            'key': key,
            'name': SENSOR_THRESHOLDS.get(key, {}).get('label', key),
            'value': None,
            'level': 'unknown',
            'label': 'No Data',
        }

    thresholds = SENSOR_THRESHOLDS.get(key)
    if not thresholds:
        return {
            'key': key,
            'name': key,
            'value': value,
            'level': 'unknown',
            'label': 'Unknown',
        }

    normal_min, normal_max = thresholds['normal']
    level = 'normal'

    high_below = thresholds.get('high_below')
    high_above = thresholds.get('high_above')

    if high_below is not None and value < high_below:
        level = 'high'
    elif high_above is not None and value > high_above:
        level = 'high'
    elif value < normal_min or value > normal_max:
        warn_min, warn_max = thresholds['warning']
        if value < warn_min or value > warn_max:
            level = 'high'
        else:
            level = 'warning'
    else:
        level = 'normal'

    unit = thresholds.get('unit', '')
    if key == 'temperature':
        display = f'{value:.1f}{unit}'
    elif key == 'ph':
        display = f'{value:.1f}'
    elif key == 'turbidity':
        display = f'{value:.1f}{unit.strip()}'
    else:
        display = f'{value:.1f}{unit}'

    return {
        'key': key,
        'name': thresholds['label'],
        'value': value,
        'display': display,
        'level': level,
        'label': LEVEL_LABELS[level],
    }


def assess_bloom_risk(sensor_data: Optional[Dict]) -> Dict:
    """Compute overall and per-parameter bloom risk from sensor readings."""
    if not sensor_data:
        return _empty_assessment()

    parameters_to_check = [
        ('temperature', sensor_data.get('temperature')),
        ('ph', sensor_data.get('ph')),
        ('turbidity', sensor_data.get('turbidity')),
    ]

    if sensor_data.get('has_do_sensor') and sensor_data.get('dissolved_oxygen') is not None:
        parameters_to_check.append(('dissolved_oxygen', sensor_data.get('dissolved_oxygen')))

    if sensor_data.get('has_salinity_sensor') and sensor_data.get('salinity') is not None:
        parameters_to_check.append(('salinity', sensor_data.get('salinity')))

    parameters = [_assess_parameter(key, value) for key, value in parameters_to_check]
    active_parameters = [p for p in parameters if p['level'] != 'unknown']

    if not active_parameters:
        return _empty_assessment()

    distribution = {'normal': 0, 'warning': 0, 'high': 0}
    max_score = 0
    overall_level = 'normal'

    for param in active_parameters:
        distribution[param['level']] = distribution.get(param['level'], 0) + 1
        score = LEVEL_SCORES[param['level']]
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
        'triggered': [p for p in active_parameters if p['level'] != 'normal'],
    }


def _ui_for_level(level: str) -> Dict:
    mapping = {
        'normal': {
            'label': 'Normal',
            'card_class': 'text-white',
            'card_bg': 'bg-success',
            'dial_class': 'risk-dial-normal',
            'dial_color': '#23C268',
            'dial_bg': 'rgba(35, 194, 104, 0.12)',
        },
        'warning': {
            'label': 'Warning',
            'card_class': 'text-dark',
            'card_bg': 'bg-warning',
            'dial_class': 'risk-dial-warning',
            'dial_color': '#F39C12',
            'dial_bg': 'rgba(243, 156, 18, 0.12)',
        },
        'high': {
            'label': 'High Risk',
            'card_class': 'text-white',
            'card_bg': 'bg-danger',
            'dial_class': 'risk-dial-high',
            'dial_color': '#E74C3C',
            'dial_bg': 'rgba(231, 76, 60, 0.12)',
        },
    }
    return mapping.get(level, mapping['normal'])


def _empty_assessment() -> Dict:
    ui = _ui_for_level('normal')
    return {
        'overall_level': 'normal',
        'overall_label': 'Normal',
        'overall_score': 0,
        'message': 'Waiting for live sensor data.',
        'card_class': ui['card_class'],
        'card_bg': ui['card_bg'],
        'dial_class': ui['dial_class'],
        'dial_color': ui['dial_color'],
        'dial_bg': ui['dial_bg'],
        'parameters': [],
        'distribution': {'normal': 0, 'warning': 0, 'high': 0},
        'triggered': [],
    }
