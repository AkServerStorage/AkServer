import secrets
import random # For OTP generation
import time
import logging
from http.cookies import SimpleCookie # For type hinting and potential direct use

# Forward declaration for type hinting AkServer_trusted_device_manager
if False: # TYPE_CHECKING
    from typing import TYPE_CHECKING
    import AkServer_trusted_device_manager as tdm_module

# --- Constants ---
OTP_VALIDITY_DURATION = 300  # 5 minutes
SESSION_VALIDITY_DURATION = 3600  # 1 hour for IP based sessions
DEVICE_TOKEN_COOKIE_NAME = "AkServer_device_token"
DEVICE_TOKEN_VALIDITY_SECONDS = 30 * 24 * 60 * 60  # 30 days

# --- Module State (In-memory, lost on server restart) ---
_current_otp = None
_otp_generation_time = 0

# Dictionaries to store session states, keyed by client_ip
_pending_device_registration = {} # IPs that passed OTP, awaiting device name
_authenticated_sessions = {}    # IPs that are fully authenticated

# Logger instance, injected by the main server via init_auth_module
_logger = None

def init_auth_module(logger_instance: logging.Logger):
    global _logger
    _logger = logger_instance
    if _logger:
        _logger.info("Authentication module initialized.")

def _log(level, message, exc_info=False): # sourcery skip: instance-method-first-arg-name
    if _logger:
        _logger.log(level, f"[Auth] {message}", exc_info=exc_info)
    else:
        print(f"[Auth Fallback] {logging.getLevelName(level)}: {message}")


def generate_device_token() -> str:
    """Generate a secure random token for device identification."""
    return secrets.token_hex(32)

def _generate_numeric_otp() -> str:
    """Generate a 6-digit numeric OTP as a string."""
    return "{:06d}".format(random.randint(0, 999999))

def request_new_otp() -> str | None:
    """
    Generates a new OTP, stores its generation time.
    Returns the OTP for display/logging by the caller.
    """
    global _current_otp, _otp_generation_time
    _current_otp = _generate_numeric_otp()
    _otp_generation_time = time.time()
    _log(logging.INFO, f"New OTP generated: {_current_otp}")
    return _current_otp

def verify_otp_and_mark_pending(submitted_otp: str, client_ip: str) -> tuple[bool, str]:
    """
    Verifies the submitted OTP. If valid, marks the client_ip as pending device registration.
    Returns (success_status, message).
    """
    global _pending_device_registration
    if _current_otp and submitted_otp == _current_otp:
        if (time.time() - _otp_generation_time) < OTP_VALIDITY_DURATION:
            _pending_device_registration[client_ip] = {"otp_verified_time": time.time()}
            _log(logging.INFO, f"OTP verified for {client_ip}. Awaiting device name.")
            return True, "OTP verified. Please register your device."
        else:
            _log(logging.WARNING, f"OTP expired. Attempt by {client_ip}")
            return False, "OTP expired. Please request a new one."
    _log(logging.WARNING, f"Invalid OTP '{submitted_otp}' attempt by {client_ip}")
    return False, "Invalid OTP."

def is_client_pending_registration(client_ip: str) -> bool:
    """Checks if a client IP is in the pending registration state and hasn't timed out."""
    if client_ip in _pending_device_registration:
        # Timeout for pending registration (e.g., 5 minutes after OTP verification)
        if time.time() - _pending_device_registration[client_ip]["otp_verified_time"] > 300:
            del _pending_device_registration[client_ip]
            _log(logging.INFO, f"Pending registration for {client_ip} timed out.")
            return False
        return True
    return False

def complete_device_registration(client_ip: str, device_name: str,
                                 trusted_devices_manager: 'tdm_module', # type: ignore
                                 trusted_devices_file_path: str
                                 ) -> str | None:
    """
    Completes device registration. Adds to trusted list, creates session, returns new token.
    Returns None if client_ip not pending.
    """
    global _authenticated_sessions, _pending_device_registration
    if not is_client_pending_registration(client_ip): # Uses the timeout logic within
        return None

    new_device_token = generate_device_token()
    # The logger passed to add_trusted_device should be the main server_logger
    trusted_devices_manager.add_trusted_device(
        new_device_token, device_name, client_ip, trusted_devices_file_path, _logger
    )
    
    _authenticated_sessions[client_ip] = {
        "last_seen": time.time(),
        "name": device_name,
        "source": "otp_registration"
    }
    _log(logging.INFO, f"Device '{device_name}' registered for {client_ip} with token ...{new_device_token[-6:]}.")
    
    if client_ip in _pending_device_registration: # Should be true, but good to check
        del _pending_device_registration[client_ip]
    
    return new_device_token

