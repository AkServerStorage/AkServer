# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Contains GUI logic for settings, including QR code sharing, OTP generation, and custom dialogs.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025-present AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------  Python Standard Library

import os, ssl, json, time, threading, qrcode, urllib.request

# ------------------------------------------------------------------ Third-Party Imports

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
from ttkbootstrap.constants import WARNING, INFO

# ------------------------------------------------------------------ Local Modules

from akserver_gui_helper_functions import _handle_api_error
from akserver_config import CONFIG, LOGGER as server_logger

# ------------------------------------------------------------------ QR Code Generator

def generate_qr_image(url):
    qr = qrcode.QRCode(box_size=4, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return ImageTk.PhotoImage(img)

# ------------------------------------------------------------------ Custom Dialog

def custom_yes_no_dialog(parent_window, icon_path: str, title: str, msg: str) -> bool:
    if parent_window is None:
        parent_window = None 
    try:
        if icon_path and os.path.exists(icon_path):
            icon_pil = Image.open(icon_path)
            icon_tk = ImageTk.PhotoImage(icon_pil)
            parent_window.iconphoto(True, icon_tk)
    except Exception as e:
        server_logger.warning(f"Failed to set custom icon: {e}")
    return messagebox.askyesno(title, msg, parent=parent_window)

# ------------------------------------------------------------------ OTP Handling

def handle_generate_otp_request(app):
    """Triggered by button click."""
    if getattr(app, "generate_otp_button_settings", None):
        app.generate_otp_button_settings.pack_forget()
    if getattr(app, "otp_display_label_settings", None):
        try:
            app.otp_display_label_settings.config(text="Requesting OTP...", bootstyle=WARNING)
            app.otp_display_label_settings.pack(pady=(5, 0))
        except tk.TclError:
            pass
    threading.Thread(target=lambda: request_otp(app), daemon=True).start()


def request_otp(app):
    """Fetch OTP from server with retries."""
    try:
        url = f"https://127.0.0.1:{CONFIG['port']}/request_otp"
        context = ssl._create_unverified_context()
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, context=context, timeout=5) as response:
                    data = json.loads(response.read())
                    otp = data.get("otp")
                    msg = data.get("message")
                    if otp:
                        app.root.after(0, lambda otp=otp: update_settings_otp_display(app, otp))
                        return
                    elif msg:
                        app.root.after(0, lambda: messagebox.showwarning("OTP Info", msg))
                        return
            except Exception:
                if attempt < 2:
                    time.sleep(0.5)
                else:
                    raise
        app.root.after(0, lambda: messagebox.showerror("Server Offline", "Cannot request OTP, server unreachable."))
        app.root.after(0, lambda: clear_settings_otp_display(app))
    except Exception as e:
        _handle_api_error(
            e,
            getattr(app, "otp_display_label_settings", None),
            app.root,
            "Failed to request OTP",
            lambda: clear_settings_otp_display(app)
        )


def clear_settings_otp_display(app):
    """Safely hide OTP and restore button."""
    label = getattr(app, "otp_display_label_settings", None)
    if label and label.winfo_exists():
        try:
            label.config(text="")
            label.pack_forget()
        except tk.TclError:
            pass
    btn = getattr(app, "generate_otp_button_settings", None)
    if btn and btn.winfo_exists():
        btn.pack()


def update_settings_otp_display(app, otp_value):
    """Display OTP and auto-clear after 10 seconds safely."""
    label = getattr(app, "otp_display_label_settings", None)
    if label and label.winfo_exists():
        try:
            label.config(text=f"OTP: {otp_value}", bootstyle=INFO)
            label.pack(pady=(5, 0))
        except tk.TclError:
            return
    if hasattr(app, "_otp_clear_id") and app._otp_clear_id:
        try:
            app.root.after_cancel(app._otp_clear_id)
        except Exception:
            pass

    app._otp_clear_id = app.root.after(10000, lambda: clear_settings_otp_display(app))

