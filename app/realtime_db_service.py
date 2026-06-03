"""
Firebase Realtime Database Service
Reads live sensor data written by ESP32 devices.
"""

from datetime import datetime
from typing import Dict, List, Optional

from firebase_admin import db

from firebase_config import initialize_firebase

DEVICE_DATA_PATHS = (
    '/device_data',
    '/devices/SH-001',
)


def _normalize_reading(raw: Dict, device_id: str = 'SH-001') -> Dict:
    """Map RTDB field names to the format expected by templates."""
    temperature = raw.get('temperature')
    ph = raw.get('pH', raw.get('ph'))
    turbidity = raw.get('turbidity_NTU', raw.get('turbidity'))
    dissolved_oxygen = raw.get('dissolved_oxygen', raw.get('dissolved_oxygen_mg_L', raw.get('do')))
    salinity = raw.get('salinity', raw.get('salinity_ppt'))
    has_do_sensor = bool(raw.get('has_do_sensor', False))
    has_salinity_sensor = bool(raw.get('has_salinity_sensor', False))

    def _to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    turbidity_voltage = _to_float(raw.get('turbidity_voltage'))
    turbidity_valid = raw.get('turbidity_valid', raw.get('turbidity_submerged'))
    if turbidity_valid is None and turbidity_voltage is not None:
        turbidity_valid = turbidity_voltage >= 0.05
    elif turbidity_valid is None:
        turbidity_valid = True
    else:
        turbidity_valid = bool(turbidity_valid)

    turbidity_val = _to_float(turbidity)
    if not turbidity_valid:
        turbidity_val = 0.0

    return {
        'id': device_id,
        'device_id': device_id,
        'device_name': raw.get('device', device_id),
        'temperature': _to_float(temperature),
        'ph': _to_float(ph),
        'turbidity': turbidity_val,
        'turbidity_valid': turbidity_valid,
        'dissolved_oxygen': _to_float(dissolved_oxygen) if has_do_sensor else None,
        'salinity': _to_float(salinity) if has_salinity_sensor else None,
        'has_do_sensor': has_do_sensor,
        'has_salinity_sensor': has_salinity_sensor,
        'timestamp': raw.get('timestamp'),
        'last_update': _format_last_update(raw.get('timestamp')),
        'source': 'realtime_db',
    }


def _format_last_update(timestamp) -> str:
    if timestamp is None:
        return 'Unknown'
    if isinstance(timestamp, (int, float)) and timestamp < 1_000_000_000:
        return 'Live'
    if isinstance(timestamp, (int, float)):
        try:
            dt = datetime.utcfromtimestamp(timestamp / 1000 if timestamp > 1e12 else timestamp)
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
    return 'Live'


def _sensor_is_active(value, sensor_type: str) -> bool:
    if value is None:
        return False
    if sensor_type == 'temperature':
        return -100 < value < 100
    if sensor_type == 'ph':
        return 0 <= value <= 14
    if sensor_type == 'turbidity':
        return value >= 0
    if sensor_type == 'dissolved_oxygen':
        return 0 <= value <= 20
    if sensor_type == 'salinity':
        return 0 <= value <= 50
    return True


def get_sensor_statuses(reading: Optional[Dict]) -> List[Dict]:
    """Build sensor rows for the devices monitoring table."""
    if not reading:
        return []

    sensors = [
        ('Temperature Sensor', 'temperature', reading.get('temperature'), '°C', True),
        ('pH Sensor', 'ph', reading.get('ph'), '', True),
        ('Turbidity Sensor', 'turbidity', reading.get('turbidity'), ' NTU', True),
    ]

    if reading.get('has_do_sensor'):
        sensors.append(('Dissolved Oxygen Sensor', 'dissolved_oxygen', reading.get('dissolved_oxygen'), ' mg/L', True))

    if reading.get('has_salinity_sensor'):
        sensors.append(('Salinity Sensor', 'salinity', reading.get('salinity'), ' ppt', True))

    rows = []
    for name, key, value, unit, _enabled in sensors:
        if key == 'turbidity' and not reading.get('turbidity_valid', True):
            active = False
            display = '—'
            status_label = 'Offline'
        else:
            active = _sensor_is_active(value, key)
            status_label = 'Active' if active else 'Offline'
            if value is None:
                display = '—'
            elif key == 'temperature':
                display = f'{value:.1f}°C'
            elif key == 'ph':
                display = f'{value:.1f}'
            elif key == 'dissolved_oxygen':
                display = f'{value:.1f} mg/L'
            elif key == 'salinity':
                display = f'{value:.1f} ppt'
            elif key == 'turbidity':
                display = f'{value:.1f} NTU'
            else:
                display = f'{value}{unit}'

        rows.append({
            'name': name,
            'status': status_label,
            'status_class': 'success' if active else 'danger',
            'reading': display,
        })

    return rows


def get_latest_sensor_data() -> Optional[Dict]:
    """Fetch the most recent sensor reading from Realtime Database."""
    initialize_firebase()

    for path in DEVICE_DATA_PATHS:
        try:
            data = db.reference(path).get()
            if data and isinstance(data, dict):
                device_id = path.rsplit('/', 1)[-1]
                if device_id == 'device_data':
                    device_id = 'SH-001'
                return _normalize_reading(data, device_id)
        except Exception:
            continue

    try:
        devices = db.reference('/devices').get()
        if devices and isinstance(devices, dict):
            for device_id, data in devices.items():
                if isinstance(data, dict) and (
                    'temperature' in data or 'pH' in data or 'ph' in data
                ):
                    return _normalize_reading(data, device_id)
    except Exception:
        pass

    return None


def get_sensor_readings(limit: int = 100) -> List[Dict]:
    """Return sensor readings for dashboard/history pages."""
    latest = get_latest_sensor_data()
    if latest:
        return [latest]
    return []


_realtime_db_service = None


def get_realtime_db_service():
    global _realtime_db_service
    if _realtime_db_service is None:
        _realtime_db_service = type('RealtimeDBService', (), {
            'get_latest_sensor_data': staticmethod(get_latest_sensor_data),
            'get_sensor_readings': staticmethod(get_sensor_readings),
            'get_sensor_statuses': staticmethod(get_sensor_statuses),
        })()
    return _realtime_db_service
