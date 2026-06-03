# Quick Start Guide - Firebase Firestore Migration

## Step 1: Get Firebase Service Account Key

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select your project (or create a new one)
3. Click on **Project Settings** (gear icon)
4. Go to **Service Accounts** tab
5. Click **Generate New Private Key**
6. A JSON file will download - save it as `serviceAccountKey.json` in your project root

```
SHELLSAFE/
├── serviceAccountKey.json  ← Your Firebase key
├── firebase_config.py
├── config.py
├── run.py
└── app/
```

## Step 2: Install Dependencies

```bash
# Activate your virtual environment
venv\Scripts\activate

# Install/update packages
pip install -r requirements.txt
```

## Step 3: Initialize Database with Default Data

```bash
# Create default users (admin + authority)
python -m flask create-users

# Create sample alerts
python -m flask create-alerts

# Or do everything at once
python -m flask init-db
```

## Step 4: Run the Application

```bash
python run.py
```

Navigate to `http://localhost:5000` in your browser.

## Step 5: Test Login

### Admin Account
- **Email:** system.admin@gmail.com
- **Password:** admin123
- **Dashboard:** `/dashboard/admin` (full access)

### Authority Account
- **Email:** coastal.auth@gmail.com
- **Password:** coast123
- **Dashboard:** `/dashboard/authority` (limited access)

---

## Common Commands

```bash
# View Firestore data in Firebase Console
# https://console.firebase.google.com → Your Project → Firestore Database

# Create default users
python -m flask create-users

# Create sample alerts
python -m flask create-alerts

# Initialize everything
python -m flask init-db

# Run development server
python run.py

# Access Flask shell
python -m flask shell
```

---

## File Structure

```
SHELLSAFE/
├── serviceAccountKey.json         ← Place Firebase key here (NEVER commit!)
├── firebase_config.py              ✨ NEW - Firebase initialization
├── config.py                       ✏️ UPDATED - No SQLAlchemy
├── requirements.txt                ✏️ UPDATED - Firebase instead of SQLAlchemy
├── run.py                          ✏️ UPDATED - Firestore commands
├── FIREBASE_MIGRATION_GUIDE.md     ✨ NEW - Complete migration guide
├── MIGRATION_SUMMARY.md            ✨ NEW - Changes summary
├── QUICK_START.md                  ✨ NEW - This file
│
├── app/
│   ├── __init__.py                ✏️ UPDATED - Firebase setup
│   ├── models.py                  ✏️ UPDATED - Firestore models
│   ├── firestore_service.py       ✨ NEW - Firestore operations
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── routes.py              ✏️ UPDATED - Firestore auth
│   │   └── forms.py
│   ├── main/
│   │   ├── __init__.py
│   │   └── routes.py              ✏️ UPDATED - Firestore queries
│   ├── static/
│   ├── templates/
│   └── migrations/                ❌ REMOVED - Not needed
│
└── venv/                          (Virtual environment)
```

---

## Troubleshooting

### Issue: "Firebase service account key not found"
**Solution:** Ensure `serviceAccountKey.json` is in the project root directory

### Issue: "No module named 'firebase_admin'"
**Solution:** Run `pip install -r requirements.txt` again

### Issue: User creation fails silently
**Solution:** Check Firebase project exists and service account has permissions

### Issue: Firestore collections not created
**Solution:** They will be auto-created when first document is added

### Issue: Login says "Invalid email or password" 
**Solution:** Run `python -m flask create-users` to create default accounts

---

## Firestore Collections Auto-Created

When you run `python -m flask init-db`, these collections are created automatically:

- **users** - User authentication data
- **alerts** - System alerts
- **sensor_readings** - Environmental sensor data
- **devices** - IoT device information
- **bloom_risk_analysis** - Algal bloom risk scores
- **reports** - Generated monitoring reports

---

## What Changed?

### Removed ❌
- SQLite database (`app.db`)
- SQLAlchemy ORM
- Database migrations
- SQL queries

### Added ✨
- Firebase Firestore cloud database
- Firestore service layer
- Firebase configuration
- Cloud-native architecture

### Kept ✅
- All Flask routes and functionality
- User authentication and authorization
- Dashboard features
- Alert and report management
- Sensor data tracking
- Device management

---

## For Production Deployment

1. **Set Environment Variables:**
   ```bash
   FIREBASE_KEY_PATH=/secure/path/to/serviceAccountKey.json
   FLASK_ENV=production
   ```

2. **Secure Firebase Rules:**
   Set appropriate Firestore security rules in Firebase Console

3. **Update .gitignore:**
   ```
   serviceAccountKey.json
   *.db
   .env
   .env.local
   ```

4. **Enable Firestore Backups**
   - Go to Firestore Database → Backups
   - Enable automatic backups

5. **Monitor Usage:**
   - Firebase Console → Usage dashboard

---

## Support Resources

- **Firebase Docs:** https://cloud.google.com/firestore/docs
- **Flask Docs:** https://flask.palletsprojects.com
- **Flask-Login:** https://flask-login.readthedocs.io

---

**You're all set!** 🚀 ShellSafe is now running on Firebase Firestore.

For detailed information, see:
- `FIREBASE_MIGRATION_GUIDE.md` - Complete setup and API reference
- `MIGRATION_SUMMARY.md` - Detailed list of all changes
