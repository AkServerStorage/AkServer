# =============================================================================
# akserver - Handling Login, OTP (Proprietary Edition)
# =============================================================================
"""
File:           akserver_route_handlers_auth.py
Description:    Contains core route handling logic for authentication and user management.
Author:         AkshAy S (akserver Project)
Version:        1.0.0
License:        akserver Custom Freemium License (See LICENSE.txt)

This software handles core authentication operations, including:
- Serving login, logout, and device registration pages.
- Handling OTP-based login and device verification.
- Managing user sessions and cookies.

Third-party components used:
- None directly in this file.

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""



# ------------------------------------------------------------------ Python Standard Library Imports

import json
from urllib.parse import parse_qs, quote, unquote, urlparse

# ------------------------------------------------------------------  Local modules

from akserver_config import LOGGER as server_logger
from akserver_auth import DEVICE_TOKEN_COOKIE_NAME
from akserver_html import get_html


# ------------------------------------------------------------------ Login function

def handle_get_login_page(handler, message):
    """Handles GET requests for the /login path."""

    if handler.AUTH_ENABLED:
        if handler._is_authenticated():
            handler._redirect("/")
            return
        
        html_content = get_html(
            "akserver_html_login.html", # <-- USE THIS FILE NAME FOR NOW
            message_placeholder=(
                f"<div class='message'>{message}</div>" if message else ""
            )
        )
        handler._send_response_data(html_content.encode("utf-8"))

    else:
        handler._redirect("/")


def handle_post_login(handler):
    """Handles POST requests for the /login path."""
    if not handler.AUTH_ENABLED:
        handler._redirect("/")
        return

    content_length = int(handler.headers["Content-Length"])
    post_data = handler.rfile.read(content_length)
    params = parse_qs(post_data.decode("utf-8"))
    submitted_otp = params.get("otp", [None])[0]
    client_ip = handler.client_address[0]

    verified, message = handler.auth_manager_instance.verify_otp_and_mark_pending(
        submitted_otp, client_ip
    )

    if verified:
        # After OTP verification, check if this IP is associated with an already trusted device.
        trusted_device_info = handler.auth_manager_instance.get_trusted_device_by_ip(
            client_ip
        )
        if trusted_device_info:
            # Device is already trusted, create a session and redirect to main page
            existing_token, device_name = trusted_device_info
            handler.auth_manager_instance.create_session_for_trusted_device(
                client_ip, existing_token, device_name
            )
            handler._redirect("/", device_token_to_set=existing_token)
        else:
            # New device or IP not associated with a trusted device, proceed with registration
            handler._redirect("/register_device_name")
    else:
        handler._redirect(f"/login?message={quote(message)}")

# ------------------------------------------------------------------ Logout function

def handle_get_logout(handler, message=None):
    """Handles GET requests for the /logout path."""
    try:
        if handler.AUTH_ENABLED:
            if not getattr(handler, "auth_manager_instance", None):
                handler.server_logger.error("auth_manager_instance is None on logout!")
                handler.send_error(500, "Authentication manager not available")
                return

            # Perform logout
            try:
                handler.auth_manager_instance.logout_client_session(handler.client_address[0])
            except Exception as e:
                handler.server_logger.exception(f"Logout failed: {e}")
                handler.send_error(500, f"Logout failed: {e}")
                return

            handler.server_logger.info(
                f"User {handler.client_address[0]} logged out. IP session cleared and device token cookie removed."
            )

            # Delete cookie safely
            cookie_attrs = "; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"
            handler.send_response(200)
            handler.send_header("Content-type", "text/html; charset=utf-8")
            handler.send_header("Set-Cookie", f"{DEVICE_TOKEN_COOKIE_NAME}=; {cookie_attrs}")
            handler.end_headers()

            # Render logout page
            html_content = get_html("akserver_html_logout.html")
            handler.wfile.write(html_content.encode("utf-8"))

        else:
            handler._redirect("/")
    except Exception as e:
        handler.server_logger.exception(f"Unhandled error in logout: {e}")
        handler.send_error(500, f"Unhandled error in logout: {e}")

# ------------------------------------------------------------------ OTP function

def handle_get_request_otp(handler): # handle request otp
    """Handles GET requests for the /request_otp path."""

    if not handler.AUTH_ENABLED: 
        handler._send_response_data( 
            json.dumps( 
                {"success": False, "message": "Authentication is disabled."} 
            ).encode(), 
            "application/json", 
            403, 
        ) 
        return 

    new_otp = handler.auth_manager_instance.request_new_otp() # Request a new OTP
    response_payload = {"success": True, "message": "OTP generated."} 

    if handler.client_address[0] == "127.0.0.1": 
        response_payload["otp"] = new_otp 
        response_payload["message"] = ( 
            "OTP generated and provided for local client." 
        ) 
        handler.server_logger.info( 
            f"OTP generated and provided in response to local client {handler.client_address[0]}."
        ) 
    else: 
        # For remote clients, we do not send the OTP in the response for security reasons.
        handler.server_logger.info( 
            f"OTP generated (but not sent in response) for remote client {handler.client_address[0]}." 
        ) 
    server_logger.info(f"One-Time Password (OTP): {new_otp}") 
    handler._send_response_data( 
        json.dumps(response_payload).encode(), "application/json" 
    ) 
    return 

# ------------------------------------------------------------------ Device function

def handle_post_submit_device_name(handler):
    """Handles POST requests for /submit_device_name."""
    if not handler.AUTH_ENABLED:
        handler._redirect("/")
        return

    client_ip = handler.client_address[0]
    if not handler.auth_manager_instance.is_client_pending_registration(client_ip):
        handler.server_logger.warning(
            f"Unauthorized POST to /submit_device_name from {client_ip}. Redirecting to login."
        )
        handler._redirect("/login?message=Invalid session. Please login again.")
        return

    content_length = int(handler.headers["Content-Length"])
    post_data = handler.rfile.read(content_length)
    params = parse_qs(post_data.decode("utf-8"))
    submitted_device_name = params.get("device_name", [""])[0].strip()

    if not submitted_device_name:
        handler.server_logger.warning(
            f"Device name not provided by {client_ip} during registration."
        )
        handler._redirect(
            "/register_device_name?message=Device%20name%20is%20required."
        )
        return

    new_device_token = handler.auth_manager_instance.complete_device_registration(
        client_ip, submitted_device_name
    )

    if new_device_token:
        handler._redirect("/", device_token_to_set=new_device_token)
    else:
        handler._redirect(
            "/login?message=Device registration failed. Please try again."
        )


def handle_get_register_device_name(handler, message: str | None = None) -> None:
    """Handles GET requests for /register_device_name."""
    

    # === Auth Enabled Check ===
    if not handler.AUTH_ENABLED:
        handler._redirect("/")
        return

    client_ip = handler.client_address[0]

    # === Ensure client is pending registration ===
    if not handler.auth_manager_instance.is_client_pending_registration(client_ip):
        server_logger.warning(
            f"Unauthorized access to /register_device_name from {client_ip}. Redirecting to login."
        )
        handler._redirect("/login?message=Please login first.")
        return

    # === Render Registration Form ===
    html_content = get_html(
        "akserver_html_device_name.html",
        message_placeholder=(
            f"<div class='message'>{message}</div>" if message and message.strip() else ""
        )
    )
    handler._send_response_data(html_content.encode("utf-8"))
