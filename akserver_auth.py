# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Device authentication and secure session management.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025 AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ---------------------------------------------------- Python Standard Library Imports

import datetime, logging, random, secrets, threading, time
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING

# ---------------------------------------------------- Local Module Imports

if TYPE_CHECKING:
    from akserver_trusted_device_manager import TrustedDeviceManager

# ---------------------------------------------------- Auth variables
 
OTP_VALIDITY_DURATION = 1000
SESSION_VALIDITY_DURATION = 3600
DEVICE_TOKEN_COOKIE_NAME = "akserver_device_token"
DEVICE_TOKEN_VALIDITY_SECONDS = 30 * 24 * 60 * 60

# ---------------------------------------------------- Authentication Manager Class

class AuthManager:
    """Manages authentication, OTPs, and sessions for the server."""

    def __init__(
        self,
        logger_instance: logging.Logger,
        trusted_devices_manager: "TrustedDeviceManager",
        trusted_devices_file_path: str,
    ):
        self._logger = logger_instance
        self.trusted_devices_manager = trusted_devices_manager
        self.trusted_devices_file_path = trusted_devices_file_path

        self._current_otp: str | None = None
        self._otp_generation_time: float = 0
        self._pending_device_registration: dict[str, dict] = {}
        self._authenticated_sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _log(self, level, message, exc_info=False):
        """Centralized logging for AuthManager (production-safe)."""
        self._logger.log(level, f"[Auth] {message}", exc_info=exc_info)


    @staticmethod
    def generate_device_token() -> str:
        """Generate a secure random token for device identification."""
        return secrets.token_hex(32)

    @staticmethod
    def _generate_numeric_otp() -> str:
        """Generate a 6-digit numeric OTP as a string."""
        return "{:06d}".format(random.randint(0, 999999))

    def request_new_otp(self) -> str | None:
        """
        Generates a new OTP, stores its generation time.
        Returns the OTP for display/logging by the caller.
        Blocks if trial is expired.
        """
        with self._lock:
            self._current_otp = self._generate_numeric_otp()
            self._otp_generation_time = time.time()
            self._log(logging.INFO, f"New OTP generated: {self._current_otp}")
        return self._current_otp

    def verify_otp_and_mark_pending(
        self, submitted_otp: str, client_ip: str
    ) -> tuple[bool, str]:
        """
        Verifies the submitted OTP. If valid, marks the client_ip as pending device registration.
        Returns (success_status, message).
        """
        with self._lock:
            if self._current_otp and submitted_otp == self._current_otp:
                if (time.time() - self._otp_generation_time) < OTP_VALIDITY_DURATION:
                    self._pending_device_registration[client_ip] = {
                        "otp_verified_time": time.time()
                    }  # noqa: E501
                    self._log(
                        logging.INFO,
                        f"OTP verified for {client_ip}. Awaiting device name.",
                    )
                    return True, "OTP verified. Please register your device."
                else:
                    self._log(logging.WARNING, f"OTP expired. Attempt by {client_ip}")
                    return False, "OTP expired. Please request a new one."
            self._log(
                logging.WARNING, f"Invalid OTP '{submitted_otp}' attempt by {client_ip}"
            )
            return False, "Invalid OTP."

    def is_client_pending_registration(self, client_ip: str) -> bool:
        """Checks if a client IP is in the pending registration state and hasn't timed out."""
        with self._lock:
            if client_ip in self._pending_device_registration:
                if (
                    time.time()
                    - self._pending_device_registration[client_ip]["otp_verified_time"]
                    > 300
                ):
                    del self._pending_device_registration[client_ip]
                    self._log(
                        logging.INFO, f"Pending registration for {client_ip} timed out."
                    )
                    return False
                return True
            return False

    def complete_device_registration(
        self, client_ip: str, device_name: str
    ) -> str | None:
        """
        Completes device registration. Adds to trusted list, creates session, returns new token.
        Blocks registration if trial expired.
        """

        if not self.is_client_pending_registration(client_ip):
            return None

        new_device_token = self.generate_device_token()
        self.trusted_devices_manager.add_trusted_device(
            new_device_token, device_name, client_ip
        )
        with self._lock:
            self._authenticated_sessions[client_ip] = {
                "last_seen": time.time(),
                "name": device_name,
                "source": "otp_registration",
            }
            self._log(
                logging.INFO,
                f"Device '{device_name}' registered for {client_ip} with token ...{new_device_token[-6:]}.",
            )
            self._pending_device_registration.pop(client_ip, None)

        return new_device_token

    def get_trusted_device_by_ip(self, client_ip: str) -> tuple[str, str] | None:
        """
        Checks if the given client IP is associated with any currently trusted device.
        This is a heuristic and not a foolproof method for device identification.
        """
        self._log(
            logging.WARNING,
            (
                f"Attempting to identify trusted device by IP ({client_ip}). "
                "Note: IP addresses are not reliable unique identifiers for devices."
            ),
        )
        with self._lock:
            for device_info in self.trusted_devices_manager.get_trusted_devices_list():
                if device_info.get("origin_ip") == client_ip:
                    self._log(
                        logging.INFO,
                        f"Found existing trusted device '{device_info.get('name')}' for IP {client_ip}.",
                    )
                    return device_info["token"], device_info.get(
                        "name", f"Device ...{device_info['token'][-6:]}"
                    )
        self._log(logging.INFO, f"No existing trusted device found for IP {client_ip}.")
        return None

    def create_session_for_trusted_device(
        self, client_ip: str, device_token: str, device_name: str
    ):
        """Creates an authenticated session for a client using an existing trusted device token."""  
        with self._lock:
            self._authenticated_sessions[client_ip] = {
                "last_seen": time.time(),
                "name": device_name,
                "source": "re_login",
            }
            self._log(
                logging.INFO,
                (
                    f"Authenticated session created for {client_ip} "
                    f"(Device: '{device_name}') using existing token ...{device_token[-6:]}."
                ),
            )

    def check_authentication(
        self, cookie_header_value: str | None, client_ip: str
    ) -> tuple[bool, str | None]:
        """
        Checks auth via device token cookie or active IP session. Updates last_seen.
        Returns (is_authenticated, device_name_for_logs).
        """
        if cookie_header_value:
            cookie = SimpleCookie()
            try:
                cookie.load(cookie_header_value)
                if DEVICE_TOKEN_COOKIE_NAME in cookie:
                    device_token = cookie[DEVICE_TOKEN_COOKIE_NAME].value
                    if self.trusted_devices_manager.is_device_trusted(device_token):
                        dev_details = self.trusted_devices_manager.get_device_details(
                            device_token
                        )
                        dev_name = (
                            dev_details.get("name", f"Device ...{device_token[-6:]}")
                            if dev_details
                            else f"Token ...{device_token[-6:]}"
                        )

                        with self._lock:
                            self._authenticated_sessions[client_ip] = {  
                                "last_seen": time.time(),
                                "name": dev_name,
                                "source": "device_token",
                            }
                        return True, dev_name
            except Exception as e:
                self._log(
                    logging.WARNING,
                    f"Error parsing cookie for device token from {client_ip}: {e}",
                    exc_info=True,
                )

        with self._lock:
            if client_ip in self._authenticated_sessions:
                session_data = self._authenticated_sessions[client_ip]
                if (
                    time.time() - session_data.get("last_seen", 0)
                    < SESSION_VALIDITY_DURATION
                ):
                    session_data["last_seen"] = time.time()
                    dev_name = session_data.get("name", client_ip)
                    self._log(
                        logging.DEBUG,
                        f"Authenticated via active IP session for {client_ip} (Name: {dev_name})",
                    )
                    return True, dev_name
                else:
                    del self._authenticated_sessions[client_ip]
                    self._log(
                        logging.INFO,
                        f"IP Session expired for {client_ip} (Name: {session_data.get('name', 'N/A')})",
                    )

        self._log(logging.DEBUG, f"Authentication check failed for {client_ip}")
        return False, None

    def logout_client_session(self, client_ip: str):
        """Clears a client's IP-based session."""
        with self._lock:
            if client_ip in self._authenticated_sessions:
                session_name = self._authenticated_sessions[client_ip].get(
                    "name", "N/A"
                )
                del self._authenticated_sessions[client_ip]
                self._log(
                    logging.INFO,
                    f"User {client_ip} (Name: {session_name}) logged out. IP session cleared.",
                )

    def get_active_sessions_info(self) -> list:
        """
        Returns details of active sessions, cleaning up expired ones.
        Now includes the fixed 'session_started_at' time by reading it from session data.
        """
        active_info = []
        now = time.time()
        with self._lock:
            sessions_to_process = list(self._authenticated_sessions.items())

            for ip, data in sessions_to_process:
                if (now - data.get("last_seen", 0)) < SESSION_VALIDITY_DURATION:
                    start_timestamp = data.get("start_time", data.get("last_seen", 0))
                    session_started_at_str = datetime.datetime.fromtimestamp(
                        start_timestamp
                    ).strftime("%Y-%m-%d %H:%M:%S")

                    active_info.append(
                        {
                            "name": data.get("name", f"IP: {ip}"),
                            "ip": ip,
                            "last_seen_ago_s": int(now - data.get("last_seen", 0)),
                            "session_started_at": session_started_at_str, 
                        }
                    )
                else:
                    
                    if ip in self._authenticated_sessions: 
                        del self._authenticated_sessions[ip]
                        self._log(
                            logging.INFO,
                            (
                                f"Cleaned up expired session for {ip} "
                                f"(Name: {data.get('name', 'N/A')}) during active session fetch."
                            ),
                        )
        return active_info

    def clear_ip_session_on_token_forget(self, ip_address: str):
        """Clears an IP session if its associated token was forgotten."""
        with self._lock:  
            if (
                ip_address
                and ip_address != "unknown"
                and ip_address in self._authenticated_sessions
            ):
                session_name = self._authenticated_sessions[ip_address].get(
                    "name", "N/A"
                )
                del self._authenticated_sessions[ip_address]
                self._log(
                    logging.INFO,
                    (
                        f"Cleared active IP-based session for {ip_address} "
                        f"(Name: {session_name}) as its token was likely forgotten."
                    ),
                )
