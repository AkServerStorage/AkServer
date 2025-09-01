# =============================================================================
# akserver - API Route Handlers (Proprietary Edition)
# =============================================================================
"""
File:           akserver_route_handler_api.py
Description:    Contains API route handling logic for system status and device management.
Author:         AkshAy S (akserver Project)
Version:        1.0.0
License:        akserver Custom Freemium License (See LICENSE.txt)

This software provides API endpoints for:
- Retrieving a list of trusted devices and active sessions.
- Forgetting (removing) a trusted device.
- Initiating a server shutdown (for local clients only).
- Checking the server's operational status.

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

# ------------------------------------------------------------------ API Helper function

def handle_get_api_devices(handler):
    """Handles GET requests for the /api/devices endpoint."""

    is_local_admin_request = handler.client_address[0] == "127.0.0.1"
    if not is_local_admin_request and not handler._is_authenticated():
        handler._send_response_data(
            json.dumps({"error": "Authentication required"}).encode(),
            "application/json",
            401,
        )
        handler.server_logger.warning(
            f"Unauthorized API access to /api/devices from {handler.client_address[0]}"
        )
        return

    display_trusted_tokens = [
        {
            "name": device_obj.get(
                "name", f"Device ...{device_obj['token'][-6:]}"
            ),
            "token_partial": f"...{device_obj['token'][-6:]}",
        }
        for device_obj in handler.auth_manager_instance.trusted_devices_manager.get_trusted_devices_list()
    ]

    active_sessions_info = handler.auth_manager_instance.get_active_sessions_info()

    response_data = {
        "trusted_devices": display_trusted_tokens,
        "active_otp_sessions": active_sessions_info,
    }

    handler._send_response_data(
        json.dumps(response_data).encode(), "application/json"
    )


def handle_post_api_devices_forget(handler):
    """Handles POST requests for /api/devices/forget."""
    
    if not handler._check_api_access():
        return

    content_length = int(handler.headers["Content-Length"])
    post_data_raw = handler.rfile.read(content_length)

    try:
        post_data = json.loads(post_data_raw.decode("utf-8"))
        token_partial_to_forget = post_data.get("token_partial")

        if (
            not token_partial_to_forget
            or not token_partial_to_forget.startswith("...")
        ):
            handler._send_response_data(
                json.dumps({"success": False, "message": "Invalid token format."}).encode(),
                "application/json",
                400,
            )
            return

        suffix_to_find = token_partial_to_forget[3:]
        removed_device_info = handler.auth_manager_instance.trusted_devices_manager.forget_device_by_partial_token_suffix(
            suffix_to_find
        )

        if removed_device_info:
            removed_device_ip = removed_device_info.get("origin_ip")
            message = "Device token forgotten."

            if removed_device_ip:
                handler.auth_manager_instance.clear_ip_session_on_token_forget(removed_device_ip)
                handler.server_logger.info(
                    f"Cleared active IP-based session for {removed_device_ip} "
                    f"as its associated token was forgotten."
                )
                message += " Associated IP session cleared."

            handler._send_response_data(
                json.dumps({"success": True, "message": message}).encode(),
                "application/json",
            )
        else:
            handler._send_response_data(
                json.dumps({"success": False, "message": "Device token not found."}).encode(),
                "application/json",
                404,
            )

    except Exception as e:
        handler.server_logger.error(f"Error in /api/devices/forget: {e}", exc_info=True)
        handler._send_response_data(
            json.dumps({"success": False, "message": "Server error."}).encode(),
            "application/json",
            500,
        )


def handle_post_shutdown(handler):
    """Handles POST requests to /api/shutdown."""

    if handler.client_address[0] == "127.0.0.1":
        handler.server_logger.info(
            f"Received /api/shutdown request from local client {handler.client_address[0]}."
        )
        handler._send_response_data(
            json.dumps(
                {"success": True, "message": "Server shutdown initiated."}
            ).encode(),
            "application/json",
        )
        handler._trigger_server_shutdown()
    else:
        handler.server_logger.warning(
            f"Unauthorized /api/shutdown attempt from {handler.client_address[0]}."
        )
        handler._send_response_data(
            json.dumps({"success": False, "message": "Forbidden."}).encode(),
            "application/json",
            403,
        )

def handle_get_api_status(self):

    self._send_response_data(
        json.dumps(
            {"status": "ok", "auth_enabled": self.AUTH_ENABLED}
        ).encode(),
        "application/json",
    ) 
    return
