# Deploy ShellSafe to Vercel

Vercel runs this Flask app as a Python Function. Firestore and Realtime Database
remain the persistent data stores; do not depend on local files or background
threads for persistence or continuous work.

## 1. Keep credentials out of Git

- Never commit `serviceAccountKey.json` or the firmware's `secrets.h`.
- The firmware now includes `secrets.h`. Copy `secrets.h.example` to `secrets.h`,
  replace its placeholders with your Wi-Fi, newly rotated Firebase token, and
  alert phone number, then upload the sketch to your board.
- Credentials that were previously present in the firmware should be rotated
  before you publish or reconnect the device.

## 2. Configure Firebase

In Firebase, enable Firestore and Realtime Database, and create a service
account with only the permissions the app needs. In **Vercel → Project →
Settings → Environment Variables**, set:

| Variable | Value |
| --- | --- |
| `SECRET_KEY` | A new, random value used to sign Flask sessions |
| `FIREBASE_CREDENTIALS_JSON` | The complete JSON contents of the Firebase service account key |
| `FIREBASE_DATABASE_URL` | Your Firebase Realtime Database URL |

Add these variables to Production and Preview only as appropriate. Do not put
the service-account JSON in GitHub, source files, or a public Vercel variable.
If the Firebase key was ever exposed, revoke it and create a replacement before
deploying.

To generate a session key locally, run:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 3. Deploy from GitHub

1. Push the project to a GitHub repository without local secrets.
2. In Vercel, choose **Add New → Project** and import that repository.
3. Keep the project root at the repository root. `pyproject.toml` directs Vercel
   to `index.py`'s Flask app, and Vercel installs `requirements.txt`.
4. Add the environment variables above and deploy.
5. Visit the deployment URL and verify login, dashboards, Firestore reads, and
   live sensor data.

## Runtime limitations

- The sensor sampler is disabled on Vercel because Functions cannot provide a
  durable always-running worker. Live values are read when requests arrive.
- Vercel Functions are short-lived and may be reused inconsistently. Any
  in-memory sensor history/cache is temporary; use Firebase for durable history.
- If you need continuous alert processing while nobody is viewing the site,
  run that worker on an always-on service or a scheduled/queued worker rather
  than relying on the Flask web Function.

## Initial user accounts

Create initial users from a trusted local environment with Firebase credentials
configured. Set `FLASK_APP` to `index.py`, and set `ADMIN_EMAIL`,
`ADMIN_PASSWORD`, `AUTHORITY_EMAIL`, and `AUTHORITY_PASSWORD` to unique, strong
values before running:

```powershell
$env:FLASK_APP = "index.py"
python -m flask create-users
```

The command does not change passwords on accounts that already exist. If you
previously initialized the documented demo accounts, change those passwords in
the existing accounts before making the deployment public.
