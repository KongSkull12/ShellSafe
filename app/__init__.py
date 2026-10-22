from flask import Flask
from flask_login import LoginManager
import sys
import os

# Add parent directory to path to import firebase_config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

login_manager = LoginManager()
login_manager.login_view = 'auth.login'

def create_app(config_class=None):
    app = Flask(__name__)
    
    if config_class:
        app.config.from_object(config_class)
    else:
        secret_key = os.environ.get('SECRET_KEY')
        if os.environ.get('VERCEL') == '1' and not secret_key:
            raise RuntimeError('Set SECRET_KEY in the Vercel project environment.')
        app.config['SECRET_KEY'] = secret_key or 'you-will-never-guess'
        if os.environ.get('VERCEL') == '1':
            app.config.update(
                SESSION_COOKIE_SECURE=True,
                SESSION_COOKIE_HTTPONLY=True,
                SESSION_COOKIE_SAMESITE='Lax',
            )
    
    login_manager.init_app(app)
    
    # Initialize Firebase and Firestore on app startup
    with app.app_context():
        try:
            from firebase_config import initialize_firebase
            from app.firestore_service import get_firestore_service
            initialize_firebase()
            get_firestore_service()
        except Exception as e:
            if os.environ.get('VERCEL') == '1':
                raise
            app.logger.warning(f"Firebase initialization: {str(e)}")
    
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    @app.before_request
    def _start_sensor_sampler():
        # Started on the first request so the debug reloader's parent process
        # (which never serves) does not poll Firebase too.
        # Vercel functions are short-lived and must not own a background worker.
        if os.environ.get('VERCEL') == '1' or os.environ.get('SENSOR_SAMPLER', '1') == '0':
            return
        from app.realtime_db_service import start_sensor_sampler
        from app.risk_service import assess_bloom_risk
        from app.live_alert_sync import sync_live_alerts

        def on_sample(reading):
            if reading and reading.get('is_online'):
                sync_live_alerts(reading, assess_bloom_risk(reading))

        start_sensor_sampler(on_sample=on_sample)

    @app.context_processor
    def inject_unread_alert_count():
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {'unread_alert_count': 0}
        try:
            from app.firestore_service import get_firestore_service
            count = get_firestore_service().get_unread_alert_count()
        except Exception:
            count = 0
        return {'unread_alert_count': count}

    @app.context_processor
    def inject_shell_live():
        # Every logged-in page paints the hull stripe from real state on first
        # render; pages that already built a payload pass their own `live`.
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {}
        try:
            from app.sensor_view import build_live_payload
            return {'shell_live': build_live_payload()}
        except Exception:
            return {'shell_live': None}

    return app
