# ShellSafe

IoT shellfish / aquaculture monitoring system: ESP32 firmware (`shellsafe.ino`), Flask web dashboard, and Firebase (Firestore + Realtime Database).

## Setup

1. Copy your Firebase service account JSON to the project root as `serviceAccountKey.json` (not committed; see `.gitignore`).
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Run the app: `python run.py`

See `QUICK_START.md` and `FIREBASE_MIGRATION_GUIDE.md` for more detail.

## Hardware

Flash `shellsafe.ino` to your ESP32 and configure WiFi / Firebase in the sketch before deploying.
