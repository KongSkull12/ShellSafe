"""
Firebase Configuration Module
Initializes Firebase Admin SDK with Firestore and Realtime Database.
"""

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os

# Path to your Firebase service account JSON key
SERVICE_ACCOUNT_KEY_PATH = os.environ.get('FIREBASE_KEY_PATH') or os.path.join(
    os.path.dirname(__file__), 'serviceAccountKey.json'
)

DATABASE_URL = os.environ.get(
    'FIREBASE_DATABASE_URL',
    'https://shellsafe-ac058-default-rtdb.firebaseio.com'
)

_db_instance = None

def initialize_firebase():
    """
    Initialize Firebase Admin SDK and return Firestore client.
    
    Returns:
        firestore.client(): Firestore database client
    """
    global _db_instance
    
    try:
        # Check if Firebase has already been initialized
        if not firebase_admin._apps:
            # Initialize Firebase with service account credentials
            if not os.path.exists(SERVICE_ACCOUNT_KEY_PATH):
                raise FileNotFoundError(
                    f"Firebase service account key not found at {SERVICE_ACCOUNT_KEY_PATH}. "
                    "Please place your 'serviceAccountKey.json' file in the project root."
                )
            
            cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
            firebase_admin.initialize_app(cred, {
                'databaseURL': DATABASE_URL,
            })
        
        # Get Firestore client
        if _db_instance is None:
            _db_instance = firestore.client()
        
        return _db_instance
    except FileNotFoundError as e:
        raise FileNotFoundError(str(e))
    except Exception as e:
        raise Exception(f"Failed to initialize Firebase: {str(e)}")


def get_firestore_client():
    """
    Get Firestore client instance.
    
    Returns:
        firestore.client(): Firestore database client
    """
    return initialize_firebase()


# Try to initialize on module import, but don't fail if it can't
db = None
try:
    db = initialize_firebase()
except Exception as e:
    print(f"Warning: Firebase not initialized. Error: {str(e)}")
    db = None
