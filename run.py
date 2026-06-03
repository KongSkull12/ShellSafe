from app import create_app
from app.models import User, Alert
from app.firestore_service import get_firestore_service

app = create_app()

@app.shell_context_processor
def make_shell_context():
    return {'app': app, 'User': User, 'Alert': Alert}

@app.cli.command("create-users")
def create_users():
    """Create default user accounts in Firestore."""
    db = get_firestore_service()
    
    # Check if admin user already exists
    admin_user = User.get_by_email('system.admin@gmail.com')
    if not admin_user:
        admin = User(email='system.admin@gmail.com', role='admin')
        admin.set_password('admin123')
        admin.save()
        print("Admin user created: system.admin@gmail.com")
    else:
        print("Admin user already exists.")

    # Check if authority user already exists
    authority_user = User.get_by_email('coastal.auth@gmail.com')
    if not authority_user:
        authority = User(email='coastal.auth@gmail.com', role='authority')
        authority.set_password('coast123')
        authority.save()
        print("Authority user created: coastal.auth@gmail.com")
    else:
        print("Authority user already exists.")

@app.cli.command("create-alerts")
def create_alerts():
    """Create sample alerts in Firestore."""
    db = get_firestore_service()
    
    # Check if alerts already exist
    existing_alerts = db.get_all_alerts()
    if len(existing_alerts) > 0:
        print(f"Alerts already exist. ({len(existing_alerts)} alerts found)")
        return
    
    alerts_data = [
        {
            "alert_type": "RISK",
            "risk_level": "Critical",
            "alert_message": "HIGH RISK: Critical algal bloom conditions detected! Temperature (31°C) and pH (8.9) exceed safe thresholds. Immediate action required."
        },
        {
            "alert_type": "RISK",
            "risk_level": "Moderate",
            "alert_message": "Medium risk level detected. Dissolved oxygen levels dropping (4.2 mg/L). Monitor closely."
        },
        {
            "alert_type": "BATTERY",
            "risk_level": "Warning",
            "alert_message": "Low battery alert. Sensor Node B-12 battery at 18%. Please recharge within 24 hours."
        },
        {
            "alert_type": "DEVICE_OFFLINE",
            "risk_level": "Warning",
            "alert_message": "Device D-05 (Coastal Monitoring Station) is offline. Last heartbeat was 2 hours ago."
        },
        {
            "alert_type": "RISK",
            "risk_level": "High",
            "alert_message": "High risk detected. Turbidity levels elevated. Possible sediment disturbance."
        }
    ]
    
    for alert_data in alerts_data:
        db.create_alert(
            alert_type=alert_data['alert_type'],
            risk_level=alert_data['risk_level'],
            message=alert_data['alert_message']
        )
        print(f"Alert created: {alert_data['alert_type']} - {alert_data['risk_level']}")
    
    print(f"Total {len(alerts_data)} sample alerts created.")

@app.cli.command("init-db")
def init_db():
    """Initialize Firestore database with default data."""
    print("Initializing Firestore database...")
    create_users()
    create_alerts()
    print("Database initialization complete!")

if __name__ == '__main__':
    app.run(debug=True)
