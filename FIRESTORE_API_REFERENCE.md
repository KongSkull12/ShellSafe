# ShellSafe Firestore API Reference

This document provides comprehensive API reference for the Firestore service layer used in ShellSafe.

---

## Table of Contents

1. [Firestore Service](#firestore-service)
2. [User Management](#user-management)
3. [Alert Management](#alert-management)
4. [Report Management](#report-management)
5. [Sensor Data](#sensor-data)
6. [Device Management](#device-management)
7. [Bloom Risk Analysis](#bloom-risk-analysis)
8. [Usage Examples](#usage-examples)

---

## Firestore Service

### Getting the Service Instance

```python
from app.firestore_service import get_firestore_service

db = get_firestore_service()
```

The service is a singleton - multiple calls return the same instance.

---

## User Management

### Get User by Email

```python
from app.models import User

user = User.get_by_email('system.admin@gmail.com')
# Returns: User object or None
```

**Parameters:**
- `email` (str): User email address

**Returns:** User instance or None if not found

---

### Get User by ID

```python
user = User.get_by_id('user_doc_id')
# Returns: User object or None
```

**Parameters:**
- `user_id` (str): Firestore user document ID

**Returns:** User instance or None if not found

---

### Create User

```python
from app.models import User

user = User(email='newuser@example.com', role='authority')
user.set_password('password123')
user_id = user.save()

# Returns: Firestore document ID
```

**Parameters:**
- `email` (str): User email
- `role` (str): 'admin' or 'authority'

**Returns:** User document ID (string)

---

### Check Password

```python
user = User.get_by_email('user@example.com')
if user and user.check_password('entered_password'):
    print("Password correct!")
```

**Parameters:**
- `password` (str): Password to verify

**Returns:** Boolean

---

### Delete User

```python
user = User.get_by_id('user_doc_id')
user.delete()
```

---

## Alert Management

### Get All Alerts

```python
from app.firestore_service import get_firestore_service

db = get_firestore_service()
alerts = db.get_all_alerts(exclude_deleted=True)

# Returns: List of alert dictionaries
# [
#   {
#     'id': 'alert_id',
#     'alert_type': 'RISK',
#     'risk_level': 'High',
#     'alert_message': 'Alert text...',
#     'is_acknowledged': False,
#     'is_deleted': False,
#     'alert_timestamp': datetime
#   },
#   ...
# ]
```

**Parameters:**
- `exclude_deleted` (bool): If True, exclude soft-deleted alerts (default: True)

**Returns:** List of alert dictionaries

---

### Get Risk Alerts Only

```python
risk_alerts = db.get_risk_alerts()
# Only returns alerts where alert_type == 'RISK' and not deleted
```

**Returns:** List of RISK-type alert dictionaries

---

### Create Alert

```python
alert_id = db.create_alert(
    alert_type='RISK',
    risk_level='Critical',
    message='Critical algal bloom detected!'
)

# Returns: Alert document ID
```

**Parameters:**
- `alert_type` (str): Type of alert (e.g., 'RISK', 'BATTERY', 'DEVICE_OFFLINE')
- `risk_level` (str): Risk level (e.g., 'Critical', 'High', 'Moderate', 'Warning')
- `message` (str): Alert message text

**Returns:** Alert document ID (string)

---

### Update Alert

```python
db.update_alert('alert_id', {
    'is_acknowledged': True,
    'risk_level': 'High'
})
```

**Parameters:**
- `alert_id` (str): Alert document ID
- `updates` (dict): Fields to update

**Returns:** None

---

### Delete Alert (Soft Delete)

```python
db.delete_alert('alert_id', permanent=False)
# Sets is_deleted=True and records deleted_at timestamp
```

**Parameters:**
- `alert_id` (str): Alert document ID
- `permanent` (bool): If True, permanently delete; if False, soft delete

**Returns:** None

---

### Get Deleted Alerts

```python
deleted_alerts = db.get_deleted_alerts()
# Returns: List of soft-deleted alert dictionaries
```

**Returns:** List of alert dictionaries with is_deleted=True

---

### Restore Alert

```python
db.restore_alert('alert_id')
# Sets is_deleted=False and deleted_at=None
```

**Parameters:**
- `alert_id` (str): Alert document ID

**Returns:** None

---

## Report Management

### Get All Reports

```python
# Get active reports
active_reports = db.get_all_reports(status='active')

# Get deleted reports
deleted_reports = db.get_all_reports(status='deleted')
```

**Parameters:**
- `status` (str): 'active' or 'deleted'

**Returns:** List of report dictionaries

---

### Create Report

```python
report_id = db.create_report(
    report_name='Monthly Report - January 2024',
    report_type='monthly',
    file_path='/reports/monthly_2024_01.pdf',
    file_size='2.4 MB',
    generated_by='System Auto'
)

# Returns: Report document ID
```

**Parameters:**
- `report_name` (str): Report name
- `report_type` (str): Type (e.g., 'monthly', 'weekly', 'annual')
- `file_path` (str, optional): Path to report file
- `file_size` (str, optional): File size (default: '2.4 MB')
- `generated_by` (str, optional): User/system that generated (default: 'System Auto')

**Returns:** Report document ID (string)

---

### Update Report

```python
db.update_report('report_id', {
    'file_path': '/new/path/report.pdf',
    'file_size': '3.2 MB'
})
```

**Parameters:**
- `report_id` (str): Report document ID
- `updates` (dict): Fields to update

**Returns:** None

---

### Delete Report

```python
# Soft delete
db.delete_report('report_id', permanent=False, deleted_by='admin')

# Permanent delete
db.delete_report('report_id', permanent=True)
```

**Parameters:**
- `report_id` (str): Report document ID
- `permanent` (bool): If True, permanently delete
- `deleted_by` (str, optional): Who deleted it

**Returns:** None

---

### Restore Report

```python
db.restore_report('report_id')
```

**Parameters:**
- `report_id` (str): Report document ID

**Returns:** None

---

## Sensor Data

### Get Sensor Readings

```python
# Get latest 100 readings
readings = db.get_sensor_readings(limit=100)

# Get latest 10 readings
recent_readings = db.get_sensor_readings(limit=10)

# Returns: List of sensor reading dictionaries
# [
#   {
#     'id': 'reading_id',
#     'temperature': 28.5,
#     'ph': 7.8,
#     'dissolved_oxygen': 6.5,
#     'salinity': 35.2,
#     'turbidity': 0.8,
#     'timestamp': datetime
#   },
#   ...
# ]
```

**Parameters:**
- `limit` (int): Number of most recent readings to return (default: 100)

**Returns:** List of sensor reading dictionaries

---

### Create Sensor Reading

```python
reading_id = db.create_sensor_reading(
    temperature=28.5,
    ph=7.8,
    dissolved_oxygen=6.5,
    salinity=35.2,
    turbidity=0.8
)

# Returns: Reading document ID
```

**Parameters:**
- `temperature` (float): Water temperature in Celsius
- `ph` (float): pH level
- `dissolved_oxygen` (float): Dissolved oxygen in mg/L
- `salinity` (float): Salinity in PSU
- `turbidity` (float): Turbidity in NTU

**Returns:** Sensor reading document ID (string)

---

## Device Management

### Get All Devices

```python
devices = db.get_all_devices()

# Returns: List of device dictionaries
# [
#   {
#     'id': 'device_id',
#     'device_name': 'Coastal Station A',
#     'imei_number': '123456789012345',
#     'battery_level': 85,
#     'last_heartbeat': datetime,
#     'is_connected': true,
#     'location_description': 'North Bay'
#   },
#   ...
# ]
```

**Returns:** List of device dictionaries

---

### Get Specific Device

```python
device = db.get_device('device_id')

# Returns: Device dictionary or None if not found
```

**Parameters:**
- `device_id` (str): Firestore device document ID

**Returns:** Device dictionary or None

---

### Create Device

```python
device_id = db.create_device(
    device_name='Coastal Station B',
    imei_number='987654321098765',
    location_description='South Bay'
)

# Returns: Device document ID
```

**Parameters:**
- `device_name` (str): Name of the device
- `imei_number` (str): IMEI/Serial number
- `location_description` (str, optional): Location description

**Returns:** Device document ID (string)

---

### Update Device

```python
db.update_device('device_id', {
    'battery_level': 45,
    'is_connected': False,
    'last_heartbeat': datetime.utcnow()
})
```

**Parameters:**
- `device_id` (str): Device document ID
- `updates` (dict): Fields to update

**Returns:** None

---

## Bloom Risk Analysis

### Get Latest Bloom Risk Analysis

```python
latest_analysis = db.get_latest_bloom_risk_analysis()

# Returns: Dictionary or None
# {
#   'id': 'analysis_id',
#   'risk_score': 7.5,
#   'risk_level': 'High',
#   'triggered_rules': 'Temperature > 28, pH > 8.5',
#   'requires_lab_verification': False,
#   'analysis_timestamp': datetime
# }
```

**Returns:** Latest bloom risk analysis dictionary or None

---

### Create Bloom Risk Analysis

```python
analysis_id = db.create_bloom_risk_analysis(
    risk_score=7.5,
    risk_level='High',
    triggered_rules='Temperature > 28, pH > 8.5',
    requires_lab_verification=False
)

# Returns: Analysis document ID
```

**Parameters:**
- `risk_score` (float): Risk score (0-10)
- `risk_level` (str): Risk level ('Low', 'Moderate', 'High', 'Critical')
- `triggered_rules` (str): Description of triggered rules
- `requires_lab_verification` (bool, optional): Lab verification needed

**Returns:** Analysis document ID (string)

---

## Usage Examples

### Example 1: Complete Alert Workflow

```python
from app.firestore_service import get_firestore_service
from datetime import datetime

db = get_firestore_service()

# Create an alert
alert_id = db.create_alert(
    alert_type='RISK',
    risk_level='High',
    message='Water temperature exceeds safe level'
)
print(f"Alert created: {alert_id}")

# Retrieve all active alerts
alerts = db.get_all_alerts(exclude_deleted=True)
print(f"Active alerts: {len(alerts)}")

# Mark alert as acknowledged
db.update_alert(alert_id, {'is_acknowledged': True})

# Soft delete the alert
db.delete_alert(alert_id, permanent=False)

# Get deleted alerts
deleted = db.get_deleted_alerts()
print(f"Deleted alerts: {len(deleted)}")

# Restore the alert
db.restore_alert(alert_id)

# Permanently delete
db.delete_alert(alert_id, permanent=True)
```

---

### Example 2: User Authentication

```python
from app.models import User

# Create a new user
new_user = User(email='researcher@example.com', role='authority')
new_user.set_password('secure_password_123')
new_user.save()

# Login process
user = User.get_by_email('researcher@example.com')
if user and user.check_password('secure_password_123'):
    print(f"Login successful for {user.email}")
    print(f"Role: {user.role}")
    # Flask-Login handles the session from here
else:
    print("Login failed")

# Retrieve by ID (e.g., from session)
user = User.get_by_id(user.id)
print(f"Retrieved user: {user.email}")
```

---

### Example 3: Sensor Data Collection

```python
from app.firestore_service import get_firestore_service

db = get_firestore_service()

# Record sensor readings
sensor_data = {
    'temperature': 26.8,
    'ph': 7.9,
    'dissolved_oxygen': 7.2,
    'salinity': 34.8,
    'turbidity': 0.6
}

reading_id = db.create_sensor_reading(**sensor_data)
print(f"Sensor reading recorded: {reading_id}")

# Retrieve recent readings
recent = db.get_sensor_readings(limit=24)  # Last 24 readings
print(f"Retrieved {len(recent)} recent readings")

# Analyze trend
temps = [r['temperature'] for r in recent]
avg_temp = sum(temps) / len(temps)
print(f"Average temperature: {avg_temp}°C")
```

---

### Example 4: Report Management

```python
from app.firestore_service import get_firestore_service

db = get_firestore_service()

# Generate a report
report_id = db.create_report(
    report_name='Monthly Water Quality Report',
    report_type='monthly',
    file_path='/reports/monthly_2024_01.pdf',
    file_size='2.8 MB'
)

# Get all active reports
active = db.get_all_reports(status='active')
print(f"Active reports: {len(active)}")

# Soft delete a report (move to deleted)
db.delete_report(report_id, permanent=False)

# Get deleted reports
deleted = db.get_all_reports(status='deleted')
print(f"Deleted reports: {len(deleted)}")

# Restore a report
db.restore_report(report_id)

# Verify it's active again
active = db.get_all_reports(status='active')
print(f"Report restored, active count: {len(active)}")
```

---

### Example 5: Admin Dashboard Data

```python
from app.firestore_service import get_firestore_service
from flask_login import current_user

db = get_firestore_service()

# Prepare data for admin dashboard
dashboard_data = {
    'sensor_readings': db.get_sensor_readings(limit=10),
    'recent_alerts': db.get_all_alerts(exclude_deleted=True)[:5],
    'devices': db.get_all_devices(),
    'bloom_analysis': db.get_latest_bloom_risk_analysis(),
    'active_reports': db.get_all_reports(status='active')
}

print(f"Dashboard prepared with:")
print(f"  - {len(dashboard_data['sensor_readings'])} recent readings")
print(f"  - {len(dashboard_data['recent_alerts'])} recent alerts")
print(f"  - {len(dashboard_data['devices'])} devices")
print(f"  - {len(dashboard_data['active_reports'])} active reports")
```

---

### Example 6: Batch Operations

```python
from app.firestore_service import get_firestore_service

db = get_firestore_service()

# Mark all alerts as acknowledged
all_alerts = db.get_all_alerts(exclude_deleted=True)
for alert in all_alerts:
    if not alert.get('is_acknowledged'):
        db.update_alert(alert['id'], {'is_acknowledged': True})

print(f"Updated {len(all_alerts)} alerts")

# Delete all acknowledged alerts (soft delete)
for alert in all_alerts:
    db.delete_alert(alert['id'], permanent=False)

print(f"Deleted {len(all_alerts)} alerts")
```

---

## Error Handling

All methods include error handling. Common scenarios:

```python
# Handle missing user
user = User.get_by_email('nonexistent@example.com')
if user is None:
    print("User not found")

# Handle missing alert
alert = db.db.collection('alerts').document('invalid_id').get()
if not alert.exists:
    print("Alert not found")

# Handle missing device
device = db.get_device('invalid_id')
if device is None:
    print("Device not found")

# Handle Firebase connection
try:
    db = get_firestore_service()
    alerts = db.get_all_alerts()
except Exception as e:
    print(f"Firebase error: {str(e)}")
```

---

## Best Practices

1. **Always use singleton pattern:**
   ```python
   db = get_firestore_service()  # Same instance reused
   ```

2. **Batch operations when possible:**
   ```python
   # Good - minimize Firestore calls
   for alert in db.get_all_alerts():
       db.update_alert(alert['id'], {...})
   ```

3. **Use try-except for production:**
   ```python
   try:
       result = db.create_alert(...)
   except Exception as e:
       logger.error(f"Failed to create alert: {e}")
       raise
   ```

4. **Always check existence before operations:**
   ```python
   user = User.get_by_email(email)
   if user is None:
       # Handle not found
       pass
   ```

5. **Use appropriate limits for queries:**
   ```python
   # Get last 100 readings instead of all
   recent = db.get_sensor_readings(limit=100)
   ```

---

## Performance Tips

- Use `limit()` on queries to reduce data transfer
- Cache frequently accessed data in memory
- Batch multiple operations
- Use indexed fields for filtering
- Monitor Firestore usage in Firebase Console

---

For more information, see:
- FIREBASE_MIGRATION_GUIDE.md
- MIGRATION_SUMMARY.md
- Firebase Firestore Documentation
