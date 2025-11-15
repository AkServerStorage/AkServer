# =============================================================================
# AkServer –  Software Module
# =============================================================================

"""
Description:    Handles secure Firebase initialization and Firestore client setup.
Author:         Akshay Shinde
Version:        1.0.0
License:        MIT License - See LICENSE file in the project root
                https://github.com/AkServerStorage/AkServer/blob/main/LICENSE

Copyright © 2025 Akshay Shinde. Open Source.

Permission is hereby granted to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of this software.

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
RESOURCE_FILE = os.path.join(APP_DIR, "system_patch.pkg") #deleting while creating executable

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