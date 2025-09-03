# =============================================================================
# akserver_resources.py (Production Ready)
# =============================================================================
"""
Handles secure Firebase initialization and Firestore client setup.
Firebase credentials are stored encrypted in `system_patch.pkg`.
"""

import os
import firebase_admin
from firebase_admin import credentials, firestore
from cryptography.fernet import Fernet

APP_DIR = os.path.dirname(__file__)

# Toggle remote Firebase access (set True to disable in future if needed)
REMOTE_DISABLED = False

# Encrypted resource file (service account JSON)
RESOURCE_FILE = os.path.join(APP_DIR, "system_patch.pkg")

# Secret key (split into parts for obscurity)
KEY_PARTS = [
    "e2X4rrTZ",
    "i8eakDMG",
    "eMFkkMCp",
    "PYBNHWf3",
    "5eKynetc",
    "Zqg=",
]
RESOURCE_TOKEN = ("".join(KEY_PARTS)).encode()
fernet = Fernet(RESOURCE_TOKEN)

# Load and decrypt the Firebase service account
with open(RESOURCE_FILE, "rb") as f:
    encrypted_data = f.read()

decrypted_json = fernet.decrypt(encrypted_data)

# Write decrypted JSON to temp file (auto-removed after init)
tmp_json_path = os.path.join(APP_DIR, "resource_temp.dat")
with open(tmp_json_path, "wb") as f:
    f.write(decrypted_json)

# Initialize Firebase Admin SDK
if not firebase_admin._apps:
    cred = credentials.Certificate(tmp_json_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Cleanup temp file
try:
    os.remove(tmp_json_path)
except Exception:
    pass
