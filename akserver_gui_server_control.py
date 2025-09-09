
# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Handles starting/stopping akserver from GUI safely.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025 AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------  Python Standard Library

import os, sys, ssl,  time, subprocess, urllib.request, threading

# ------------------------------------------------------------------ Third-Party Imports

from tkinter import messagebox
from ttkbootstrap.constants import WARNING, INFO, SUCCESS, DANGER

# ------------------------------------------------------------------ Local Modules

from akserver_config import CONFIG, LOGGER as server_logger, PORT

# ------------------------------------------------------------------ Helpers

def _get_trial_status(app):
    """Return trial info dict: {'active': bool, 'days_left': int}"""
    return getattr(app, "get_trial_status", lambda: {"active": True, "days_left": 0})()

def _set_server_button_state(app, enabled=True):
    """Safely update server button state based on trial and busy status"""
    if getattr(app, "server_button", None) and app.server_button.winfo_exists():
        trial_active = _get_trial_status(app).get("active", True)
        state = "normal" if enabled and trial_active else "disabled"
        app.root.after(0, lambda: app.server_button.config(state=state))

def _report_error(app, message):
    """Centralized error reporting"""
    server_logger.error(f"[ERROR] {message}")
    if getattr(app, "root", None):
        app.root.after(0, lambda: update_server_ui_state(app, False, message, DANGER))
        app.root.after(0, lambda: messagebox.showerror("Error", message))

# ------------------------------------------------------------------ Server Status Check

def check_server_status_api():
    """Return True if server responds to /api/status."""
    try:
        context = ssl._create_unverified_context()
        port = CONFIG["port"]
        with urllib.request.urlopen(f"https://127.0.0.1:{port}/api/status", context=context, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False

# ------------------------------------------------------------------ UI Updates

def update_server_ui_state(app, is_running, status_text=None, status_color=None):
    """Update server label and button safely"""
    try:
        trial_info = _get_trial_status(app)
        trial_active = trial_info.get("active", True)
        days_left = trial_info.get("days_left", 0)

        if getattr(app, "server_status_label", None) and app.server_status_label.winfo_exists():
            default_text = "Server Online" if is_running else "Server Offline"
            default_color = SUCCESS if is_running else DANGER
            trial_text = f"Trial active — {days_left} days remaining" if trial_active else "Trial Expired — Upgrade required!"
            combined_text = f"{status_text or default_text} | {trial_text}"
            combined_color = DANGER if not trial_active else (status_color or default_color)
            app.server_status_label.config(text=combined_text, bootstyle=combined_color)

        if getattr(app, "server_button", None) and app.server_button.winfo_exists():
            app.server_button.config(
                text="Stop Server" if is_running else "Start Server",
                bootstyle=app.BUTTON_COLORS["stop" if is_running else "start"]
            )
            busy = getattr(app, "server_busy", False)
            _set_server_button_state(app, enabled=not busy)

    except Exception as e:
        server_logger.exception("update_server_ui_state error: %s", e)


# ------------------------------------------------------------------ Server Control

def start_server_logic(app):
    if getattr(app, "server_busy", False):
        return
    app.server_busy = True
    _set_server_button_state(app, enabled=False)
    update_server_ui_state(app, False, "Starting Server...", WARNING)
    threading.Thread(target=_start_server_thread_logic, args=(app,), daemon=True).start()

def stop_server_logic(app):
    if getattr(app, "server_busy", False):
        return
    app.server_busy = True
    _set_server_button_state(app, enabled=False)
    update_server_ui_state(app, True, "Stopping Server...", WARNING)
    threading.Thread(target=_stop_server_thread_logic, args=(app,), daemon=True).start()


# ------------------------------------------------------------------ Internal Thread Logic
def _start_server_thread_logic(app):
    """Start server in background thread."""
    try:
        from akserver_gui import APPLICATION_PATH, SERVER_SCRIPT_NAME

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

        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )

        app.server_process = process
        time.sleep(1)
        running = process.poll() is None
        app.root.after(0, lambda: update_server_ui_state(
            app,
            running,
            "Server Started" if running else "Failed to start",
            SUCCESS if running else DANGER
        ))

    except Exception as e:
        _report_error(app, f"Failed to start server: {e}")
    finally:
        app.server_busy = False
        _set_server_button_state(app, enabled=True)

def _stop_server_thread_logic(app):
    """Stop server in background thread."""
    try:
        if getattr(app, "server_process", None):
            context = ssl._create_unverified_context()
            req = urllib.request.Request(f"https://127.0.0.1:{PORT}/api/shutdown", method="POST")
            urllib.request.urlopen(req, context=context, timeout=5)

        app.root.after(0, lambda: update_server_ui_state(app, False, "Server stopped successfully.", SUCCESS))

    except urllib.error.URLError:
        app.root.after(0, lambda: update_server_ui_state(app, False, "Server is already stopped.", INFO))
    except Exception as e:
        app.root.after(0, lambda e=e: update_server_ui_state(app, False, f"Unexpected error: {e}", DANGER))
    finally:
        app.server_busy = False
        app.server_process = None
        _set_server_button_state(app, enabled=True)

# ------------------------------------------------------------------ Restart GUI

def restart_server_logic(app):
    """Restart the GUI safely."""
    def _restart():
        try:
            if getattr(app, "server_process", None) and app.server_process.poll() is None:
                stop_server_logic(app)
                while getattr(app, "server_busy", False):
                    time.sleep(0.1)
            python = sys.executable
            os.execl(python, python, *sys.argv)
        except Exception as e:
            _report_error(app, f"Restart failed: {e}")

    threading.Thread(target=_restart, daemon=True).start()
