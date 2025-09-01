# =============================================================================
# akserver - SSL and Crypto Utilities (Proprietary Edition)
# =============================================================================
"""
File:           akserver_ssl_util.py
Description:    SSL certificate generation, token signing, and crypto helpers.
Author:         AkshAy S (akserver Project)
Version:        1.0.0
License:        akserver Custom Freemium License (See LICENSE.txt)

SSL and crypto helpers that use centralized secret key & logger from akserver_config.

Third-party components used:
- cryptography (Apache 2.0): Used for X.509 certs and key generation

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""
# ------------------------------------------------------------------ Python Standard Library Imports

import os
import stat
import time
import uuid
import hmac
import datetime
import hashlib
import logging
from typing import Optional

# ------------------------------------------------------------------ Third-party

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# ------------------------------------------------------------------  Local modules

from akserver_config import get_or_create_secret_key, LOGGER as server_logger

DEVICE_ID_FILE = os.path.expanduser("~/.akserver_device_id")

def generate_self_signed_cert(
    cert_path: str,
    key_path: str,
    hostname: str = "localhost",
    logger: Optional[logging.Logger] = None,
) -> None:
    """Generates a new self-signed SSL certificate (PEM)."""
    log = logger or server_logger
    log.info(f"Generating new self-signed SSL certificate for {hostname}...")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "akserverCity"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "akserver SelfSigned"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    certificate = builder.sign(key, hashes.SHA256())
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)

    try:
        with open(cert_path, "wb") as f:
            f.write(certificate_pem)
        with open(key_path, "wb") as f:
            f.write(private_key_pem)
        log.info(f"Certificate saved to {cert_path}, key saved to {key_path}")
    except Exception as e:
        log.error(f"Failed saving certificate/key: {e}", exc_info=True)
        raise

# get or create secret key (raw bytes)
SECRET_KEY = get_or_create_secret_key()

def generate_download_token(filename: str, expires_in: int = 180) -> str:
    """Return HMAC-based token: {hex}:{expiry}"""

    expiry = int(time.time()) + expires_in
    data = f"{filename}|{expiry}"
    token = hmac.new(SECRET_KEY, data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{token}:{expiry}"

def verify_download_token(filename: str, token_string: str) -> bool:

    try:
        token, expiry_str = token_string.split(":")
        expiry = int(expiry_str)
        if time.time() > expiry:
            return False
        expected_data = f"{filename}|{expiry}"
        expected_token = hmac.new(SECRET_KEY, expected_data.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(token, expected_token)
    except Exception:
        return False

def verify_upload_token(token_string: str) -> bool:

    try:
        token, expiry_str = token_string.split(":")
        expiry = int(expiry_str)
        if time.time() > expiry:
            return False
        expected_data = f"upload_access|{expiry}"
        expected_token = hmac.new(SECRET_KEY, expected_data.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(token, expected_token)
    except (ValueError, IndexError):
        return False
    except Exception as e:
        server_logger.error(f"Token verification failed: {e}", exc_info=True)
        return False

def get_or_create_device_id() -> str:
    """Get a per-machine stable device id; persist to hidden file in user home."""

    if os.path.exists(DEVICE_ID_FILE):
        try:
            with open(DEVICE_ID_FILE, "r") as f:
                device_id = f.read().strip()
                if device_id:
                    return device_id
        except Exception:
            pass

    device_id = uuid.uuid4().hex
    try:
        with open(DEVICE_ID_FILE, "w") as f:
            f.write(device_id)
        # try to make file read only & hidden (best-effort)
        try:
            os.chmod(DEVICE_ID_FILE, stat.S_IREAD)
        except Exception:
            pass
        if os.name == "nt":
            try:
                import ctypes
                FILE_ATTRIBUTE_HIDDEN = 0x02
                ctypes.windll.kernel32.SetFileAttributesW(DEVICE_ID_FILE, FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass
    except Exception as e:
        server_logger.warning(f"[get_or_create_device_id] Warning: could not persist device id: {e}")
    return device_id

def validate_token(token_str: str, expected_filename: str) -> bool:

    try:
        token, expiry = token_str.split(":")
        expiry = int(expiry)
        if time.time() > expiry:
            return False
        data = f"{expected_filename}|{expiry}"
        expected_token = hmac.new(SECRET_KEY, data.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(token, expected_token)
    except Exception as e:
        server_logger.debug("Token validation error", exc_info=True)
        return False

def generate_upload_token(expires_in: int = 300) -> str:

    expiry = int(time.time()) + expires_in
    data = f"upload_access|{expiry}"
    token = hmac.new(SECRET_KEY, data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{token}:{expiry}"


def handle_sensitive_path_access(handler, path):
    """
    Blocks access to sensitive application files or directories.
    Returns True if request is blocked, False otherwise.
    """
    try:
        from akserver import APP_DATA_ROOT, SSL_CERT_FILE, SSL_KEY_FILE, TRUSTED_DEVICES_FILE

        potential_fs_path = handler.translate_path(path)
        abs_app_path = os.path.abspath(APP_DATA_ROOT)

        if not os.path.abspath(potential_fs_path).startswith(abs_app_path):
            return False  # outside our app scope → safe

        relative_to_app_path = os.path.relpath(potential_fs_path, abs_app_path)

        sensitive_filenames_in_app_root = [
            os.path.basename(SSL_CERT_FILE),
            os.path.basename(SSL_KEY_FILE),
            os.path.basename(TRUSTED_DEVICES_FILE),
        ]
        sensitive_dirs_relative_to_app = ["logs"]
        sensitive_extensions = [
            ".py", ".pyc", ".pyd",
            ".db", ".sqlite", ".sqlite3",
            ".env",
        ]

        path_parts = relative_to_app_path.split(os.sep)
        filename_component = path_parts[-1]

        is_sensitive = False
        if len(path_parts) > 0 and path_parts[0] in sensitive_dirs_relative_to_app:
            is_sensitive = True
        elif filename_component in sensitive_filenames_in_app_root and (
            len(path_parts) == 1 or (len(path_parts) > 1 and path_parts[0] == ".")
        ):
            is_sensitive = True
        elif any(filename_component.endswith(ext) for ext in sensitive_extensions):
            is_sensitive = True

        if is_sensitive:
            server_logger.warning(
                f"Blocked attempt to access sensitive resource: {path} "
                f"(resolved to {potential_fs_path}) from {handler.client_address[0]}"
            )
            handler.send_error(403, "Forbidden")
            return True

    except Exception as e:
        server_logger.error(f"Error in sensitive path check for {path}: {e}", exc_info=True)

    return False
