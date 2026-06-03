"""
Firestore Models Module
Defines data models for Firestore collections.
"""

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import login_manager
from app.firestore_service import get_firestore_service
from typing import Optional, Dict, Any
from datetime import datetime


class User(UserMixin):
    """
    User model for Firestore authentication.
    Implements Flask-Login UserMixin for session management.
    """
    
    def __init__(self, email: str, role: str = 'authority', user_id: str = None, password_hash: str = None):
        self.id = user_id
        self.email = email
        self.role = role
        self.password_hash = password_hash
    
    def set_password(self, password: str) -> None:
        """Hash and set the password."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password: str) -> bool:
        """Verify the password against the hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def save(self) -> str:
        """
        Save user to Firestore.
        
        Returns:
            User document ID
        """
        db = get_firestore_service()
        if self.id:
            # Update existing user
            db.db.collection('users').document(self.id).update({
                'email_id': self.email,
                'password': self.password_hash,
                'role': self.role
            })
            return self.id
        else:
            # Create new user
            doc_ref = db.db.collection('users').add({
                'email_id': self.email,
                'password': self.password_hash,
                'role': self.role,
                'created_at': datetime.utcnow()
            })
            self.id = doc_ref[1].id
            return self.id
    
    def delete(self) -> None:
        """Delete user from Firestore."""
        if self.id:
            db = get_firestore_service()
            db.db.collection('users').document(self.id).delete()
    
    @staticmethod
    def get_by_email(email: str) -> Optional['User']:
        """
        Retrieve a user by email from Firestore.
        
        Args:
            email: User email address
            
        Returns:
            User instance or None if not found
        """
        db = get_firestore_service()
        user_data = db.get_user_by_email(email)
        
        if user_data:
            return User(
                email=user_data['email_id'],
                role=user_data.get('role', 'authority'),
                user_id=user_data['id'],
                password_hash=user_data.get('password')
            )
        return None
    
    @staticmethod
    def get_by_id(user_id: str) -> Optional['User']:
        """
        Retrieve a user by ID from Firestore.
        
        Args:
            user_id: User document ID
            
        Returns:
            User instance or None if not found
        """
        db = get_firestore_service()
        user_doc = db.db.collection('users').document(user_id).get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return User(
                email=user_data['email_id'],
                role=user_data.get('role', 'authority'),
                user_id=user_id,
                password_hash=user_data.get('password')
            )
        return None


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    """Load user by ID for Flask-Login session management."""
    return User.get_by_id(user_id)


class SensorData:
    """Sensor reading data model for Firestore."""
    
    def __init__(self, temperature: float, ph: float, dissolved_oxygen: float,
                 salinity: float, turbidity: float, reading_id: str = None, timestamp: datetime = None):
        self.id = reading_id
        self.temperature = temperature
        self.ph = ph
        self.dissolved_oxygen = dissolved_oxygen
        self.salinity = salinity
        self.turbidity = turbidity
        self.timestamp = timestamp or datetime.utcnow()
    
    def save(self) -> str:
        """Save sensor reading to Firestore."""
        db = get_firestore_service()
        if self.id:
            db.db.collection('sensor_readings').document(self.id).update({
                'temperature': self.temperature,
                'ph': self.ph,
                'dissolved_oxygen': self.dissolved_oxygen,
                'salinity': self.salinity,
                'turbidity': self.turbidity,
                'timestamp': self.timestamp
            })
            return self.id
        else:
            doc_ref = db.db.collection('sensor_readings').add({
                'temperature': self.temperature,
                'ph': self.ph,
                'dissolved_oxygen': self.dissolved_oxygen,
                'salinity': self.salinity,
                'turbidity': self.turbidity,
                'timestamp': self.timestamp
            })
            self.id = doc_ref[1].id
            return self.id


