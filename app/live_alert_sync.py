"""
Create in-app Firestore alerts from live sensor risk state.
Only high-risk parameter alerts — not disconnection spam (shown on Devices).
"""

import time
from typing import Dict, Optional

from app.firestore_service import get_firestore_service

_ALERT_COOLDOWN_SECONDS = 600
_BATTERY_COOLDOWN_SECONDS = 6 * 3600
BATTERY_LOW_PCT = 20
_last_sent: Dict[str, float] = {}
_last_sync_attempt = 0.0
_MIN_SYNC_GAP = 15.0  # never hit Firestore more often than this


def _should_send(key: str, cooldown: float = _ALERT_COOLDOWN_SECONDS) -> bool:
    now = time.time()
    last = _last_sent.get(key, 0)
    if now - last < cooldown:
        return False
    _last_sent[key] = now
    return True


def sync_device_alerts(sensor_data: Optional[Dict]) -> None:
    """Raise a Battery alert when the node runs low (at most every 6 h)."""
    if not sensor_data or not sensor_data.get('is_online'):
        return
    pct = sensor_data.get('battery_pct')
    if pct is None or pct >= BATTERY_LOW_PCT:
        return
    if not _should_send('battery_low', _BATTERY_COOLDOWN_SECONDS):
        return
    try:
        volts = sensor_data.get('battery_v')
        get_firestore_service().create_alert(
            'BATTERY',
            'Warning',
            f"Battery low: {pct:.0f}%" + (f" ({volts:.2f} V)" if volts else '')
            + '. Recharge or replace the battery to keep the node online.',
        )
    except Exception:
        # Allow a retry on the next sample if Firestore was unreachable.
        _last_sent.pop('battery_low', None)


def sync_live_alerts(sensor_data: Optional[Dict], risk_assessment: Optional[Dict]) -> None:
    global _last_sync_attempt

    if not sensor_data or not risk_assessment:
        return

    now = time.time()
    if now - _last_sync_attempt < _MIN_SYNC_GAP:
        return
    _last_sync_attempt = now

    # Only create alerts for high-risk connected sensors.
    high = [
        p for p in (risk_assessment.get('triggered') or [])
        if p.get('level') == 'high'
    ]
    if not high:
        return

    try:
        db = get_firestore_service()
    except Exception:
        return

    try:
        for param in high:
            key = f"risk_{param.get('key')}"
            if not _should_send(key):
                continue
            display = param.get('display') or param.get('value')
            db.create_alert(
                'RISK',
                'Critical',
                f"{param.get('name')} alert: {display}. Exceeded configured alert threshold.",
            )
    except Exception:
        return
