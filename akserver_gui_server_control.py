# =============================================================================
# akserver - GUI Server Control Module (Proprietary Edition)
# =============================================================================
"""
File: akserver_gui_server_control.py
Description: Contains the logic for managing the akserver backend process from the GUI.

Author: AkshAy S (akserver Project)
Version: 1.0.0
License: akserver Custom Freemium License (See LICENSE.txt)

This module handles core server control operations, including:
- Starting the akserver process as a subprocess.
- Stopping the server gracefully via an internal API call.
- Checking the server's current operational status.
- Updating the GUI's state (buttons, status labels) to reflect the server's status.
- Providing a safe restart mechanism for the server.

Third-party components used:
- ttkbootstrap (MIT)
- tkinter (BSD)

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""


# ------------------------------------------------------------------  Python Standard Library Imports

import os
import sys
import ssl
import urllib.request
import threading
import subprocess
import time

# ------------------------------------------------------------------ Third-Party Imports

from tkinter import messagebox
from ttkbootstrap.constants import WARNING, INFO, SUCCESS, DANGER

# ------------------------------------------------------------------ Local Modules

from akserver_config import CONFIG, LOGGER as server_logger

# ------------------------------------------------------------------ Server Status Check

def check_server_status_api():
    """Returns True if server responds to /api/status."""
    try:
        context = ssl._create_unverified_context()
        port = CONFIG["port"]
        with urllib.request.urlopen(f"https://127.0.0.1:{port}/api/status", context=context, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False

# ------------------------------------------------------------------ Server Control (Start/Stop)

def start_server_logic(app):
    update_server_ui_state(app, False, status_text="Starting Server...", status_color=INFO)
    threading.Thread(target=_start_server_thread_logic, args=(app,), daemon=True).start()

def stop_server_logic(app):
    update_server_ui_state(app, True, status_text="Stopping Server...", status_color=WARNING)
    threading.Thread(target=_stop_server_thread_logic, args=(app,), daemon=True).start()

# ------------------------------------------------------------------ UI Updates

def update_server_ui_state(app, is_running, status_text=None, status_color=None):
    """Update buttons and status label safely."""
    if getattr(app, "server_button", None) and app.server_button.winfo_exists():
        try:
            app.server_button.config(
                text="Stop Server" if is_running else "Start Server",
                bootstyle=app.BUTTON_COLORS["stop" if is_running else "start"]
            )
        except Exception:
            pass

    if getattr(app, "server_status_label", None) and app.server_status_label.winfo_exists():
        default_text, default_color = ("Server Online", SUCCESS) if is_running else ("Server Offline", DANGER)
        try:
            app.server_status_label.config(
                text=status_text or default_text,
                bootstyle=status_color if status_color is not None else default_color
            )
        except Exception:
            pass

# ------------------------------------------------------------------ Internal Thread Logic

def _start_server_thread_logic(app):
    """Thread to start server safely."""
    try:
        from akserver_gui import APPLICATION_PATH, SERVER_SCRIPT_NAME

        server_logger.info("[DEBUG] Server start thread entered.")

        # Determine command
        if getattr(sys, "frozen", False):
            exe_path = os.path.join(APPLICATION_PATH, "akserver.exe")
            if not os.path.exists(exe_path):
                _report_error(app, f"Server executable not found: {exe_path}")
                return
            cmd = [exe_path]
        else:
            script_path = os.path.join(APPLICATION_PATH, SERVER_SCRIPT_NAME)
            if not os.path.exists(script_path):
                _report_error(app, f"Server script not found: {script_path}")
                return
            cmd = [sys.executable, script_path]

        env = os.environ.copy()
        env["akserver_SAVE_DIR"] = CONFIG["save_dir"]
        env["akserver_AUTH_ENABLED"] = "true"

        # Launch server
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )

        app.root.after(0, lambda: setattr(app, "server_process", process))
        app.root.after(0, lambda: update_server_ui_state(app, True, status_text="Server Started", status_color=SUCCESS))

    except Exception as e:
        _report_error(app, f"Failed to start server: {str(e)}")

def _stop_server_thread_logic(app):
    """Thread to stop server safely via API."""
    try:
        port = CONFIG["port"]
        context = ssl._create_unverified_context()
        req = urllib.request.Request(f"https://127.0.0.1:{port}/api/shutdown", method="POST")
        with urllib.request.urlopen(req, context=context, timeout=5):
            app.root.after(0, lambda: update_server_ui_state(app, False, status_text="Server Stopped", status_color=DANGER))
    except Exception as e:
        _report_error(app, f"Failed to stop server: {str(e)}")

# ------------------------------------------------------------------ Restart GUI Safely

def restart_server_logic(app):
    """Restart the GUI in a safe thread."""
    def _restart():
        try:
            if getattr(app, "server_process", None) and app.server_process.poll() is None:
                stop_server_logic(app)
                time.sleep(1)
            python = sys.executable
            os.execl(python, python, *sys.argv)
        except Exception as e:
            _report_error(app, f"Restart failed: {e}")
    threading.Thread(target=_restart, daemon=True).start()

# ------------------------------------------------------------------ Error Helper

def _report_error(app, message):
    server_logger.error(f"[ERROR] {message}")
    app.root.after(0, lambda: update_server_ui_state(app, False, status_text=message, status_color=DANGER))
    app.root.after(0, lambda: messagebox.showerror("Error", message))
