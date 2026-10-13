"""
Create in-app Firestore alerts from live sensor risk state.
Only high-risk parameter alerts — not disconnection spam (shown on Devices).
"""

import time
from typing import Dict, Optional

from app.firestore_service import get_firestore_service

_ALERT_COOLDOWN_SECONDS = 600
_last_sent: Dict[str, float] = {}
_last_sync_attempt = 0.0
_MIN_SYNC_GAP = 15.0  # never hit Firestore more often than this


def _should_send(key: str) -> bool:
    now = time.time()
    last = _last_sent.get(key, 0)
    if now - last < _ALERT_COOLDOWN_SECONDS:
        return False
    _last_sent[key] = now
    return True


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