class Alert:
    """Alert model for Firestore."""
    
    def __init__(self, alert_type: str, risk_level: str, message: str, 
                 alert_id: str = None, is_acknowledged: bool = False, 
                 is_deleted: bool = False, timestamp: datetime = None):
        self.alert_id = alert_id
        self.alert_type = alert_type
        self.risk_level = risk_level
        self.alert_message = message
        self.is_acknowledged = is_acknowledged
        self.is_deleted = is_deleted
        self.alert_timestamp = timestamp or datetime.utcnow()
    
    def save(self) -> str:
        """Save alert to Firestore."""
        db = get_firestore_service()
        if self.alert_id:
            db.db.collection('alerts').document(self.alert_id).update({
                'alert_type': self.alert_type,
                'risk_level': self.risk_level,
                'alert_message': self.alert_message,
                'is_acknowledged': self.is_acknowledged,
                'is_deleted': self.is_deleted,
                'alert_timestamp': self.alert_timestamp
            })
            return self.alert_id
        else:
            doc_ref = db.db.collection('alerts').add({
                'alert_type': self.alert_type,
                'risk_level': self.risk_level,
                'alert_message': self.alert_message,
                'is_acknowledged': self.is_acknowledged,
                'is_deleted': self.is_deleted,
                'alert_timestamp': self.alert_timestamp
            })
            self.alert_id = doc_ref[1].id
            return self.alert_id
    
    def delete(self, permanent: bool = False) -> None:
        """Soft delete (move to deleted_alerts) or permanently delete an alert."""
        db = get_firestore_service()
        if not self.alert_id:
            return
        
        if permanent:
            db.db.collection('alerts').document(self.alert_id).delete()
        else:
            db.db.collection('alerts').document(self.alert_id).update({
                'is_deleted': True,
                'deleted_at': datetime.utcnow()
            })
    
    def restore(self) -> None:
        """Restore a soft-deleted alert."""
        db = get_firestore_service()
        if self.alert_id:
            db.db.collection('alerts').document(self.alert_id).update({
                'is_deleted': False,
                'deleted_at': None
            })


class Report:
    """Report model for Firestore."""
    
    def __init__(self, report_name: str, report_type: str, report_id: str = None,
                 file_path: str = None, file_size: str = '2.4 MB', 
                 generated_by: str = 'System Auto', status: str = 'active', 
                 generated_date: datetime = None):
        self.report_id = report_id
        self.report_name = report_name
        self.report_type = report_type
        self.generated_date = generated_date or datetime.utcnow()
        self.file_size = file_size
        self.file_path = file_path
        self.generated_by = generated_by
        self.status = status
    
    def save(self) -> str:
        """Save report to Firestore."""
        db = get_firestore_service()
        if self.report_id:
            db.db.collection('reports').document(self.report_id).update({
                'report_name': self.report_name,
                'report_type': self.report_type,
                'generated_date': self.generated_date,
                'file_size': self.file_size,
                'file_path': self.file_path,
                'generated_by': self.generated_by,
                'status': self.status
            })
            return self.report_id
        else:
            doc_ref = db.db.collection('reports').add({
                'report_name': self.report_name,
                'report_type': self.report_type,
                'generated_date': self.generated_date,
                'file_size': self.file_size,
                'file_path': self.file_path,
                'generated_by': self.generated_by,
                'status': self.status
            })
            self.report_id = doc_ref[1].id
            return self.report_id
    
    def delete(self, permanent: bool = False, deleted_by: str = None) -> None:
        """Soft delete or permanently delete a report."""
        db = get_firestore_service()
        if not self.report_id:
            return
        
        if permanent:
            db.db.collection('reports').document(self.report_id).delete()
        else:
            db.db.collection('reports').document(self.report_id).update({
                'status': 'deleted',
                'deleted_date': datetime.utcnow(),
                'deleted_by': deleted_by or 'System Admin'
            })
    
    def restore(self) -> None:
        """Restore a deleted report."""
        db = get_firestore_service()
        if self.report_id:
            db.db.collection('reports').document(self.report_id).update({
                'status': 'active'
            })


class Device:
    """Device model for Firestore."""
    
    def __init__(self, device_name: str, imei_number: str, device_id: str = None,
                 battery_level: int = 100, last_heartbeat: datetime = None,
                 is_connected: bool = True, location_description: str = ''):
        self.device_id = device_id
        self.device_name = device_name
        self.imei_number = imei_number
        self.battery_level = battery_level
        self.last_heartbeat = last_heartbeat or datetime.utcnow()
        self.is_connected = is_connected
        self.location_description = location_description
    
    def save(self) -> str:
        """Save device to Firestore."""
        db = get_firestore_service()
        if self.device_id:
            db.db.collection('devices').document(self.device_id).update({
                'device_name': self.device_name,
                'imei_number': self.imei_number,
                'battery_level': self.battery_level,
                'last_heartbeat': self.last_heartbeat,
                'is_connected': self.is_connected,
                'location_description': self.location_description
            })
            return self.device_id
        else:
            doc_ref = db.db.collection('devices').add({
                'device_name': self.device_name,
                'imei_number': self.imei_number,
                'battery_level': self.battery_level,
                'last_heartbeat': self.last_heartbeat,
                'is_connected': self.is_connected,
                'location_description': self.location_description
            })
            self.device_id = doc_ref[1].id
            return self.device_id

