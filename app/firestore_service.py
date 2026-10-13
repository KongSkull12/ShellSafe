"""
Firestore Database Service Layer
Provides abstraction for Firestore operations.
"""

from firebase_config import get_firestore_client
from datetime import datetime
from typing import Dict, List, Any, Optional
from google.cloud.firestore import Query

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
    
    def get_all_alerts(self, exclude_deleted: bool = True) -> List[Dict]:
        """
        Retrieve all alerts.
        
        Args:
            exclude_deleted: If True, exclude deleted alerts
            
        Returns:
            List of alert documents
        """
        alerts = []
        for doc in self.db.collection('alerts').stream():
            data = doc.to_dict()
            if exclude_deleted and data.get('is_deleted', False):
                continue
            alerts.append({'id': doc.id, **data})
        
        alerts.sort(key=lambda x: x.get('alert_timestamp', datetime.utcnow()), reverse=True)
        return alerts
    
    def get_risk_alerts(self) -> List[Dict]:
        """Get all RISK type alerts that are not deleted."""
        alerts = []
        for doc in self.db.collection('alerts').stream():
            data = doc.to_dict()
            if data.get('is_deleted', False):
                continue
            if data.get('alert_type') != 'RISK':
                continue
            alerts.append({'id': doc.id, **data})
        
        alerts.sort(key=lambda x: x.get('alert_timestamp', datetime.utcnow()), reverse=True)
        return alerts

    def get_unread_alert_count(self) -> int:
        """Count non-deleted alerts that have not been acknowledged."""
        return sum(
            1
            for alert in self.get_all_alerts(exclude_deleted=True)
            if not alert.get('is_acknowledged', False)
        )

    def mark_all_alerts_read(self) -> int:
        """Acknowledge all unread alerts. Returns number updated."""
        updated = 0
        for alert in self.get_all_alerts(exclude_deleted=True):
            if not alert.get('is_acknowledged', False):
                self.update_alert(alert['id'], {'is_acknowledged': True})
                updated += 1
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
        return doc_ref.id
    
    def update_alert(self, alert_id: str, updates: Dict) -> None:
        """Update an alert document."""
        self.db.collection('alerts').document(alert_id).update(updates)
    
    def delete_alert(self, alert_id: str, permanent: bool = False) -> None:
        """
        Delete an alert (soft delete by default).
        
        Args:
            alert_id: Alert document ID
            permanent: If True, permanently delete; otherwise soft delete to deleted_alerts
        """
        alert = self.db.collection('alerts').document(alert_id).get()
        if not alert.exists:
            return
        
        alert_data = alert.to_dict()
        
        if permanent:
            self.db.collection('alerts').document(alert_id).delete()
        else:
            # Move to deleted_alerts collection
            alert_data['is_deleted'] = True
            alert_data['deleted_at'] = datetime.utcnow()
            self.db.collection('alerts').document(alert_id).update({'is_deleted': True, 'deleted_at': datetime.utcnow()})
    
    def get_deleted_alerts(self) -> List[Dict]:
        """Get all soft-deleted alerts."""
        alerts = []
        for doc in self.db.collection('alerts').stream():
            data = doc.to_dict()
            if not data.get('is_deleted', False):
                continue
            alerts.append({'id': doc.id, **data})
        
        alerts.sort(key=lambda x: x.get('deleted_at', datetime.utcnow()), reverse=True)
        return alerts
    
    def restore_alert(self, alert_id: str) -> None:
        """Restore a soft-deleted alert."""
        self.db.collection('alerts').document(alert_id).update({
            'is_deleted': False,
            'deleted_at': None
        })
    
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
                      file_size: str = '2.4 MB', generated_by: str = 'System Auto') -> str:
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
        _, doc_ref = self.db.collection('reports').add(report_data)
        return doc_ref.id
    
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
