# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Handles secure Firebase initialization and Firestore client setup.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025 AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Python Standard library

import os

# ------------------------------------------------------------------ Third-party

import firebase_admin
from firebase_admin import credentials, firestore
from cryptography.fernet import Fernet

# ------------------------------------------------------------------ Subdirectory Paths

APP_DIR = os.path.dirname(__file__)
REMOTE_DISABLED = False
RESOURCE_FILE = os.path.join(APP_DIR, "system_patch.pkg")

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

with open(RESOURCE_FILE, "rb") as f:
    encrypted_data = f.read()

decrypted_json = fernet.decrypt(encrypted_data)

tmp_json_path = os.path.join(APP_DIR, "resource_temp.dat")
with open(tmp_json_path, "wb") as f:
    f.write(decrypted_json)

if not firebase_admin._apps:
    cred = credentials.Certificate(tmp_json_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

try:
    os.remove(tmp_json_path)
except Exception:
    pass