def check_authentication(
    cookie_header_value: str | None,
    client_ip: str,
    trusted_devices_manager: 'tdm_module' # type: ignore
) -> tuple[bool, str | None]:
    """
    Checks auth via device token cookie or active IP session. Updates last_seen.
    Returns (is_authenticated, device_name_for_logs).
    """
    global _authenticated_sessions
    if cookie_header_value:
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header_value)
            if DEVICE_TOKEN_COOKIE_NAME in cookie:
                device_token = cookie[DEVICE_TOKEN_COOKIE_NAME].value
                if trusted_devices_manager.is_device_trusted(device_token):
                    dev_details = next((d for d in trusted_devices_manager.get_trusted_devices_list() if d["token"] == device_token), None)
                    dev_name = dev_details.get("name", f"Device ...{device_token[-6:]}") if dev_details else f"Token ...{device_token[-6:]}"
                    
                    _authenticated_sessions[client_ip] = {"last_seen": time.time(), "name": dev_name, "source": "device_token"}
                    _log(logging.INFO, f"Authenticated via device token from {client_ip} (Device: '{dev_name}', Token: ...{device_token[-6:]})")
                    return True, dev_name
        except Exception as e:
            _log(logging.WARNING, f"Error parsing cookie for device token from {client_ip}: {e}", exc_info=True)

    if client_ip in _authenticated_sessions:
        session_data = _authenticated_sessions[client_ip]
        if time.time() - session_data.get("last_seen", 0) < SESSION_VALIDITY_DURATION:
            session_data["last_seen"] = time.time()
            dev_name = session_data.get("name", client_ip)
            _log(logging.DEBUG, f"Authenticated via active IP session for {client_ip} (Name: {dev_name})")
            return True, dev_name
        else:
            del _authenticated_sessions[client_ip]
            _log(logging.INFO, f"IP Session expired for {client_ip} (Name: {session_data.get('name', 'N/A')})")
            
    _log(logging.DEBUG, f"Authentication check failed for {client_ip}")
    return False, None

def logout_client_session(client_ip: str):
    """Clears a client's IP-based session."""
    global _authenticated_sessions
    if client_ip in _authenticated_sessions:
        session_name = _authenticated_sessions[client_ip].get("name", "N/A")
        del _authenticated_sessions[client_ip]
        _log(logging.INFO, f"User {client_ip} (Name: {session_name}) logged out. IP session cleared.")

def get_active_sessions_info() -> list:
    """Returns details of active sessions, cleaning up expired ones."""
    global _authenticated_sessions
    active_info = []
    now = time.time()
    for ip, data in list(_authenticated_sessions.items()): # Iterate copy for safe deletion
        if (now - data.get("last_seen", 0)) < SESSION_VALIDITY_DURATION:
            active_info.append({"name": data.get("name", f"IP: {ip}"), "ip": ip, "last_seen_ago_s": int(now - data.get("last_seen",0))})
        else:
            del _authenticated_sessions[ip]
            _log(logging.INFO, f"Cleaned up expired session for {ip} (Name: {data.get('name', 'N/A')}) during active session fetch.")
    return active_info

def clear_ip_session_on_token_forget(ip_address: str):
    """Clears an IP session if its associated token was forgotten."""
    global _authenticated_sessions
    if ip_address and ip_address != "unknown" and ip_address in _authenticated_sessions:
        session_name = _authenticated_sessions[ip_address].get("name", "N/A")
        del _authenticated_sessions[ip_address]
        _log(logging.INFO, f"Cleared active IP-based session for {ip_address} (Name: {session_name}) as its token was likely forgotten.")