# ShellSafe Firebase Firestore Migration Guide

## Overview

This document provides complete setup and migration instructions for converting ShellSafe from SQLite to Firebase Firestore.

## Prerequisites

Before starting, ensure you have:
- Firebase project created (go to [Firebase Console](https://console.firebase.google.com))
- Service account JSON key downloaded
- Python 3.7 or higher
- All dependencies installed

## Setup Steps

### 1. Get Firebase Service Account Key

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select your project
3. Go to **Project Settings** → **Service Accounts**
4. Click **Generate New Private Key**
5. Save the JSON file as `serviceAccountKey.json` in the project root directory

```
SHELLSAFE/
├── serviceAccountKey.json  ← Place your Firebase key here
├── firebase_config.py
├── config.py
├── requirements.txt
├── run.py
└── app/
```

### 2. Install Dependencies

```bash
# Activate virtual environment
venv\Scripts\activate

# Install updated requirements
pip install -r requirements.txt
```

**Removed SQLAlchemy packages:**
- Flask-SQLAlchemy
- Flask-Migrate
- SQLAlchemy
- alembic
- mysqlclient

**Added Firebase package:**
- firebase-admin

### 3. Initialize Firebase and Database

```bash
# Create default users (admin and authority)
python -m flask create-users

# Create sample alerts
python -m flask create-alerts

# Or initialize everything at once
python -m flask init-db
```

### 4. Run the Application

```bash
python run.py
```

The application will start on `http://localhost:5000`

## Default Accounts

### Admin Account
- **Email:** system.admin@gmail.com
- **Password:** admin123
- **Role:** admin
- **Access:** Full system including devices, sensor data, reports, and alerts

### Authority Account
- **Email:** coastal.auth@gmail.com
- **Password:** coast123
- **Role:** authority
- **Access:** Sensor data, reports, and alerts (no devices)

## Firestore Collection Schema

### 1. Users Collection
```json
{
  "email_id": "user@example.com",
  "password": "hashed_password_here",
  "role": "admin",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### 2. Alerts Collection
```json
{
  "alert_type": "RISK",
  "risk_level": "Critical",
  "alert_message": "Alert message here",
  "is_acknowledged": false,
  "is_deleted": false,
  "alert_timestamp": "2024-01-01T00:00:00Z",
  "deleted_at": null
}
```

### 3. Sensor Readings Collection
```json
{
  "temperature": 28.5,
  "ph": 7.8,
  "dissolved_oxygen": 6.5,
  "salinity": 35.2,
  "turbidity": 0.8,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### 4. Devices Collection
```json
{
  "device_name": "Coastal Station A",
  "imei_number": "123456789012345",
  "battery_level": 85,
  "last_heartbeat": "2024-01-01T00:00:00Z",
  "is_connected": true,
  "location_description": "North Bay"
}
```

### 5. Bloom Risk Analysis Collection
```json
{
  "risk_score": 7.5,
  "risk_level": "High",
  "triggered_rules": "Temperature > 28, pH > 8.5",
  "requires_lab_verification": false,
  "analysis_timestamp": "2024-01-01T00:00:00Z"
}
```

### 6. Reports Collection
```json
{
  "report_name": "Monthly Report - January 2024",
  "report_type": "monthly",
  "generated_date": "2024-01-01T00:00:00Z",
  "file_size": "2.4 MB",
  "file_path": "/reports/monthly_2024_01.pdf",
  "generated_by": "System Auto",
  "status": "active",
  "deleted_date": null,
  "deleted_by": null
}
```

## File Changes Summary

### New Files
- **firebase_config.py** - Firebase initialization and configuration
- **app/firestore_service.py** - Firestore operations abstraction layer

### Modified Files
- **requirements.txt** - Removed SQLAlchemy packages, added firebase-admin
- **config.py** - Removed SQLAlchemy configuration
- **app/__init__.py** - Replaced SQLAlchemy with Firebase/Firestore
- **app/models.py** - Converted models to Firestore-compatible classes
- **app/auth/routes.py** - Updated authentication to use Firestore
- **app/main/routes.py** - Converted all database queries to Firestore
- **run.py** - Updated CLI commands for Firestore initialization

### Removed Files
- **.db files** - SQLite database files (no longer needed)
- **migrations/** directory - Alembic migrations (not needed with Firestore)

## CRUD Operations Reference

### Create (INSERT)
```python
from app.firestore_service import get_firestore_service

db = get_firestore_service()

# Create alert
alert_id = db.create_alert(
    alert_type='RISK',
    risk_level='High',
    message='High algal bloom risk detected'
)

# Create user
user = User(email='user@example.com', role='authority')
user.set_password('password')
user_id = user.save()
```

### Read (SELECT)
```python
# Get all alerts
alerts = db.get_all_alerts(exclude_deleted=True)

# Get user by email
user = User.get_by_email('system.admin@gmail.com')

# Get sensor readings
readings = db.get_sensor_readings(limit=100)
```

### Update (UPDATE)
```python
# Update alert
db.update_alert(alert_id, {'is_acknowledged': True})

# Update device
db.update_device(device_id, {'battery_level': 75})
```

### Delete (DELETE)
```python
# Soft delete alert (moves to deleted)
db.delete_alert(alert_id, permanent=False)

# Permanent delete
db.delete_alert(alert_id, permanent=True)

# Restore deleted alert
db.restore_alert(alert_id)
```

## Key Features

### Authentication
- ✓ User login with email and password (hashed with Werkzeug)
- ✓ Role-based access control (admin/authority)
- ✓ Flask-Login session management
- ✓ Firestore persistence

### Alerts
- ✓ Create, read, update alerts
- ✓ Soft delete (moves to deleted collection)
- ✓ Restore deleted alerts
- ✓ Permanent deletion
- ✓ Filter by type and status

### Reports
- ✓ Create and manage reports
- ✓ Soft delete functionality
- ✓ Restore reports
- ✓ Track deleted reports with timestamps

### Dashboards
- **Admin Dashboard:** Full access to all data
  - Sensor readings
  - Alerts
  - Devices
  - Bloom risk analysis
  
- **Authority Dashboard:** Limited access
  - Sensor readings
  - Alerts
  - Bloom risk analysis
  - ✗ No device access

### Data Management
- ✓ Sensor data history
- ✓ Device management (admin only)
- ✓ Real-time bloom risk analysis
- ✓ Battery and connection monitoring

## Security Notes

1. **Service Account Key:** Keep `serviceAccountKey.json` secure and never commit to version control
2. **Password Hashing:** Passwords are hashed using Werkzeug before storage in Firestore
3. **Firestore Rules:** Set appropriate Firestore security rules in your Firebase project
4. **Environment Variables:** Store sensitive configuration in environment variables

### Suggested Firestore Security Rules

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Only authenticated users can read/write
    match /{document=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```

## Troubleshooting

### Firebase Not Initialized
**Error:** "Firebase service account key not found"
- **Solution:** Ensure `serviceAccountKey.json` is in project root directory
- **Alternative:** Set `FIREBASE_KEY_PATH` environment variable

### Import Errors
**Error:** "No module named 'firebase_admin'"
- **Solution:** Run `pip install -r requirements.txt`

### Firestore Connection Issues
**Error:** Connection timeout or permission denied
- **Solution:** Check Firestore security rules and service account permissions

### User Not Found During Login
**Error:** "Invalid email or password" (but email/password is correct)
- **Solution:** Run `python -m flask create-users` to initialize default accounts

## API Reference

See **app/firestore_service.py** for complete method documentation:

```python
# User Management
get_user_by_email(email: str)
create_user(email: str, password_hash: str, role: str)
user_exists(email: str)

# Alerts
get_all_alerts(exclude_deleted: bool)
get_risk_alerts()
create_alert(alert_type: str, risk_level: str, message: str)
delete_alert(alert_id: str, permanent: bool)
restore_alert(alert_id: str)

# Reports
get_all_reports(status: str)
create_report(report_name: str, report_type: str, ...)
delete_report(report_id: str, permanent: bool, deleted_by: str)
restore_report(report_id: str)

# Sensor Data
get_sensor_readings(limit: int)
create_sensor_reading(temperature, ph, dissolved_oxygen, ...)

# Devices
get_all_devices()
get_device(device_id: str)
create_device(device_name: str, imei_number: str, ...)
update_device(device_id: str, updates: Dict)

# Bloom Risk
get_latest_bloom_risk_analysis()
create_bloom_risk_analysis(risk_score, risk_level, ...)
```

## Migration Checklist

- [ ] Firebase project created
- [ ] Service account key downloaded and placed in project root
- [ ] `requirements.txt` installed (`pip install -r requirements.txt`)
- [ ] Default users created (`python -m flask create-users`)
- [ ] Sample alerts created (`python -m flask create-alerts`)
- [ ] Application started (`python run.py`)
- [ ] Tested admin login (system.admin@gmail.com / admin123)
- [ ] Tested authority login (coastal.auth@gmail.com / coast123)
- [ ] Verified alert creation/retrieval
- [ ] Verified report functionality
- [ ] Tested soft delete and restore features

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Firestore documentation: https://cloud.google.com/firestore/docs
3. Check Firebase Admin SDK: https://firebase.google.com/docs/admin/setup
4. Review application logs and Flask error messages

---

**Migration Complete!** ✓ ShellSafe is now running on Firebase Firestore instead of SQLite.
