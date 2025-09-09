# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Manages and synchronizes configuration settings for akserver's GUI and server components.
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

import os, sys, json, socket, logging, base64, secrets, getpass, subprocess
from logging.handlers import RotatingFileHandler
from typing import Optional

# ------------------------------------------------------------------ App & default config

APP_NAME = "akserver"
DEFAULT_CONFIG = {
    "save_dir": os.path.join(os.path.expanduser("~"), "akserverUploads"),
    "port": 8443,
}
CONFIG = DEFAULT_CONFIG.copy()

# ------------------------------------------------------------------ Platform-specific paths (Windows-first)

if sys.platform == "win32":
    PROGRAM_DATA_PATH = os.getenv("PROGRAMDATA", r"C:\ProgramData")
    APP_DATA_ROOT = os.path.join(PROGRAM_DATA_PATH, APP_NAME, f"{APP_NAME}_Data_Server")

    USER_DATA_ROOT = os.path.join(os.path.expanduser("~"), f".{APP_NAME}")
else:
    APP_DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{APP_NAME}_Data_Server")
    USER_DATA_ROOT = os.path.join(os.path.expanduser("~"), f".{APP_NAME}")

# ------------------------------------------------------------------ Subdirectory Paths

SERVER_DATA_PATH = os.path.join(APP_DATA_ROOT, "Server")
LOG_DIR = os.path.join(SERVER_DATA_PATH, "logs")
CONFIG_FILE = os.path.join(SERVER_DATA_PATH, f"{APP_NAME}_config.json")
SSL_CERT_FILE = os.path.join(SERVER_DATA_PATH, "server_cert.pem")
SSL_KEY_FILE = os.path.join(SERVER_DATA_PATH, "server_key.pem")
TRUSTED_DEVICES_FILE = os.path.join(SERVER_DATA_PATH, "trusted_devices.json")
DEFAULT_SAVE_DIR = DEFAULT_CONFIG["save_dir"]

# ------------------------------------------------------------------ Secret file names/paths
_SECRET_FILENAME = "secret.key"
_SECRET_FILE_PATH = os.path.join(SERVER_DATA_PATH, _SECRET_FILENAME)
ENV_SECRET_NAME = "akserver_SECRET_KEY"
_SECRET_BYTE_LEN = 32 

# ------------------------------------------------------------------ Utility helpers for directories / file I/O / encoding

def _ensure_parent_dir(path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass

def _write_secret_file_atomic(path: str, b64_secret: str) -> None:
    """
    Best-effort atomic write + Windows hiding + basic ACL via icacls (best-effort).
    If Windows, we try to hide the file and restrict permissions to current user only.
    """
    _ensure_parent_dir(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(b64_secret)
    os.replace(tmp, path)

    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
        elif os.name == "nt":
            try:
                import ctypes
                FILE_ATTRIBUTE_HIDDEN = 0x02
                ctypes.windll.kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass

            try:
                username = getpass.getuser()
                subprocess.run(["icacls", path, "/inheritance:r"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["icacls", path, "/grant", f"{username}:(R,W)"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
    except Exception:
        pass

def _read_secret_file(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read().strip()
            return data or None
    except Exception:
        return None

def _encode_secret(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _decode_secret(b64_text: str) -> bytes:
    padding = "=" * ((4 - (len(b64_text) % 4)) % 4)
    return base64.urlsafe_b64decode(b64_text + padding)

# ------------------------------------------------------------------ Logging factory (centralized)

def setup_logger(app_name: str = APP_NAME, log_dir: str = LOG_DIR, log_file: str = "server.log") -> logging.Logger:
    """Create and return a centralized production-grade logger."""
    logger = logging.getLogger(app_name)
    logger.setLevel(logging.DEBUG) 

    if not logger.handlers:
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            pass

        file_handler = RotatingFileHandler(os.path.join(log_dir, log_file), maxBytes=5*1024*1024, backupCount=5)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False

    return logger

# ------------------------------------------------------------------ create LOGGER early so other helpers can use it

LOGGER = setup_logger()

# ------------------------------------------------------------------ Secret key management API (exposed)

def get_or_create_secret_key() -> bytes:
    """
    Resolution order:
      1) Environment variable akserver_SECRET_KEY (base64 urlsafe or hex or raw string).
      2) Secret file in SERVER_DATA_PATH/secret.key
      3) Generate, persist, return new secret.
    Returns: raw bytes key (suitable for HMAC usage).
    """

    env = os.environ.get(ENV_SECRET_NAME)
    if env:
        try:
            return _decode_secret(env)
        except Exception:
            try:
                return bytes.fromhex(env)
            except Exception:
                return env.encode("utf-8")

    file_val = _read_secret_file(_SECRET_FILE_PATH)
    if file_val:
        try:
            return _decode_secret(file_val)
        except Exception:
            try:
                return bytes.fromhex(file_val)
            except Exception:
                return file_val.encode("utf-8")


    raw = secrets.token_bytes(_SECRET_BYTE_LEN)
    encoded = _encode_secret(raw)
    try:
        _write_secret_file_atomic(_SECRET_FILE_PATH, encoded)
        LOGGER.info("Generated and persisted new secret key (file created).")
    except Exception as e:

        fallback = os.path.join(os.path.expanduser("~"), f".{_SECRET_FILENAME}")
        try:
            _write_secret_file_atomic(fallback, encoded)
            LOGGER.warning(f"Persisting secret to default path failed; saved fallback at {fallback}: {e}")
        except Exception:
            LOGGER.error("Failed to persist secret key to disk; proceeding with in-memory secret.")
            sys.stderr.write("Warning: akserver secret could not be persisted to disk.\n")
    return raw

def rotate_secret_key(new_raw: Optional[bytes] = None) -> bytes:
    """Rotate secret (admin-only). Returns new raw key bytes."""
    raw = new_raw if new_raw is not None else secrets.token_bytes(_SECRET_BYTE_LEN)
    encoded = _encode_secret(raw)
    _write_secret_file_atomic(_SECRET_FILE_PATH, encoded)
    LOGGER.info("Secret key rotated by administrator.")
    return raw

# ------------------------------------------------------------------ Config file helpers and save/load

def ensure_dir_exists(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        LOGGER.error(f"[FATAL] Could not create directory {path}: {e}")

def load_config() -> None:
    global CONFIG
    try:
        ensure_dir_exists(os.path.dirname(CONFIG_FILE))
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            CONFIG.update({k: file_config.get(k, CONFIG[k]) for k in DEFAULT_CONFIG})
        else:
            save_config()
    except Exception as e:
        LOGGER.error(f"Error loading config: {e}. Using default settings.")
        CONFIG = DEFAULT_CONFIG.copy()
        save_config()

def save_config(new_config_dict: dict | None = None) -> None:
    global CONFIG
    if new_config_dict:
        CONFIG.update(new_config_dict)
    try:
        ensure_dir_exists(os.path.dirname(CONFIG_FILE))
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        LOGGER.error(f"Error saving config: {e}")

# ------------------------------------------------------------------ Port resolution helper

def get_available_port(preferred_port: int = 8443, host: str = "127.0.0.1") -> int:
    """Try preferred port; otherwise return an OS-assigned free port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, preferred_port))
            return preferred_port
    except OSError:

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, 0))
            return s.getsockname()[1]

# ------------------------------------------------------------------ Resolve PORT dynamically at import time

load_config()
PORT = get_available_port(CONFIG.get("port", 8443))
CONFIG["port"] = PORT
