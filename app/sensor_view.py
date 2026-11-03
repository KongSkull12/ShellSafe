"""
One view model for live sensor state, shared by page renders, the poll API
and the SSE stream so the server and the browser never disagree.

Per-probe state:
  live      - device online, probe connected, value trusted
  unplugged - device online, firmware reports the probe as Disconnected
  offline   - device not publishing; value (if any) is the last known one
  checking  - first sighting after server start
  nodata    - nothing in Firebase at all
"""

from typing import Dict, List, Optional

from app.ml_service import predict_bloom
from app.realtime_db_service import get_latest_sensor_data, get_sensor_statuses
from app.risk_service import assess_bloom_risk

SENSORS = (
    # key, label, unit, decimals, connection flag
    ('temperature', 'Temperature', '°C', 1, 'temperature_connected'),
    ('ph', 'pH', '', 2, 'ph_connected'),
    ('turbidity', 'Turbidity', 'NTU', 1, 'turbidity_connected'),
    ('orp', 'ORP', 'mV', 1, 'orp_connected'),
    ('ec', 'EC', 'µS/cm', 1, 'ec_connected'),
)

STATE_LABELS = {
    'live': 'Live',
    'dry': 'Dry',
    'unplugged': 'Probe unplugged',
    'out_of_water': 'Dry',
    'offline': 'Device offline',
    'checking': 'Connecting',
    'nodata': 'No data',
    'unavailable': 'Unavailable',
}

_DRY_FLAGS = {
    'ph': 'ph_dry',
    'turbidity': 'turbidity_dry',
    'orp': 'orp_dry',
    'ec': 'ec_dry',
}

# Shown with the probe strip, but not counted as a probe.
CALCULATED = (
    ('salinity', 'Salinity', 'ppt', 2, 'Calculated from EC and temperature'),
)


def _format(value: Optional[float], decimals: int) -> Optional[str]:
    if value is None:
        return None
    return f'{value:,.{decimals}f}'


def build_sensor_cards(reading: Optional[Dict], risk: Dict) -> List[Dict]:
    levels = {p['key']: p for p in (risk.get('parameters') or [])}
    link_state = (reading or {}).get('link_state', 'nodata') if reading else 'nodata'

    cards = []
    for key, label, unit, decimals, flag in SENSORS:
        value = reading.get(key) if reading else None
        connected = bool(reading.get(flag)) if reading else False

        dry_flag = _DRY_FLAGS.get(key)
        is_dry = bool(
            dry_flag and (reading or {}).get(dry_flag)
            or (key == 'turbidity' and (reading or {}).get('turbidity_out_of_water'))
        )
        if link_state == 'live':
            state = 'live' if connected and value is not None else 'unplugged'
            # Same as EC: dry probes stay connected and show 0.
            if is_dry and connected:
                state = 'dry'
                value = 0.0
        else:
            state = link_state

        level = None
        level_label = None
        if state == 'live' and key in levels:
            level = levels[key].get('level')
            level_label = levels[key].get('label')
            if level == 'uncalibrated':
                level = None
        elif state == 'dry':
            level_label = 'Dry'

        show_value = state in ('live', 'dry')
        display = _format(value, decimals) if show_value else None
        display_unit = unit
        calibrated = (reading or {}).get('calibrated') or {}
        volts = ((reading or {}).get('probe_voltage') or {}).get(key)
        uncalibrated = state == 'live' and calibrated.get(key) is False
        if uncalibrated and volts is not None:
            display = f'{float(volts):.3f}'
            display_unit = 'V'

        cards.append({
            'key': key,
            'label': label,
            'unit': unit,
            'display_unit': display_unit,
            'uncalibrated': uncalibrated,
            'state': state,
            'state_label': STATE_LABELS[state],
            'value': value if show_value and not uncalibrated else None,
            'display': display,
            # Last known value is shown muted on offline cards, never as live.
            'last_display': _format(value, decimals) if state == 'offline' and connected else None,
            'level': level,
            'level_label': level_label,
        })
    return cards


def _extension_card(key, label, unit, decimals, state, value, note, signal, level='', level_label=None) -> Dict:
    display = _format(value, decimals) if state == 'live' else None
    return {
        'key': key,
        'label': label,
        'unit': unit,
        'display_unit': unit,
        'uncalibrated': False,
        'state': state,
        'state_label': level_label or STATE_LABELS[state],
        'value': value if state == 'live' else None,
        'display': display,
        'last_display': None,
        'level': level,
        'level_label': level_label,
        'note': note,
        'signal': signal,
        'installed': state == 'live',
    }


def build_calculated(reading: Optional[Dict]) -> List[Dict]:
    link_state = (reading or {}).get('link_state', 'nodata') if reading else 'nodata'
    value = reading.get('salinity') if reading else None
    if link_state != 'live':
        state, level_label, note = link_state, None, CALCULATED[0][4]
    elif value is not None:
        state, level_label, note = 'live', 'Calculated', CALCULATED[0][4]
    else:
        state, level_label, note = 'unavailable', None, 'Needs calibrated EC and temperature.'
    key, label, unit, decimals, _default_note = CALCULATED[0]
    return [_extension_card(key, label, unit, decimals, state, value, note, 'From EC', 'derived' if state == 'live' else '', level_label)]


def build_live_payload(reading: Optional[Dict] = None, fetch: bool = True) -> Dict:
    if reading is None and fetch:
        reading = get_latest_sensor_data()
    risk = assess_bloom_risk(reading)
    link_state = reading.get('link_state', 'live') if reading else 'nodata'
    sensors = build_sensor_cards(reading, risk)
    calculated = build_calculated(reading)
    return {
        'sensor_data': reading,
        'sensor_statuses': get_sensor_statuses(reading),
        'risk_assessment': risk,
        'ml_prediction': predict_bloom(reading),
        'is_online': link_state == 'live',
        'link': {
            'state': link_state,
            'label': STATE_LABELS.get(link_state, 'Offline'),
            'device_id': reading.get('device_id') if reading else None,
            'device_name': reading.get('device_name') if reading else None,
            'last_seen_epoch': reading.get('last_seen_epoch') if reading else None,
            'last_update': reading.get('last_update') if reading else None,
            'timeout_seconds': reading.get('offline_timeout_seconds') if reading else None,
            'live_count': sum(1 for s in sensors if s['state'] == 'live'),
            'probe_total': len(SENSORS),
        },
        'sensors': sensors,
        'calculated': calculated,
    }


def payload_fingerprint(payload: Dict) -> tuple:
    """Changes whenever anything visible on a live page would change."""
    reading = payload.get('sensor_data') or {}
    return (
        payload['link']['state'],
        tuple((s['state'], s['value'], s['level']) for s in payload['sensors']),
        tuple((s['state'], s['value']) for s in payload.get('calculated') or []),
        payload['risk_assessment'].get('overall_level'),
        payload['ml_prediction'].get('message'),
        reading.get('battery_pct'),
        reading.get('transport'),
        bool(reading.get('gps_fix')),
        reading.get('latitude'),
        reading.get('longitude'),
        reading.get('satellites'),
    )
