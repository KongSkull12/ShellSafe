"""
Firebase Realtime Database Service
Reads live sensor data written by ESP32 T-Call A7670 (shellsafev2.ino).
"""

from datetime import datetime, timezone
import os
import re
import time
from typing import Dict, List, Optional, Tuple

from firebase_admin import db

from firebase_config import initialize_firebase

DEVICE_DATA_PATHS = (
    '/device_data',
    '/devices/SH-001',
)

SMS_CONFIG_PATH = '/sms_config'
SMS_TEST_PATH = '/sms_test'
MAX_SMS_PHONES = 4

DEVICE_OFFLINE_TIMEOUT_SECONDS = int(os.environ.get('DEVICE_OFFLINE_TIMEOUT_SECONDS', '20'))
UPTIME_OFFLINE_TIMEOUT_SECONDS = int(os.environ.get('UPTIME_OFFLINE_TIMEOUT_SECONDS', '20'))

# Short in-memory cache so SSE/poll do not hammer Firebase every tick.
_latest_cache: Dict[str, object] = {'data': None, 'expires': 0.0}
_LATEST_CACHE_TTL = float(os.environ.get('SENSOR_CACHE_TTL_SECONDS', '2.5'))
# Track whether firmware uptime is still advancing; if it stalls, device is offline.
_uptime_tracker: Dict[str, Dict[str, float]] = {}

# Uptime timestamps from firmware (millis()/1000) are well below Unix epoch seconds.
UPTIME_TIMESTAMP_MAX = 1_000_000_000

DISCONNECTED_TOKENS = frozenset({
    'disconnected', 'offline', 'n/a', 'na', 'none', 'null', '',
})

SENSOR_SPECS = (
    ('temperature', 'Temperature Sensor', 'temperature', '°C', 'temperature_connected'),
    ('ph', 'pH Sensor', 'ph', '', 'ph_connected'),
    ('turbidity', 'Turbidity Sensor', 'turbidity', ' NTU', 'turbidity_connected'),
    ('orp', 'ORP Sensor', 'orp', ' mV', 'orp_connected'),
    ('ec', 'EC Sensor', 'ec', ' µS/cm', 'ec_connected'),
)


