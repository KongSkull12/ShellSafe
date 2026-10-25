"""
Firebase Realtime Database Service
Reads live sensor data written by ESP32 T-Call A7670 (shellsafev2.ino).

Link state model (what the UI shows):
  live     - the device published recently; per-probe values are trusted
  checking - first sighting after server start, no proof of freshness yet
  offline  - the device stopped publishing; last values are history, not live
"""

from collections import deque
from datetime import datetime, timezone
import os
import re
import threading
import time
from typing import Deque, Dict, List, Optional, Tuple

from firebase_admin import db

from firebase_config import initialize_firebase

DEVICE_DATA_PATHS = (
    '/device_data',
    '/devices/SH-001',
)

SMS_CONFIG_PATH = '/sms_config'
SMS_TEST_PATH = '/sms_test'
MAX_SMS_PHONES = 4

# Firmware publishes every ~5 s, but a PUT can stall behind modem/SMS work,
# so allow a few missed publishes before calling the device offline.
DEVICE_OFFLINE_TIMEOUT_SECONDS = int(os.environ.get('DEVICE_OFFLINE_TIMEOUT_SECONDS', '30'))

# Short in-memory cache so SSE/poll do not hammer Firebase every tick.
_latest_cache: Dict[str, object] = {'data': None, 'expires': 0.0}
_LATEST_CACHE_TTL = float(os.environ.get('SENSOR_CACHE_TTL_SECONDS', '2.5'))
# Track whether firmware uptime is still advancing; if it stalls, device is offline.
_uptime_tracker: Dict[str, Dict[str, float]] = {}

# Readings seen while the server runs. RTDB only holds the latest snapshot,
# so this is the only history available without a firmware change.
HISTORY_MAX_SAMPLES = int(os.environ.get('SENSOR_HISTORY_SAMPLES', '720'))
_history: Deque[Dict] = deque(maxlen=HISTORY_MAX_SAMPLES)
_history_lock = threading.Lock()
_last_history_key: Dict[str, object] = {'key': None}

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


def _wall_clock_epoch(timestamp) -> Optional[float]:
    dt = _parse_timestamp(timestamp)
    if not dt:
        return None
    return dt.replace(tzinfo=timezone.utc).timestamp()


def _offline_timeout(raw: Dict) -> int:
    """
    On mobile data the firmware publishes every 30 s instead of 5 s, so
    allow a few of its own intervals before calling it offline.
    """
    try:
        interval = float(raw.get('publish_interval_s') or 0)
    except (TypeError, ValueError):
        interval = 0
    return max(DEVICE_OFFLINE_TIMEOUT_SECONDS, int(interval * 2.5))


def _assess_link(device_id: str, raw: Dict, has_sensor_payload: bool) -> Tuple[str, Optional[float]]:
    """
    Decide whether the device is publishing right now.
    Returns (link_state, last_seen_epoch).

    Priority:
      1. server_ts - Firebase server timestamp written with each PUT (exact).
      2. uptime_seconds - advancing uptime proves the device is alive; a frozen
         value means only an old snapshot is left in RTDB.
      3. wall-clock timestamp (GPS UTC) when nothing better exists.
    """
    now = time.time()
    if not has_sensor_payload:
        return 'offline', None
    timeout = _offline_timeout(raw)

    server_ts = raw.get('server_ts')
    if isinstance(server_ts, (int, float)) and server_ts > 1e12:
        seen = server_ts / 1000.0
        age = now - seen
        return ('live' if age <= timeout else 'offline'), seen

    wall_seen = _wall_clock_epoch(_reading_timestamp(raw))

    uptime_value = raw.get('uptime_seconds')
    if uptime_value is None and _is_uptime_timestamp(raw.get('timestamp')):
        uptime_value = raw.get('timestamp')

    if uptime_value is not None:
        try:
            uptime = float(uptime_value)
        except (TypeError, ValueError):
            uptime = None

        if uptime is not None:
            state = _uptime_tracker.get(device_id)
            if not state:
                # First sighting: we cannot know yet whether uptime will advance.
                _uptime_tracker[device_id] = {
                    'last_uptime': uptime,
                    'last_progress_at': None,
                    'first_seen_at': now,
                }
                if wall_seen is not None:
                    fresh = (now - wall_seen) <= timeout
                    return ('live' if fresh else 'offline'), wall_seen
                return 'checking', None

            last_uptime = float(state.get('last_uptime', uptime))
            progressed = uptime > (last_uptime + 0.001)
            rebooted = uptime < (last_uptime - 5.0)
            state['last_uptime'] = uptime
            if progressed or rebooted:
                state['last_progress_at'] = now
                return 'live', now

            last_progress_at = state.get('last_progress_at')
            if last_progress_at is not None:
                if (now - last_progress_at) <= timeout:
                    return 'live', last_progress_at
                return 'offline', last_progress_at

            # Never seen it move. Give it one timeout window, then call it.
            if (now - float(state.get('first_seen_at', now))) <= timeout:
                if wall_seen is not None and (now - wall_seen) > timeout:
                    return 'offline', wall_seen
                return 'checking', wall_seen
            return 'offline', wall_seen

    if wall_seen is not None:
        fresh = (now - wall_seen) <= timeout
        return ('live' if fresh else 'offline'), wall_seen

    # A payload with no clock of any kind: trust it as live.
    return 'live', None


