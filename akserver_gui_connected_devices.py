# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Contains GUI logic for displaying and managing connected devices and active sessions.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025-present AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------  Python Standard Library Imports

import ssl, json, time, urllib, threading

# ------------------------------------------------------------------ Third-Party Imports

from ttkbootstrap import ttk
from ttkbootstrap.constants import INFO, SUCCESS, DANGER, LEFT, RIGHT, X, SOLID, SECONDARY

# ------------------------------------------------------------------ Local Modules

from akserver_gui_helper_functions import _handle_api_error, clear_frame
from akserver_config import CONFIG, LOGGER as server_logger

# ------------------------------------------------------------------  Internal Helpers

def _clear_devices_ui(app):
    for tree in [app.trusted_devices_tree, app.active_sessions_tree]:
        if tree:
            for widget in tree.winfo_children():
                widget.destroy()
            ttk.Label(tree, text="No devices found.", bootstyle=INFO).pack(pady=10)

def _fetch_devices_from_server_thread(app, status_label_ref, root_window_ref, refresh_button_ref=None):
    """Fetch devices from server in a thread."""
    try:
        if refresh_button_ref:
            root_window_ref.after(0, lambda: refresh_button_ref.config(
                text="Refreshing...", state="disabled", bootstyle=(SECONDARY, 'outline')
            ))
        port = CONFIG["port"]
        url = f"https://127.0.0.1:{port}/api/devices"
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url)

        root_window_ref.after(0, lambda: status_label_ref.config(text="Refreshing device list...", bootstyle=INFO))

        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                server_logger.debug(f"API Response: {json.dumps(data, indent=2)}") 
                root_window_ref.after(0, lambda d=data: _update_devices_ui(app, d, status_label_ref))
                app.last_updated_time = time.strftime("%I:%M %p")
                msg = "Device list updated." if data.get("trusted_devices") or data.get("active_otp_sessions") else "No connected devices found."
                root_window_ref.after(0, lambda: status_label_ref.config(
                    text=msg, bootstyle=SUCCESS if "updated" in msg else INFO))
    except Exception as e:
        _handle_api_error(e, status_label_ref, root_window_ref, "Failed to refresh list", lambda: _clear_devices_ui(app))
    finally:
        if refresh_button_ref and refresh_button_ref.winfo_exists():
            root_window_ref.after(0, lambda: refresh_button_ref.config(text="Refresh", state="normal",
                                                                     bootstyle=(SECONDARY, 'outline')))

def _update_devices_ui(app, data, status_label_ref):
    """Populate devices and active sessions UI."""
    device_type_icons = {"laptop": "💻", "phone": "📱", "default": "🖥️"}

    tree = app.trusted_devices_tree
    clear_frame(tree)
    if data.get("trusted_devices"):
        for device in data["trusted_devices"]:
            name = device.get("name", "Unnamed Device")
            token = device.get("token_partial", "N/A")
            icon = device_type_icons.get(device.get("device_type", "laptop"), "🖥️")
            frame = ttk.Frame(tree, borderwidth=1, relief=SOLID, padding=5)
            frame.pack(fill=X, pady=2, padx=2)
            ttk.Label(frame, text=f"{icon} {name}", font=("Helvetica", 12)).pack(side=LEFT, padx=5)
            ttk.Button(frame, text="Forget", bootstyle=DANGER,
                       command=lambda tp=token, df=frame: threading.Thread(
                           target=_forget_device_thread, args=(tp, status_label_ref, app, df), daemon=True).start(),
                           takefocus=0
                       ).pack(side=RIGHT, padx=5)
    else:
        ttk.Label(tree, text="No trusted devices found.", bootstyle=INFO).pack(pady=10)

    tree = app.active_sessions_tree
    clear_frame(tree)
    sessions = data.get("active_otp_sessions", [])
    displayed = 0
    for session in sessions:
        last_seen_s = session.get("last_seen_ago_s", float("inf"))
        if last_seen_s < getattr(app, "ACTIVE_SESSION_RECENCY_THRESHOLD_SECONDS", 3600):
            icon = device_type_icons.get(session.get("device_type", "phone"), "🖥️")
            frame = ttk.Frame(tree, borderwidth=1, relief=SOLID, padding=5)
            frame.pack(fill=X, pady=2, padx=2)
            left = ttk.Frame(frame)
            left.pack(side=LEFT, expand=True, fill=X, padx=3)
            ttk.Label(left, text=f"{icon} {session.get('name','N/A')}", font=("Helvetica", 9)).pack(side=LEFT)
            ttk.Label(left, text=f"Started: {session.get('session_started_at','Unknown')} | Last: ~{round(last_seen_s/60)} min ago",
                      font=("Helvetica", 8), bootstyle=SECONDARY).pack(side=LEFT, padx=5)
            ttk.Label(frame, text="●", foreground="green", font=("Helvetica", 12)).pack(side=RIGHT, padx=5)
            displayed += 1
    if displayed == 0:
        ttk.Label(tree, text="No recently active sessions found.", bootstyle=INFO).pack(pady=10)

    if hasattr(app, "set_bottom_status_message"):
        app.set_bottom_status_message("Device list refreshed.", INFO)

def _forget_device_thread(token_partial, status_label_ref, app_ref, device_frame):
    """Forget device via API."""
    try:
        port = CONFIG["port"]
        url = f"https://127.0.0.1:{port}/api/devices/forget"
        payload = json.dumps({"token_partial": token_partial}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        app_ref.root.after(0, lambda: status_label_ref.config(text=f"Forgetting {token_partial}...", bootstyle=INFO))
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            if response.status == 200:
                app_ref.root.after(0, lambda: device_frame.destroy())
                app_ref.root.after(1000, lambda: threading.Thread(
                    target=_fetch_devices_from_server_thread,
                    args=(app_ref, status_label_ref, app_ref.root),
                    daemon=True
                ).start())
                if hasattr(app_ref, "set_bottom_status_message"):
                    app_ref.set_bottom_status_message(f"Device {token_partial} forgotten", SUCCESS)
    except Exception as e:
        server_logger.error(f"Error forgetting {token_partial}: {e}")