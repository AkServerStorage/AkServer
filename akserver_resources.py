# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Handles secure Firebase initialization and Firestore client setup.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025-present. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""
import os
import json
import sys
import firebase_admin
from firebase_admin import credentials, firestore
from cryptography.fernet import Fernet

APP_DIR = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
REMOTE_DISABLED = False

RESOURCE_FILE = os.path.join(APP_DIR,"_internal", "system_patch.pkg") 
#RESOURCE_FILE = os.path.join(APP_DIR, "system_patch.pkg")

KEY_PARTS = [
    "e2X4rrTZ", "i8eakDMG", "eMFkkMCp", "PYBNHWf3", "5eKynetc", "Zqg="
]
RESOURCE_TOKEN = ("".join(KEY_PARTS)).encode()
fernet = Fernet(RESOURCE_TOKEN)

try:
    with open(RESOURCE_FILE, "rb") as f:
        encrypted_data = f.read()
    decrypted_json = fernet.decrypt(encrypted_data)
    cred_dict = json.loads(decrypted_json)
except FileNotFoundError:
    raise FileNotFoundError(f"Could not find {RESOURCE_FILE}")
except json.JSONDecodeError:
    raise ValueError("Failed to parse decrypted JSON credentials")
except fernet.InvalidToken:
    raise ValueError("Invalid decryption token for system_patch.pkg")

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()