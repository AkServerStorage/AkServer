# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Client-side helper: securely store & verify server trial/license.
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

import os, json, time, base64
from pathlib import Path
from typing import Optional, Dict, Any

# ------------------------------------------------------------------ Third-party

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature

# ------------------------------------------------------------------ Subdirectory Paths

APP_NAME = "AkServer"
APPDATA_DIR = Path(os.getenv("APPDATA", Path.home())) / APP_NAME
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
SERVER_TOKEN_FILE = APPDATA_DIR / "server_token.dat"
SERVER_TOKEN_META = APPDATA_DIR / "server_token_meta.json" 

PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
REPLACE_WITH_YOUR_PUBLIC_KEY_PEM
-----END PUBLIC KEY-----"""

OFFLINE_GRACE_SECONDS = 72 * 3600 

_HAS_DPAPI = False
try:
    import win32crypt 
    _HAS_DPAPI = True
except Exception:
    _HAS_DPAPI = False

_HAS_KEYRING = False
try:
    import keyring
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False

# ------------------------------------------------------------------ Functions

def _b64url_decode_no_padding(s: str) -> bytes:
    """Decode base64url with missing padding handled."""
    s = s.encode("utf-8")
    rem = len(s) % 4
    if rem:
        s += b"=" * (4 - rem)
    return base64.urlsafe_b64decode(s)


def _parse_jwt_payload(jwt_token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = jwt_token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        payload_json = _b64url_decode_no_padding(payload_b64).decode("utf-8")
        return json.loads(payload_json)
    except Exception:
        return None

def secure_store_token(token_str: str) -> bool:
    """
    Securely store token. On Windows uses DPAPI to encrypt bytes to SERVER_TOKEN_FILE.
    Also writes metadata (payload and stored_at) to SERVER_TOKEN_META.
    Returns True on success.
    """
    try:
        token_bytes = token_str.encode("utf-8")
        if _HAS_DPAPI:
            protected = win32crypt.CryptProtectData(token_bytes, "akserver_token", None, None, None, 0)
            SERVER_TOKEN_FILE.write_bytes(protected)
        elif _HAS_KEYRING:
            keyring.set_password(APP_NAME, "server_token", token_str)
            SERVER_TOKEN_FILE.write_text("keyring") 
        else:
            SERVER_TOKEN_FILE.write_text(token_str)
            os.chmod(SERVER_TOKEN_FILE, 0o600)

        payload = _parse_jwt_payload(token_str)
        meta = {
            "stored_at": int(time.time()),
            "payload": payload
        }
        SERVER_TOKEN_META.write_text(json.dumps(meta))
        return True
    except Exception as e:
        try:
            SERVER_TOKEN_FILE.write_text(token_str)
            SERVER_TOKEN_META.write_text(json.dumps({"stored_at": int(time.time()), "payload": None}))
        except Exception:
            pass
        return False


def secure_load_token() -> Optional[str]:
    try:
        if _HAS_DPAPI and SERVER_TOKEN_FILE.exists():
            data = SERVER_TOKEN_FILE.read_bytes()
            decrypted = win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]
            return decrypted.decode("utf-8")
        elif _HAS_KEYRING:
            val = keyring.get_password(APP_NAME, "server_token")
            if val:
                return val
            if SERVER_TOKEN_FILE.exists():
                content = SERVER_TOKEN_FILE.read_text().strip()
                if content == "keyring":
                    return val
                return content
        elif SERVER_TOKEN_FILE.exists():
            return SERVER_TOKEN_FILE.read_text()
        return None
    except Exception:
        return None

def _read_meta() -> Dict[str, Any]:
    try:
        if SERVER_TOKEN_META.exists():
            return json.loads(SERVER_TOKEN_META.read_text())
    except Exception:
        pass
    return {}

def _verify_jwt_signature_and_get_payload(jwt_token: str) -> Optional[Dict[str, Any]]:
    try:
        header_b64, payload_b64, sig_b64 = jwt_token.split(".")
    except Exception:
        return None

    signing_input = (header_b64 + "." + payload_b64).encode("utf-8")
    try:
        signature = _b64url_decode_no_padding(sig_b64)
    except Exception:
        return None

    try:
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
    except Exception:
        return None

    try:
        public_key.verify(
            signature,
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
    except InvalidSignature:
        return None
    except Exception:
        return None
    return _parse_jwt_payload(jwt_token)


# ------------------------ Public API ------------------------
def load_and_verify_server_token() -> Optional[Dict[str, Any]]:
    token = secure_load_token()
    if not token:
        return None
    payload = _verify_jwt_signature_and_get_payload(token)
    return payload


def get_server_token_status(device_id_expected: str) -> Dict[str, Any]:
    meta = _read_meta()
    last_valid_at = meta.get("stored_at")
    payload = load_and_verify_server_token()
    if payload is None:
        saved_payload = meta.get("payload")
        if saved_payload:
            return {"valid": False, "payload": saved_payload, "reason": "token_file_invalid", "last_valid_at": last_valid_at}
        return {"valid": False, "payload": None, "reason": "missing_or_invalid", "last_valid_at": last_valid_at}

    now = int(time.time())
    exp = payload.get("exp")
    if exp is not None and now > int(exp):
        return {"valid": False, "payload": payload, "reason": "expired", "last_valid_at": last_valid_at}

    if payload.get("device_id") != device_id_expected:
        return {"valid": False, "payload": payload, "reason": "device_mismatch", "last_valid_at": last_valid_at}

    return {"valid": True, "payload": payload, "reason": "ok", "last_valid_at": last_valid_at}


def store_server_token_from_server_response(token_str: str) -> bool:
    payload = _verify_jwt_signature_and_get_payload(token_str)
    if payload is None:
        return False
    return secure_store_token(token_str)
