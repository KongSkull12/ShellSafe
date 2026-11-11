"""
Firestore Database Service Layer
Provides abstraction for Firestore operations.
"""

from firebase_config import get_firestore_client
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging
import time
from google.api_core.exceptions import NotFound
from google.cloud.firestore import Query

_log = logging.getLogger(__name__)

# Spark plan allows 50K Firestore reads a day, and streaming `alerts` costs
# one read per document. The badge is painted on every logged-in page, so it
# uses a count query (1 read per 1000 matches) and is cached.
_UNREAD_CACHE_TTL = 120.0
_unread_cache: Dict[str, Any] = {'count': 0, 'expires': 0.0}

# Full alerts list, shared by the Alerts, Risk, Recently deleted and Reports
# pages. Writes made by this process clear it straight away.
_ALERTS_CACHE_TTL = 60.0
_alerts_cache: Dict[str, Any] = {'docs': None, 'expires': 0.0}


def _invalidate_alert_caches() -> None:
    _alerts_cache['expires'] = 0.0
    _unread_cache['expires'] = 0.0


def _timestamp_sort_key(value: Any) -> float:
    """Normalize mixed Firestore / datetime / string timestamps for sorting."""
    if value is None:
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    if hasattr(value, 'timestamp') and callable(value.timestamp):
        try:
            return float(value.timestamp())
        except Exception:
            pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Firestore sometimes stores epoch ms.
        return float(value) / 1000.0 if value > 1e12 else float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except Exception:
            return 0.0
    return 0.0


