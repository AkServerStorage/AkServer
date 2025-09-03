# akserver_trial_server_token.py
"""
Client-side helper: securely store & verify server-issued RS256 JWTs for trial/license.
- Uses Windows DPAPI (win32crypt) when available to protect at-rest file.
- Falls back to 'keyring' if DPAPI isn't available.
- Stores metadata (last_valid_payload) for offline-grace decisions.
"""

import os
import json
import time
import base64
from pathlib import Path
from typing import Optional, Dict, Any

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature

# Paths (adjust per your app layout)
APP_NAME = "AkServer"
APPDATA_DIR = Path(os.getenv("APPDATA", Path.home())) / APP_NAME
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
SERVER_TOKEN_FILE = APPDATA_DIR / "server_token.dat"       # encrypted token bytes
SERVER_TOKEN_META = APPDATA_DIR / "server_token_meta.json" # metadata (json)

# Replace this with the real PUBLIC key PEM (RS256) generated from your server's private key.
# DO NOT PUT PRIVATE KEY HERE. Keep the public key only.
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
REPLACE_WITH_YOUR_PUBLIC_KEY_PEM
-----END PUBLIC KEY-----"""

# Offline grace (seconds) -- allow users to stay active for this long after last valid server token
OFFLINE_GRACE_SECONDS = 72 * 3600  # 72 hours

# Try to import Windows DPAPI (win32crypt). If not available, fall back to keyring.
_HAS_DPAPI = False
try:
    import win32crypt  # pywin32
    _HAS_DPAPI = True
except Exception:
    _HAS_DPAPI = False

# try keyring fallback
_HAS_KEYRING = False
try:
    import keyring
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False


# ------------------------ Utilities ------------------------
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


# ------------------------ Secure storage ------------------------
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
            # Fallback: store token in the OS keyring
            keyring.set_password(APP_NAME, "server_token", token_str)
            # write a tiny sentinel file so we can check metadata using file mtime
            SERVER_TOKEN_FILE.write_text("keyring")  # not sensitive
        else:
            # Last resort: write file with restrictive perms (still not ideal)
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
        # Best-effort: do not raise (client must continue to function)
        try:
            # attempt an insecure write as last resort
            SERVER_TOKEN_FILE.write_text(token_str)
            SERVER_TOKEN_META.write_text(json.dumps({"stored_at": int(time.time()), "payload": None}))
        except Exception:
            pass
        return False


def secure_load_token() -> Optional[str]:
    """
    Load token from secure location and return raw JWT string or None.
    Decrypts DPAPI blob or reads keyring/file fallback.
    """
    try:
        if _HAS_DPAPI and SERVER_TOKEN_FILE.exists():
            data = SERVER_TOKEN_FILE.read_bytes()
            decrypted = win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]
            return decrypted.decode("utf-8")
        elif _HAS_KEYRING:
            # try keyring first
            val = keyring.get_password(APP_NAME, "server_token")
            if val:
                return val
            # fallback to file sentinel
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


# ------------------------ JWT verification ------------------------
def _verify_jwt_signature_and_get_payload(jwt_token: str) -> Optional[Dict[str, Any]]:
    """
    Verify RS256 signature of a JWT and return payload (dict) if valid.
    Does NOT validate claims beyond signature (caller validates exp/device_id etc).
    """
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
        # Public key invalid / not set
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

    # If signature ok, parse payload
    return _parse_jwt_payload(jwt_token)


# ------------------------ Public API ------------------------
def load_and_verify_server_token() -> Optional[Dict[str, Any]]:
    """
    Load, verify, and return payload dict on success.
    Returns None if missing/invalid.
    """
    token = secure_load_token()
    if not token:
        return None
    payload = _verify_jwt_signature_and_get_payload(token)
    return payload


def get_server_token_status(device_id_expected: str) -> Dict[str, Any]:
    """
    Returns dict:
      {
        "valid": bool,
        "payload": dict or None,
        "reason": str,
        "last_valid_at": ts or None
      }
    """
    meta = _read_meta()
    last_valid_at = meta.get("stored_at")
    payload = load_and_verify_server_token()
    if payload is None:
        # If no payload, check meta last_valid payload for offline grace
        saved_payload = meta.get("payload")
        if saved_payload:
            # meta may hold last known-good payload even if token file got corrupted
            # do not treat as fully valid; caller can use last_valid_at to grant grace
            return {"valid": False, "payload": saved_payload, "reason": "token_file_invalid", "last_valid_at": last_valid_at}
        return {"valid": False, "payload": None, "reason": "missing_or_invalid", "last_valid_at": last_valid_at}

    # payload exists -- check expiry and device_id
    now = int(time.time())
    exp = payload.get("exp")
    if exp is not None and now > int(exp):
        return {"valid": False, "payload": payload, "reason": "expired", "last_valid_at": last_valid_at}

    if payload.get("device_id") != device_id_expected:
        return {"valid": False, "payload": payload, "reason": "device_mismatch", "last_valid_at": last_valid_at}

    # fully valid
    return {"valid": True, "payload": payload, "reason": "ok", "last_valid_at": last_valid_at}


def store_server_token_from_server_response(token_str: str) -> bool:
    """
    Convenience: store token returned from the server after purchase/issuance
    and write metadata. Returns True on success.
    """
    payload = _verify_jwt_signature_and_get_payload(token_str)
    if payload is None:
        return False
    return secure_store_token(token_str)
