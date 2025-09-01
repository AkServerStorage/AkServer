# =============================================================================
# akserver - GUI Helper Functions Module (Proprietary Edition)
# =============================================================================
"""
File: akserver_gui_helper_functions.py
Description: A collection of reusable utility functions for the akserver GUI.

Author: AkshAy S (akserver Project)
Version: 1.0.0
License: akserver Custom Freemium License (See LICENSE.txt)

This module contains various helper functions to streamline UI development and
improve code consistency. The functions cover:
- Frame and widget management.
- Path string manipulation for better UI display.
- Adding dynamic hover effects to ttkbootstrap widgets.
- Network-related tasks, such as getting the local IP address.
- Standardized API error handling for graceful feedback.

Third-party components used:
- ttkbootstrap (MIT)

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------  Python Standard Library Imports
import socket
import json
import urllib

# ------------------------------------------------------------------ Third-Party Imports

from ttkbootstrap.constants import DANGER

# ------------------------------------------------------------------ Local Modules
import os, sys
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from akserver_config import LOGGER as server_logger

# ------------------------------------------------------------------ Frame Helpers
def clear_frame(frame):
    """Remove all widgets from a Tkinter frame."""
    for widget in frame.winfo_children():
        widget.destroy()

# ------------------------------------------------------------------ Path Helpers

def truncate_path(path, max_length=40):
    """Truncate long paths in the middle with ellipsis."""
    if len(path) <= max_length:
        return path
    part_length = max_length // 2 - 2
    return f"{path[:part_length]}...{path[-part_length:]}"

# ------------------------------------------------------------------ Hover Helpers

def add_bootstyle_hover(widget, normal="primary", hover="success"):
    """Swap bootstyle on hover for ttkbootstrap buttons."""

    def on_enter(e):
        widget.config(bootstyle=hover)
    def on_leave(e):
        widget.config(bootstyle=normal)
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)

def add_hover_effect(button, normal_style, hover_style):
    """Apply hover effect that correctly resets on mouse leave."""

    def on_enter(e):
        try:
            button.configure(bootstyle=hover_style)
        except Exception as ex:
            server_logger.error(f"Hover enter error: {ex}")
    def on_leave(e):
        try:
            button.configure(bootstyle=normal_style)
        except Exception as ex:
            server_logger.error(f"Hover leave error: {ex}")
    button.bind("<Enter>", on_enter)
    button.bind("<Leave>", on_leave)

# ------------------------------------------------------------------ Network Helpers

def get_local_ip():
    """Return local LAN IP address or fallback to 127.0.0.1."""

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

# ------------------------------------------------------------------ API Error Handling

def _get_error_message_from_http_exception(e, default_message_prefix="Error"):
    """Extract a detailed error message from an HTTPError or similar exception object."""

    try:
        error_body = e.read().decode()
        error_detail = json.loads(error_body).get("message", getattr(e, "reason", str(e)))
        return f"{default_message_prefix} {getattr(e, 'code', '')}: {error_detail}".strip()
    except Exception:
        if hasattr(e, "code") and hasattr(e, "reason"):
            return f"{default_message_prefix} {e.code}: {e.reason}"
        elif hasattr(e, "reason"):
            return f"{default_message_prefix}: {e.reason}"
        return f"{default_message_prefix}: {str(e)}"

def _handle_api_error(e, status_label_ref, root_window_ref, error_prefix, clear_ui_callback=None):
    """Handles common error patterns for API calls in the GUI."""

    if isinstance(e, urllib.error.HTTPError):
        error_message = _get_error_message_from_http_exception(e, error_prefix)
    else:
        error_message = f"{error_prefix} (General Error): {str(e)}"

    if status_label_ref and root_window_ref and status_label_ref.winfo_exists():
        root_window_ref.after(
            0,
            lambda msg=error_message: status_label_ref.config(text=msg, bootstyle=DANGER),
        )

    if clear_ui_callback and root_window_ref and callable(clear_ui_callback):
        root_window_ref.after(0, clear_ui_callback)
