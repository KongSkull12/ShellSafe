# ShellSafe

IoT shellfish / aquaculture monitoring system: Flask web dashboard and Firebase (Firestore + Realtime Database).

## Local setup

1. Copy your Firebase service account JSON to the project root as `serviceAccountKey.json` (not committed; see `.gitignore`).
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Run the app: `python app.py`

See `QUICK_START.md` and `FIREBASE_MIGRATION_GUIDE.md` for more detail.

Initial accounts must be created with unique credentials supplied through
environment variables; see `VERCEL_DEPLOYMENT.md`. Do not use shared or
published demo passwords.

## Deploy to Vercel

See [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md) for the GitHub import steps,
required Firebase/Vercel environment variables, and serverless runtime
limitations.
