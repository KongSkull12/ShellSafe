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
        # Default config
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    
    login_manager.init_app(app)
    
    # Initialize Firebase and Firestore on app startup
    with app.app_context():
        try:
            from firebase_config import initialize_firebase
            from app.firestore_service import get_firestore_service
            initialize_firebase()
            get_firestore_service()
        except Exception as e:
            app.logger.warning(f"Firebase initialization: {str(e)}")
    
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

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

    return app