def humanize_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return 'unknown'
    seconds = max(0, int(seconds))
    if seconds < 10:
        return 'just now'
    if seconds < 60:
        return f'{seconds} s ago'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes} min ago'
    hours = minutes // 60
    if hours < 48:
        return f'{hours} hr ago'
    return f'{hours // 24} days ago'


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
    link_state, last_seen_epoch = _assess_link(device_id, raw, has_sensor_payload)
    is_online = link_state == 'live'
    last_seen_age = (time.time() - last_seen_epoch) if last_seen_epoch else None

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
        'sim_ready': raw.get('sim_ready'),
        'gsm_network': raw.get('gsm_network'),
        'gsm_signal': raw.get('gsm_signal'),
        # Raw probe signal (V) and DS18B20 count, for wiring diagnostics.
        'probe_voltage': raw.get('probe_voltage') if isinstance(raw.get('probe_voltage'), dict) else {},
        'ds18b20_count': raw.get('ds18b20_count'),
        # Per-probe calibration flags from firmware; missing means unknown (older firmware).
        'calibrated': raw.get('calibrated') if isinstance(raw.get('calibrated'), dict) else {},
        'uptime_seconds': raw.get('uptime_seconds'),
        # Power and performance (firmware v5+); None on older firmware.
        'battery_pct': _to_float(raw.get('battery_pct')),
        'battery_v': _to_float(raw.get('battery_v')),
        'battery_source': raw.get('battery_source'),
        'transport': raw.get('transport'),
        'cellular_data': raw.get('cellular_data'),
        'wifi_rssi': _to_float(raw.get('wifi_rssi')),
        'free_heap': _to_float(raw.get('free_heap')),
        'min_free_heap': _to_float(raw.get('min_free_heap')),
        'publish_ok': _to_float(raw.get('publish_ok')),
        'publish_fail': _to_float(raw.get('publish_fail')),
        'publish_ms': _to_float(raw.get('publish_ms')),
        'timestamp': reading_timestamp,
        'link_state': link_state,
        'last_seen_epoch': last_seen_epoch,
        'last_update': 'just now' if is_online else humanize_age(last_seen_age),
        'is_online': is_online,
        'is_stale': not is_online,
        'offline_timeout_seconds': _offline_timeout(raw),
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
            'status': 'Offline',
            'status_class': 'secondary',
            'reading': 'Offline',
        } for _key, name, _field, _unit, _flag in SENSOR_SPECS]

    rows = []
    for key, name, field, unit, flag in SENSOR_SPECS:
        value = reading.get(field)
        connected = bool(reading.get(flag, value is not None))
        active = _sensor_is_active(value, key, connected)

        if active:
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


def _record_history(reading: Dict) -> None:
    """Append a live reading once per firmware publish."""
    if not reading or not reading.get('is_online'):
        return
    key = (
        reading.get('uptime_seconds'),
        reading.get('timestamp'),
        reading.get('temperature'), reading.get('ph'), reading.get('turbidity'),
        reading.get('orp'), reading.get('ec'),
    )
    with _history_lock:
        if key == _last_history_key['key']:
            return
        _last_history_key['key'] = key
        sample = {'t': time.time()}
        for spec_key, _name, field, _unit, flag in SENSOR_SPECS:
            sample[spec_key] = reading.get(field) if reading.get(flag) else None
        _history.append(sample)


def get_live_history() -> List[Dict]:
    """Readings captured since the server started, oldest first."""
    with _history_lock:
        return list(_history)


READINGS_PATH = '/readings'
_stored_cache: Dict[str, object] = {'data': None, 'expires': 0.0, 'limit': 0}
_STORED_CACHE_TTL = 30.0


def get_stored_history(limit: int = 720) -> List[Dict]:
    """
    Per-minute readings the firmware logs to /readings (firmware v5+), in
    the same shape as get_live_history(). Survives server restarts and
    works on Vercel, where the in-memory history does not persist.
    """
    now = time.time()
    if _stored_cache['data'] is not None and now < float(_stored_cache['expires']) \
            and int(_stored_cache['limit']) >= limit:
        return list(_stored_cache['data'])[-limit:]  # type: ignore[arg-type]

    initialize_firebase()
    try:
        data = db.reference(READINGS_PATH).order_by_key().limit_to_last(limit).get() or {}
    except Exception:
        return []

    samples = []
    for record in data.values():
        if not isinstance(record, dict) or not isinstance(record.get('t'), (int, float)):
            continue
        sample = {'t': record['t'] / 1000.0}
        for spec_key, *_rest in SENSOR_SPECS:
            sample[spec_key] = _to_float(record.get(spec_key))
        samples.append(sample)
    samples.sort(key=lambda s: s['t'])

    _stored_cache.update({'data': samples, 'expires': now + _STORED_CACHE_TTL, 'limit': limit})
    return samples


def get_history(limit: int = 720) -> List[Dict]:
    """Stored per-minute log when the firmware writes one, else this server's memory."""
    stored = get_stored_history(limit)
    return stored if stored else get_live_history()[-limit:]


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

    _record_history(result)
    _latest_cache['data'] = result
    _latest_cache['expires'] = now + _LATEST_CACHE_TTL
    return result


def get_sensor_readings(limit: int = 100) -> List[Dict]:
    """Return sensor readings for dashboard/history pages."""
    latest = get_latest_sensor_data()
    if latest:
        return [latest]
    return []


_sampler_started = False
_sampler_lock = threading.Lock()


def start_sensor_sampler(interval_seconds: float = 4.0, on_sample=None) -> None:
    """
    Poll RTDB in the background so link state, history and alerts stay
    current even when no browser has the dashboard open.
    """
    global _sampler_started
    with _sampler_lock:
        if _sampler_started:
            return
        _sampler_started = True

    def run():
        while True:
            try:
                reading = get_latest_sensor_data(use_cache=False)
                if on_sample:
                    on_sample(reading)
            except Exception:
                pass
            time.sleep(interval_seconds)

    threading.Thread(target=run, name='shellsafe-sensor-sampler', daemon=True).start()


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
