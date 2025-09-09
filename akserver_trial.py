# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Trial/license for AkServer.
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

import os, time, uuid, json, tempfile
from pathlib import Path
from typing import Optional, Dict, Any

# ------------------------------------------------------------------ Third-party

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ------------------------------------------------------------------ Local modules

from akserver_config import get_or_create_secret_key, LOGGER
from akserver_resources import db, REMOTE_DISABLED
from akserver_trial_server_token import get_server_token_status, OFFLINE_GRACE_SECONDS

# ------------------------------------------------------------------ Constants

APP_NAME = "AkServer"
APPDATA_DIR = Path(os.getenv("APPDATA", Path.home())) / APP_NAME
TRIAL_FILE = APPDATA_DIR / "trial_state.dat"
BACKUP_TRIAL_FILE = Path.home() / f".{APP_NAME}_trial_backup.dat"

TRIAL_LENGTH_DAYS = 60
MIN_UPDATE_INTERVAL = 60
REMOTE_REFRESH_INTERVAL = 7 * 24 * 3600
LOCAL_DAY_CHECK_INTERVAL = 24 * 3600

# ------------------------------------------------------------------ Functions

def _get_device_id() -> str:
    device_file = Path.home() / f".{APP_NAME}_device"
    try:
        if device_file.exists():
            return device_file.read_text().strip()
    except Exception:
        LOGGER.exception("Failed to read device id file")

    device_id = uuid.uuid4().hex
    try:
        device_file.parent.mkdir(parents=True, exist_ok=True)
        device_file.write_text(device_id)
        try:
            device_file.chmod(0o400)
        except Exception:
            pass
    except Exception:
        LOGGER.exception("Failed to write device id file")
    return device_id

DEVICE_ID = _get_device_id()

def _derive_aesgcm_key(master_key: bytes) -> bytes:
    if not isinstance(master_key, (bytes, bytearray)):
        master_key = str(master_key).encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"akserver-trial-aesgcm"
    )
    return hkdf.derive(master_key)

_raw_secret = get_or_create_secret_key()
try:
    AES_KEY = _derive_aesgcm_key(_raw_secret)
except Exception:
    LOGGER.exception("Failed to derive AES key; generating ephemeral key")
    AES_KEY = AESGCM.generate_key(bit_length=256)

def _aesgcm_encrypt(data: bytes) -> bytes:
    aesgcm = AESGCM(AES_KEY)
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, data, None)

def _aesgcm_decrypt(encrypted: bytes) -> bytes:
    if len(encrypted) < 28:
        raise ValueError("Encrypted payload too short")
    nonce, ct = encrypted[:12], encrypted[12:]
    return AESGCM(AES_KEY).decrypt(nonce, ct, None)

def _atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
        try:
            path.chmod(0o600)
        except Exception:
            pass
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass

def _save_trial(trial: dict):
    payload = json.dumps(trial, separators=(",", ":")).encode("utf-8")
    encrypted = _aesgcm_encrypt(payload)
    for path in (TRIAL_FILE, BACKUP_TRIAL_FILE):
        try:
            _atomic_write(path, encrypted)
        except Exception:
            LOGGER.warning(f"Failed to write trial file: {path}")