class FirestoreService:
    """Service class for Firestore database operations"""
    
    def __init__(self):
        self.db = get_firestore_client()
    
    # ==================== USER OPERATIONS ====================
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """
        Retrieve a user by email address.
        
        Args:
            email: User email address
            
        Returns:
            User document data or None if not found
        """
        users = self.db.collection('users').where('email_id', '==', email).stream()
        for user in users:
            return {'id': user.id, **user.to_dict()}
        return None
    
    def create_user(self, email: str, password_hash: str, role: str) -> str:
        """
        Create a new user in Firestore.
        
        Args:
            email: User email
            password_hash: Hashed password
            role: User role (admin or authority)
            
        Returns:
            User document ID
        """
        user_data = {
            'email_id': email,
            'password': password_hash,
            'role': role,
            'created_at': datetime.utcnow()
        }
        doc_ref = self.db.collection('users').add(user_data)
        return doc_ref[1].id
    
    def user_exists(self, email: str) -> bool:
        """Check if user exists by email."""
        return self.get_user_by_email(email) is not None
    
    # ==================== ALERT OPERATIONS ====================
    
    def get_all_alerts(self, exclude_deleted: bool = True, limit: Optional[int] = None) -> List[Dict]:
        """
        Retrieve alerts (newest first).

        Args:
            exclude_deleted: If True, exclude deleted alerts
            limit: Optional max number of alerts to return after filtering

        Returns:
            List of alert documents
        """
        if limit is not None and not self._alerts_cache_fresh():
            return self._latest_alerts(max(0, int(limit)), exclude_deleted)

        docs = self._alert_docs()
        if docs is None:
            return []
        alerts = [a for a in docs if not (exclude_deleted and a.get('is_deleted', False))]
        alerts.sort(key=lambda x: _timestamp_sort_key(x.get('alert_timestamp')), reverse=True)
        if limit is not None:
            return alerts[: max(0, int(limit))]
        return alerts

    @staticmethod
    def _alerts_cache_fresh() -> bool:
        return _alerts_cache['docs'] is not None and time.time() < float(_alerts_cache['expires'])

    def _alert_docs(self) -> Optional[List[Dict]]:
        """Every alert document, read at most once per _ALERTS_CACHE_TTL."""
        if self._alerts_cache_fresh():
            return [dict(a) for a in _alerts_cache['docs']]
        try:
            docs = [{'id': d.id, **(d.to_dict() or {})} for d in self.db.collection('alerts').stream()]
        except Exception as exc:
            _log.warning('Reading alerts failed: %s', exc)
            stale = _alerts_cache['docs']
            return [dict(a) for a in stale] if stale is not None else None
        _alerts_cache['docs'] = docs
        _alerts_cache['expires'] = time.time() + _ALERTS_CACHE_TTL
        return [dict(a) for a in docs]

    def _latest_alerts(self, limit: int, exclude_deleted: bool) -> List[Dict]:
        """Newest alerts via an ordered, limited query (reads ~limit docs, not all)."""
        if limit == 0:
            return []
        try:
            # Over-fetch a little so soft-deleted alerts can be skipped.
            docs = (self.db.collection('alerts')
                    .order_by('alert_timestamp', direction=Query.DESCENDING)
                    .limit(limit + 10).stream())
            alerts = [{'id': d.id, **(d.to_dict() or {})} for d in docs]
        except Exception as exc:
            _log.warning('Reading latest alerts failed: %s', exc)
            return []
        if exclude_deleted:
            alerts = [a for a in alerts if not a.get('is_deleted', False)]
        alerts.sort(key=lambda x: _timestamp_sort_key(x.get('alert_timestamp')), reverse=True)
        return alerts[:limit]

    def get_risk_alerts(self) -> List[Dict]:
        """Get all RISK type alerts that are not deleted."""
        return [a for a in self.get_all_alerts(exclude_deleted=True) if a.get('alert_type') == 'RISK']

    def get_unread_alert_count(self) -> int:
        """Count non-deleted alerts that have not been acknowledged."""
        now = time.time()
        if now < float(_unread_cache['expires']):
            return int(_unread_cache['count'])
        try:
            if self._alerts_cache_fresh():
                count = sum(1 for a in self.get_all_alerts(exclude_deleted=True)
                            if not a.get('is_acknowledged', False))
            else:
                # Every alert is created with both flags, so equality filters
                # match all of them. Needs no composite index.
                query = (self.db.collection('alerts')
                         .where('is_acknowledged', '==', False)
                         .where('is_deleted', '==', False))
                result = query.count().get()
                count = int(result[0][0].value)
        except Exception as exc:
            _log.warning('get_unread_alert_count failed: %s', exc)
            count = int(_unread_cache.get('count') or 0)
        _unread_cache['count'] = count
        _unread_cache['expires'] = now + _UNREAD_CACHE_TTL
        return count

    def mark_all_alerts_read(self) -> int:
        """Acknowledge all unread alerts. Returns number updated."""
        updated = 0
        for alert in self.get_all_alerts(exclude_deleted=True):
            if not alert.get('is_acknowledged', False):
                self.update_alert(alert['id'], {'is_acknowledged': True})
                updated += 1
        _invalidate_alert_caches()
        return updated

    def clear_acknowledged_alerts(self) -> int:
        """Soft-delete all acknowledged alerts. Returns number cleared."""
        cleared = 0
        for alert in self.get_all_alerts(exclude_deleted=True):
            if alert.get('is_acknowledged', False):
                self.delete_alert(alert['id'], permanent=False)
                cleared += 1
        return cleared
    
    def create_alert(self, alert_type: str, risk_level: str, message: str) -> str:
        """
        Create a new alert.
        
        Args:
            alert_type: Type of alert (e.g., 'RISK', 'BATTERY', 'DEVICE_OFFLINE')
            risk_level: Risk level (e.g., 'Critical', 'Warning', 'Moderate')
            message: Alert message
            
        Returns:
            Alert document ID
        """
        alert_data = {
            'alert_type': alert_type,
            'risk_level': risk_level,
            'alert_message': message,
            'is_acknowledged': False,
            'is_deleted': False,
            'alert_timestamp': datetime.utcnow()
        }
        _, doc_ref = self.db.collection('alerts').add(alert_data)
        _invalidate_alert_caches()
        return doc_ref.id
    
    def update_alert(self, alert_id: str, updates: Dict) -> None:
        """Update an alert document."""
        self.db.collection('alerts').document(alert_id).update(updates)
        _invalidate_alert_caches()
    
    def delete_alert(self, alert_id: str, permanent: bool = False) -> None:
        """
        Delete an alert (soft delete by default).
        
        Args:
            alert_id: Alert document ID
            permanent: If True, permanently delete; otherwise soft delete to deleted_alerts
        """
        ref = self.db.collection('alerts').document(alert_id)
        if permanent:
            ref.delete()
        else:
            try:
                ref.update({'is_deleted': True, 'deleted_at': datetime.utcnow()})
            except NotFound:
                return
        _invalidate_alert_caches()
    
    def get_deleted_alerts(self) -> List[Dict]:
        """Get all soft-deleted alerts."""
        alerts = [a for a in (self._alert_docs() or []) if a.get('is_deleted', False)]
        alerts.sort(key=lambda x: _timestamp_sort_key(x.get('deleted_at')), reverse=True)
        return alerts
    
    def restore_alert(self, alert_id: str) -> None:
        """Restore a soft-deleted alert."""
        self.db.collection('alerts').document(alert_id).update({
            'is_deleted': False,
            'deleted_at': None
        })
        _invalidate_alert_caches()
    
    # ==================== REPORT OPERATIONS ====================
    
    def get_all_reports(self, status: str = 'active') -> List[Dict]:
        """
        Retrieve reports by status.
        
        Args:
            status: Report status ('active' or 'deleted')
            
        Returns:
            List of report documents
        """
        docs = self.db.collection('reports').where(
            'status', '==', status
        ).stream()
        
        reports = []
        for doc in docs:
            reports.append({'id': doc.id, **doc.to_dict()})
        
        # Sort by generated_date in memory
        reports.sort(key=lambda x: x.get('generated_date', datetime.utcnow()), reverse=True)
        return reports
    
    def create_report(self, report_name: str, report_type: str, file_path: str = None, 
                      file_size: str = '2.4 MB', generated_by: str = 'System Auto',
                      summary: Optional[Dict] = None) -> str:
        """
        Create a new report.
        
        Args:
            report_name: Report name
            report_type: Report type (e.g., 'monthly', 'weekly')
            file_path: Path to report file
            file_size: Size of report file
            generated_by: User who generated the report
            
        Returns:
            Report document ID
        """
        report_data = {
            'report_name': report_name,
            'report_type': report_type,
            'generated_date': datetime.utcnow(),
            'file_size': file_size,
            'file_path': file_path,
            'generated_by': generated_by,
            'status': 'active'
        }
        if summary is not None:
            report_data['summary'] = summary
        _, doc_ref = self.db.collection('reports').add(report_data)
        return doc_ref.id

    def get_report(self, report_id: str) -> Optional[Dict]:
        doc = self.db.collection('reports').document(report_id).get()
        return {'id': doc.id, **doc.to_dict()} if doc.exists else None
    
    def update_report(self, report_id: str, updates: Dict) -> None:
        """Update a report document."""
        self.db.collection('reports').document(report_id).update(updates)
    
    def delete_report(self, report_id: str, permanent: bool = False, deleted_by: str = None) -> None:
        """
        Delete a report (soft delete by default).
        
        Args:
            report_id: Report document ID
            permanent: If True, permanently delete
            deleted_by: User who deleted the report
        """
        if permanent:
            self.db.collection('reports').document(report_id).delete()
        else:
            self.db.collection('reports').document(report_id).update({
                'status': 'deleted',
                'deleted_date': datetime.utcnow(),
                'deleted_by': deleted_by or 'System Admin'
            })
    
    def restore_report(self, report_id: str) -> None:
        """Restore a deleted report."""
        self.db.collection('reports').document(report_id).update({
            'status': 'active'
        })
    
    # ==================== SENSOR READINGS OPERATIONS ====================
    
    def get_sensor_readings(self, limit: int = 100) -> List[Dict]:
        """Get latest sensor readings (Realtime Database first, then Firestore)."""
        from app.realtime_db_service import get_sensor_readings as get_rtdb_readings

        rtdb_readings = get_rtdb_readings(limit=limit)
        if rtdb_readings:
            return rtdb_readings

        docs = self.db.collection('sensor_readings').order_by(
            'timestamp', direction=Query.DESCENDING
        ).limit(limit).stream()
        
        readings = []
        for doc in docs:
            readings.append({'id': doc.id, **doc.to_dict()})
        return readings
    
    def create_sensor_reading(self, temperature: float = None, ph: float = None,
                              turbidity: float = None, orp: float = None,
                              ec: float = None) -> str:
        """Create a new sensor reading (Temp, pH, Turbidity, ORP, EC)."""
        reading_data = {
            'temperature': temperature,
            'ph': ph,
            'turbidity': turbidity,
            'orp': orp,
            'ec': ec,
            'timestamp': datetime.utcnow()
        }
        _, doc_ref = self.db.collection('sensor_readings').add(reading_data)
        return doc_ref.id
    
    # ==================== DEVICE OPERATIONS ====================
    
    def get_all_devices(self) -> List[Dict]:
        """Get all devices."""
        docs = self.db.collection('devices').stream()
        
        devices = []
        for doc in docs:
            devices.append({'id': doc.id, **doc.to_dict()})
        return devices
    
    def get_device(self, device_id: str) -> Optional[Dict]:
        """Get a specific device."""
        doc = self.db.collection('devices').document(device_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None
    
    def create_device(self, device_name: str, imei_number: str, location_description: str = '') -> str:
        """Create a new device."""
        device_data = {
            'device_name': device_name,
            'imei_number': imei_number,
            'battery_level': 100,
            'last_heartbeat': datetime.utcnow(),
            'is_connected': True,
            'location_description': location_description
        }
        _, doc_ref = self.db.collection('devices').add(device_data)
        return doc_ref.id
    
    def update_device(self, device_id: str, updates: Dict) -> None:
        """Update a device."""
        self.db.collection('devices').document(device_id).update(updates)
    
    # ==================== BLOOM RISK ANALYSIS OPERATIONS ====================
    
    def get_latest_bloom_risk_analysis(self) -> Optional[Dict]:
        """Get the latest bloom risk analysis."""
        docs = self.db.collection('bloom_risk_analysis').order_by(
            'analysis_timestamp', direction=Query.DESCENDING
        ).limit(1).stream()
        
        for doc in docs:
            return {'id': doc.id, **doc.to_dict()}
        return None
    
    def create_bloom_risk_analysis(self, risk_score: float, risk_level: str, 
                                   triggered_rules: str, requires_lab_verification: bool = False) -> str:
        """Create a bloom risk analysis record."""
        analysis_data = {
            'risk_score': risk_score,
            'risk_level': risk_level,
            'triggered_rules': triggered_rules,
            'requires_lab_verification': requires_lab_verification,
            'analysis_timestamp': datetime.utcnow()
        }
        _, doc_ref = self.db.collection('bloom_risk_analysis').add(analysis_data)
        return doc_ref.id
    
    # ==================== UTILITY OPERATIONS ====================
    
    def collection_exists(self, collection_name: str) -> bool:
        """Check if a collection has any documents."""
        try:
            docs = self.db.collection(collection_name).limit(1).stream()
            return any(True for _ in docs)
        except:
            return False


# Create a singleton instance
_firestore_service = None

def get_firestore_service() -> FirestoreService:
    """Get the Firestore service singleton."""
    global _firestore_service
    if _firestore_service is None:
        _firestore_service = FirestoreService()
    return _firestore_service
