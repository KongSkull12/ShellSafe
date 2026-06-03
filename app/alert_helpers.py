"""Normalize Firestore alert documents for templates and UI logic."""

from datetime import datetime
from typing import Any, Dict, List

ALERT_TITLES = {
    'RISK': 'Bloom Risk Alert',
    'BATTERY': 'Battery Alert',
    'DEVICE_OFFLINE': 'Device Offline',
    'DISCONNECTION': 'Device Disconnection',
}

RISK_ALERT_TYPES = frozenset({'RISK'})


def _to_datetime(value: Any) -> datetime:
    if value is None:
        return datetime.utcnow()
    if isinstance(value, datetime):
        return value
    if hasattr(value, 'timestamp'):
        return datetime.utcfromtimestamp(value.timestamp())
    return datetime.utcnow()


def _alert_title(alert_type: str, risk_level: str) -> str:
    base = ALERT_TITLES.get(alert_type, alert_type.replace('_', ' ').title())
    if alert_type == 'RISK' and risk_level:
        return f'{base} — {risk_level}'
    return base


def normalize_alert(raw: Dict) -> Dict:
    """Map Firestore alert fields to template-friendly keys."""
    alert_id = raw.get('id') or raw.get('alert_id')
    alert_type = raw.get('alert_type', 'UNKNOWN')
    risk_level = raw.get('risk_level', 'Warning')
    is_acknowledged = bool(raw.get('is_acknowledged', False))
    created_at = _to_datetime(raw.get('alert_timestamp') or raw.get('created_at'))
    deleted_at = raw.get('deleted_at')
    if deleted_at is not None:
        deleted_at = _to_datetime(deleted_at)

    return {
        'id': alert_id,
        'alert_id': alert_id,
        'alert_type': alert_type,
        'alert_level': risk_level,
        'risk_level': risk_level,
        'alert_message': raw.get('alert_message', ''),
        'alert_title': raw.get('alert_title') or _alert_title(alert_type, risk_level),
        'status': 'Read' if is_acknowledged else 'Unread',
        'is_acknowledged': is_acknowledged,
        'is_deleted': bool(raw.get('is_deleted', False)),
        'is_system': alert_type not in RISK_ALERT_TYPES,
        'created_at': created_at,
        'deleted_at': deleted_at,
    }


def normalize_alerts(alerts: List[Dict]) -> List[Dict]:
    return [normalize_alert(a) for a in alerts]


def count_unread(alerts: List[Dict]) -> int:
    return sum(1 for a in alerts if not a.get('is_acknowledged', False))