def _load_trial(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        raw = path.read_bytes()
        payload = _aesgcm_decrypt(raw)
        return json.loads(payload.decode("utf-8"))
    except Exception:
        LOGGER.warning(f"Failed to load trial file: {path}")
        return None

def _fetch_trial_from_firebase(device_id: str) -> Optional[Dict[str, Any]]:
    if REMOTE_DISABLED:
        return None
    try:
        doc = db.collection("trials").document(device_id).get()
        if doc.exists:
            d = doc.to_dict()
            if "expiryDate" in d:
                d["expiryDate"] = int(d["expiryDate"])
            return d
    except Exception:
        LOGGER.exception("Firebase fetch failed")
    return None

def _update_trial_in_firebase(device_id: str, trial_data: Dict[str, Any]):
    if REMOTE_DISABLED:
        return
    try:
        db.collection("trials").document(device_id).set(trial_data)
    except Exception:
        LOGGER.exception("Firebase update failed")

def _now() -> int: return int(time.time())
def _monotonic() -> float: return time.monotonic()

def _initialize_trial() -> Dict[str, Any]:
    trial = _load_trial(TRIAL_FILE) or _load_trial(BACKUP_TRIAL_FILE)
    now, mono = _now(), _monotonic()

    if trial is None:
        trial = {
            "start_date": now,
            "last_run": now,
            "device_id": DEVICE_ID,
            "trial_days": TRIAL_LENGTH_DAYS,
            "expiry_ts": now + TRIAL_LENGTH_DAYS * 86400,
            "last_remote_sync": 0,
            "last_seen_wall": now,
            "last_seen_mono": mono,
            "fresh_init": True,   # 👈 NEW
        }
        _save_trial(trial)
        LOGGER.info("Initialized new trial record")

    trial.setdefault("expiry_ts", trial.get("start_date", now) + int(trial.get("trial_days", TRIAL_LENGTH_DAYS)) * 86400)
    trial.setdefault("last_remote_sync", 0)
    trial.setdefault("last_seen_wall", now)
    trial.setdefault("last_seen_mono", mono)
    return trial

def _apply_clock_sanity(trial: Dict[str, Any], now: int, mono: float) -> Optional[Dict[str, Any]]:
    """
    Detect clock rollback or impossible jumps. If detected, mark as expired locally.
    Skip check on first init.
    """
    if trial.pop("fresh_init", False): 
        LOGGER.info("Skipping clock sanity checks (fresh init)")
        return trial

    last_wall = int(trial.get("last_seen_wall", now))
    last_mono = float(trial.get("last_seen_mono", mono))

    if now + 300 < last_wall:
        LOGGER.warning("Clock rollback detected (>5 min) — invalidating trial locally.")
        trial["expiry_ts"] = min(trial.get("expiry_ts", now), now)
        trial["last_seen_wall"] = now
        trial["last_seen_mono"] = mono
        _save_trial(trial)
        return trial

    if mono + 1e-6 < last_mono:
        LOGGER.warning("Monotonic clock anomaly — invalidating trial locally.")
        trial["expiry_ts"] = min(trial.get("expiry_ts", now), now)
        trial["last_seen_wall"] = now
        trial["last_seen_mono"] = mono
        _save_trial(trial)
        return trial

    if (now - last_wall) >= LOCAL_DAY_CHECK_INTERVAL or (mono - last_mono) >= 0.5:
        trial["last_seen_wall"] = now
        trial["last_seen_mono"] = mono

    return trial

def _maybe_weekly_remote_refresh(trial: Dict[str, Any], now: int) -> Dict[str, Any]:
    last_sync = int(trial.get("last_remote_sync", 0))
    if now - last_sync < REMOTE_REFRESH_INTERVAL:
        return trial

    firebase_trial = _fetch_trial_from_firebase(DEVICE_ID)
    trial["last_remote_sync"] = now

    if firebase_trial and "expiryDate" in firebase_trial:
        server_exp = int(firebase_trial["expiryDate"])
        if server_exp < int(trial.get("expiry_ts", server_exp)):
            trial["expiry_ts"] = server_exp
            LOGGER.info("Expiry tightened by Firebase")
    _save_trial(trial)
    return trial

def check_trial() -> Dict[str, Any]:
    now, mono = _now(), _monotonic()

    try:
        server_status = get_server_token_status(DEVICE_ID)
        if server_status.get("valid"):
            exp = int(server_status["payload"].get("exp", now))
            days_left = max((exp - now) // 86400, 0)
            return {"active": days_left > 0, "days_left": days_left, "expired": days_left == 0, "source": "server_token"}

        last_valid_at = server_status.get("last_valid_at")
        last_payload = server_status.get("payload")
        if last_valid_at and not server_status.get("valid") and (now - int(last_valid_at) <= OFFLINE_GRACE_SECONDS):
            if last_payload and last_payload.get("exp"):
                exp = int(last_payload["exp"])
                days_left = max((exp - now) // 86400, 0)
                LOGGER.info("Using offline grace with last server token")
                return {"active": days_left > 0, "days_left": days_left, "expired": days_left == 0, "source": "offline_grace"}
    except Exception:
        LOGGER.exception("Server token check failed")

    trial = _initialize_trial()
    if trial.get("device_id") != DEVICE_ID:
        LOGGER.warning("Device mismatch — trial invalid")
        return {"active": False, "days_left": 0, "expired": True, "source": "local"}

    trial = _apply_clock_sanity(trial, now, mono)
    if now >= int(trial.get("expiry_ts", now)):
        return {"active": False, "days_left": 0, "expired": True, "source": "local"}

    try:
        trial = _maybe_weekly_remote_refresh(trial, now)
    except Exception:
        LOGGER.debug("Firestore refresh skipped")

    if now - int(trial.get("last_run", now)) >= MIN_UPDATE_INTERVAL:
        trial["last_run"] = now
        try: _save_trial(trial)
        except Exception: LOGGER.debug("Failed to update last_run")

    expiry_ts = int(trial.get("expiry_ts", now))
    days_left = max((expiry_ts - now) // 86400, 0)
    return {"active": days_left > 0, "days_left": days_left, "expired": days_left == 0, "source": "local"}