def _is_disconnected_raw(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in DISCONNECTED_TOKENS
    return False


def _parse_sensor_value(value) -> Tuple[Optional[float], bool]:
    """
    Return (numeric_value, connected).
    Firmware sends a number when connected, or the string \"Disconnected\".
    """
    if _is_disconnected_raw(value):
        return None, False
    try:
        return float(value), True
    except (TypeError, ValueError):
        return None, False


def _to_float(value):
    numeric, _connected = _parse_sensor_value(value)
    return numeric


def _is_uptime_timestamp(timestamp) -> bool:
    return isinstance(timestamp, (int, float)) and 0 <= timestamp < UPTIME_TIMESTAMP_MAX


def _parse_timestamp(timestamp) -> Optional[datetime]:
    """Convert wall-clock RTDB timestamps to UTC datetime. Ignores uptime stamps."""
    if timestamp is None:
        return None

    if _is_uptime_timestamp(timestamp):
        return None

    if isinstance(timestamp, (int, float)):
        try:
            return datetime.utcfromtimestamp(timestamp / 1000 if timestamp > 1e12 else timestamp)
        except (OSError, OverflowError, ValueError):
            return None

    if isinstance(timestamp, str):
        normalized = timestamp.strip()
        if not normalized:
            return None
        if normalized.endswith('Z'):
            normalized = normalized[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            return None

    return None


def _is_data_stale(timestamp, has_sensor_payload: bool) -> bool:
    """
    Offline if wall-clock last reading is too old.
    Firmware millis()/1000 uptime cannot be compared to Unix epoch — treat a
    present payload as fresh (device is actively publishing).
    """
    if _is_uptime_timestamp(timestamp):
        return not has_sensor_payload

    dt = _parse_timestamp(timestamp)
    if not dt:
        # No usable wall clock: online if any sensor field is present in payload.
        return not has_sensor_payload

    age_seconds = (datetime.utcnow() - dt).total_seconds()
    return age_seconds > DEVICE_OFFLINE_TIMEOUT_SECONDS


def _is_uptime_stale(device_id: str, uptime_value, has_sensor_payload: bool) -> bool:
    """
    Determine staleness for uptime-based timestamps (millis()/1000).
    If uptime no longer increases for a while, assume the device is offline and
    only old RTDB data remains.
    """
    if not has_sensor_payload:
        return True

    try:
        uptime = float(uptime_value)
    except (TypeError, ValueError):
        return True

    now = time.time()
    state = _uptime_tracker.get(device_id)
    if not state:
        _uptime_tracker[device_id] = {
            'last_uptime': uptime,
            'last_progress_at': now,
        }
        return False

    last_uptime = float(state.get('last_uptime', uptime))
    last_progress_at = float(state.get('last_progress_at', now))

    # Uptime increases while device is publishing, or can reset after reboot.
    progressed = uptime > (last_uptime + 0.001)
    rebooted = uptime < (last_uptime - 5.0)
    if progressed or rebooted:
        state['last_uptime'] = uptime
        state['last_progress_at'] = now
        return False

    state['last_uptime'] = uptime
    return (now - last_progress_at) > UPTIME_OFFLINE_TIMEOUT_SECONDS


def _normalize_reading(raw: Dict, device_id: str = 'SH-001') -> Dict:
    """Map RTDB field names from shellsafev2.ino to template/API format."""
    temperature, temperature_connected = _parse_sensor_value(raw.get('temperature'))
    ph, ph_connected = _parse_sensor_value(raw.get('pH', raw.get('ph')))
    turbidity, turbidity_connected = _parse_sensor_value(
        raw.get('turbidity_NTU', raw.get('turbidity'))
    )
    orp, orp_connected = _parse_sensor_value(raw.get('ORP_mV', raw.get('orp')))
    ec, ec_connected = _parse_sensor_value(raw.get('EC_uS_cm', raw.get('ec')))

    # Payload exists when firmware wrote any of the five sensor keys (even Disconnected).
    sensor_keys_present = any(
        key in raw for key in (
            'temperature', 'pH', 'ph', 'turbidity_NTU', 'turbidity',
            'ORP_mV', 'orp', 'EC_uS_cm', 'ec', 'device',
        )
    )
    has_connected_reading = any([
        temperature_connected, ph_connected, turbidity_connected,
        orp_connected, ec_connected,
    ])
    has_sensor_payload = sensor_keys_present or has_connected_reading

    reading_timestamp = _reading_timestamp(raw)
    uptime_seconds = raw.get('uptime_seconds')
    # uptime_seconds advances on every publish. A frozen value means the
    # device stopped sending, even if the last GPS clock still looks recent.
    if uptime_seconds is not None:
        is_stale = _is_uptime_stale(device_id, uptime_seconds, has_sensor_payload)
    elif _is_uptime_timestamp(reading_timestamp):
        is_stale = _is_uptime_stale(device_id, reading_timestamp, has_sensor_payload)
    else:
        is_stale = _is_data_stale(reading_timestamp, has_sensor_payload)
    is_online = bool(has_sensor_payload and not is_stale)

    # Accept common firmware aliases (lat/lon, nested gps object).
    gps_obj = raw.get('gps') if isinstance(raw.get('gps'), dict) else {}
    latitude = _to_float(
        raw.get('latitude', raw.get('lat', gps_obj.get('latitude')))
    )
    longitude = _to_float(
        raw.get('longitude', raw.get('lon', raw.get('lng', gps_obj.get('longitude'))))
    )
    has_coords = (
        latitude is not None and longitude is not None
        and not (abs(latitude) < 1e-5 and abs(longitude) < 1e-5)
    )
    # Prefer explicit gps_fix, but also treat valid coords as a fix.
    if 'gps_fix' in raw:
        gps_fix = bool(raw.get('gps_fix')) and has_coords
    else:
        gps_fix = has_coords

    maps_url = None
    if gps_fix:
        maps_url = raw.get('maps_url') or (
            f'https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}'
            f'#map=16/{latitude}/{longitude}'
        )

    return {
        'id': device_id,
        'device_id': device_id,
        'device_name': raw.get('device', device_id),
        'temperature': temperature,
        'ph': ph,
        'turbidity': turbidity,
        'orp': orp,
        'ec': ec,
        'temperature_connected': temperature_connected,
        'ph_connected': ph_connected,
        'turbidity_connected': turbidity_connected,
        'orp_connected': orp_connected,
        'ec_connected': ec_connected,
        'gps_enabled': bool(raw.get('gps_enabled', gps_fix)),
        'gps_fix': gps_fix,
        'latitude': latitude if gps_fix else None,
        'longitude': longitude if gps_fix else None,
        'altitude_m': _to_float(raw.get('altitude_m')) if gps_fix else None,
        'speed_kmh': _to_float(raw.get('speed_kmh')) if gps_fix else None,
        'gps_accuracy_m': _to_float(raw.get('gps_accuracy_m')) if gps_fix else None,
        'satellites': int(raw.get('satellites') or 0) if gps_fix else 0,
        'maps_url': maps_url,
        'timestamp': reading_timestamp,
        'last_update': _format_last_update(reading_timestamp, is_online),
        'is_online': is_online,
        'is_stale': is_stale,
        'offline_timeout_seconds': DEVICE_OFFLINE_TIMEOUT_SECONDS,
        'source': 'realtime_db',
    }


def _reading_timestamp(raw: Dict):
    """
    Prefer a wall-clock stamp. Firmware also publishes uptime_seconds
    (millis/1000) under that name or as timestamp.
    """
    for key in ('timestamp', 'gps_time', 'updated_at', 'utc'):
        value = raw.get(key)
        if value not in (None, ''):
            return value
    if raw.get('uptime_seconds') is not None:
        return raw.get('uptime_seconds')
    return None


def _format_last_update(timestamp, is_online: bool = True) -> str:
    # Online payload with no wall clock (or only boot uptime) is a live reading.
    if timestamp is None or _is_uptime_timestamp(timestamp):
        return 'Just now' if is_online else 'Unknown'

    dt = _parse_timestamp(timestamp)
    if not dt:
        return 'Just now' if is_online else 'Unknown'

    try:
        delta = datetime.utcnow() - dt
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return 'Just now'
        if minutes < 60:
            return f'{minutes} min{"s" if minutes != 1 else ""} ago'
        hours = minutes // 60
        return f'{hours} hr{"s" if hours != 1 else ""} ago'
    except (OSError, OverflowError, ValueError):
        return 'Live'


def _sensor_is_active(value, sensor_type: str, connected: bool) -> bool:
    if not connected or value is None:
        return False
    if sensor_type == 'temperature':
        return -100 < value < 100
    if sensor_type == 'ph':
        return 0 <= value <= 14
    if sensor_type == 'turbidity':
        return value >= 0
    if sensor_type == 'orp':
        return -2000 <= value <= 2000
    if sensor_type == 'ec':
        return 0 <= value <= 50000
    return True


def _format_sensor_reading(key: str, value: Optional[float], unit: str) -> str:
    if value is None:
        return 'Disconnected'
    if key == 'temperature':
        return f'{value:.1f}°C'
    if key == 'ph':
        return f'{value:.2f}'
    if key == 'turbidity':
        return f'{value:.1f} NTU'
    if key == 'orp':
        return f'{value:.1f} mV'
    if key == 'ec':
        return f'{value:.1f} µS/cm'
    return f'{value}{unit}'


def get_sensor_statuses(reading: Optional[Dict]) -> List[Dict]:
    """Build sensor rows for the devices monitoring table."""
    if not reading:
        return []

    if not reading.get('is_online', True):
        return [{
            'name': name,
            'status': 'Disconnected',
            'status_class': 'secondary',
            'reading': 'Disconnected',
        } for _key, name, _field, _unit, _flag in SENSOR_SPECS]

    rows = []
    for key, name, field, unit, flag in SENSOR_SPECS:
        value = reading.get(field)
        connected = bool(reading.get(flag, value is not None))
        active = _sensor_is_active(value, key, connected)

        if not connected:
            status_label = 'Disconnected'
            status_class = 'secondary'
            display = 'Disconnected'
        elif active:
            status_label = 'Active'
            status_class = 'success'
            display = _format_sensor_reading(key, value, unit)
        else:
            status_label = 'Disconnected'
            status_class = 'secondary'
            display = 'Disconnected'

        rows.append({
            'name': name,
            'status': status_label,
            'status_class': status_class,
            'reading': display,
        })

    return rows


def get_latest_sensor_data(use_cache: bool = True) -> Optional[Dict]:
    """Fetch the most recent sensor reading from Realtime Database."""
    now = time.time()
    if use_cache and _latest_cache['data'] is not None and now < float(_latest_cache['expires']):
        return _latest_cache['data']  # type: ignore[return-value]

    initialize_firebase()
    result = None

    for path in DEVICE_DATA_PATHS:
        try:
            data = db.reference(path).get()
            if data and isinstance(data, dict):
                device_id = path.rsplit('/', 1)[-1]
                if device_id == 'device_data':
                    device_id = 'SH-001'
                result = _normalize_reading(data, device_id)
                break
        except Exception:
            continue

    if result is None:
        try:
            devices = db.reference('/devices').get()
            if devices and isinstance(devices, dict):
                for device_id, data in devices.items():
                    if isinstance(data, dict) and (
                        'temperature' in data
                        or 'pH' in data
                        or 'ph' in data
                        or 'ORP_mV' in data
                        or 'EC_uS_cm' in data
                    ):
                        result = _normalize_reading(data, device_id)
                        break
        except Exception:
            pass

    _latest_cache['data'] = result
    _latest_cache['expires'] = now + _LATEST_CACHE_TTL
    return result


def get_sensor_readings(limit: int = 100) -> List[Dict]:
    """Return sensor readings for dashboard/history pages."""
    latest = get_latest_sensor_data()
    if latest:
        return [latest]
    return []


def _normalize_phone(phone: str) -> Optional[str]:
    if not phone:
        return None
    cleaned = re.sub(r'[\s\-()]', '', str(phone).strip())
    if not cleaned:
        return None
    if cleaned.startswith('00'):
        cleaned = '+' + cleaned[2:]
    if not cleaned.startswith('+'):
        # Philippine local 09xxxxxxxxx → +639xxxxxxxxx
        if cleaned.startswith('0') and len(cleaned) >= 10:
            cleaned = '+63' + cleaned[1:]
        else:
            cleaned = '+' + cleaned
    if not re.fullmatch(r'\+[1-9]\d{7,14}', cleaned):
        return None
    return cleaned


def get_sms_phones() -> List[str]:
    """Load SMS recipient list from RTDB /sms_config (max 4)."""
    initialize_firebase()
    try:
        data = db.reference(SMS_CONFIG_PATH).get()
    except Exception:
        return []

    if not data:
        return []

    phones = data.get('phones') if isinstance(data, dict) else data
    if not isinstance(phones, list):
        return []

    result = []
    for phone in phones:
        normalized = _normalize_phone(phone)
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= MAX_SMS_PHONES:
            break
    return result


def set_sms_phones(phones: List[str]) -> List[str]:
    """Persist up to 4 normalized phone numbers to RTDB /sms_config."""
    initialize_firebase()
    cleaned = []
    for phone in phones:
        normalized = _normalize_phone(phone)
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
        if len(cleaned) >= MAX_SMS_PHONES:
            break

    payload = {
        'phones': cleaned,
        'updated_at': datetime.utcnow().isoformat() + 'Z',
        'max_phones': MAX_SMS_PHONES,
    }
    db.reference(SMS_CONFIG_PATH).set(payload)
    return cleaned


def get_sms_test_status() -> Dict:
    """Read pending/completed SMS test status from RTDB /sms_test."""
    initialize_firebase()
    try:
        data = db.reference(SMS_TEST_PATH).get()
    except Exception:
        data = None

    if not isinstance(data, dict):
        return {
            'requested': False,
            'status': 'idle',
            'detail': '',
            'requested_at': None,
            'completed_at': None,
            'recipient_count': 0,
        }

    status = str(data.get('status') or 'idle').lower()
    if status not in ('idle', 'pending', 'sent', 'failed'):
        status = 'idle'

    return {
        'requested': bool(data.get('requested')),
        'status': status,
        'detail': str(data.get('detail') or ''),
        'requested_at': data.get('requested_at'),
        'completed_at': data.get('completed_at'),
        'recipient_count': int(data.get('recipient_count') or 0),
    }


def request_sms_test(requested_by: str = 'admin') -> Dict:
    """
    Queue a manual SMS test for the T-Call modem.
    Firmware polls /sms_test and sends to phones in /sms_config.
    """
    phones = get_sms_phones()
    if not phones:
        raise ValueError('Save at least one valid phone number before sending a test SMS.')

    initialize_firebase()
    now = datetime.utcnow().isoformat() + 'Z'
    payload = {
        'requested': True,
        'status': 'pending',
        'detail': 'Waiting for T-Call A7670 to send test SMS…',
        'requested_at': now,
        'requested_by': requested_by or 'admin',
        'completed_at': None,
        'recipient_count': len(phones),
    }
    db.reference(SMS_TEST_PATH).set(payload)
    return payload


_realtime_db_service = None


def get_realtime_db_service():
    global _realtime_db_service
    if _realtime_db_service is None:
        _realtime_db_service = type('RealtimeDBService', (), {
            'get_latest_sensor_data': staticmethod(get_latest_sensor_data),
            'get_sensor_readings': staticmethod(get_sensor_readings),
            'get_sensor_statuses': staticmethod(get_sensor_statuses),
            'get_sms_phones': staticmethod(get_sms_phones),
            'set_sms_phones': staticmethod(set_sms_phones),
            'get_sms_test_status': staticmethod(get_sms_test_status),
            'request_sms_test': staticmethod(request_sms_test),
        })()
    return _realtime_db_service
