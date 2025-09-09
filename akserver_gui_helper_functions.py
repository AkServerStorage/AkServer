# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    A collection of reusable utility functions for the akserver GUI.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025 AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Python Standard Library Imports
import socket, json, urllib, os, sys

# ------------------------------------------------------------------ Third-Party Imports

from ttkbootstrap.constants import DANGER
import tkinter as tk
from tkinter import scrolledtext
from PIL import Image, ImageTk

# ------------------------------------------------------------------ Local Modules

from akserver_config import LOGGER as server_logger

# ------------------------------------------------------------------ path

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
LICENSES_FOLDER = "licenses"
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
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



class LicensesWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("AkServer Licenses & Privacy Documents")
        self.geometry("950x650")
        self.configure(bg="#ffffff")

        self.bg_color = "#ffffff"
        self.nav_bg = "#f9fbfc"
        self.active_bg = "#d4e5ff"
        self.accent_color = "#2a8bff"
        self.font_family = ("Segoe UI", 10)
        self.mono_font = ("Consolas", 10)

        # --- Set window icon ---
        icon_path = os.path.join(STATIC_DIR, "akserver_icon.ico")  # Add the filename!
        if os.path.exists(icon_path):
            try:
                icon_img = Image.open(icon_path)
                icon_img = ImageTk.PhotoImage(icon_img)
                self.iconphoto(False, icon_img)  # Set icon for window
                self._icon_img_ref = icon_img  # keep reference to avoid GC
            except Exception as e:
                print(f"[WARN] Could not set window icon: {e}")
        else:
            print(f"[WARN] Icon file not found: {icon_path}")


        self.nav_frame = tk.Frame(self, bg=self.nav_bg, width=260)
        self.nav_frame.pack(side="left", fill="y")

        self.content_frame = tk.Frame(self, bg=self.bg_color)
        self.content_frame.pack(side="right", fill="both", expand=True)

        self.doc_title = tk.Label(self.content_frame, text="", font=("Segoe UI",14,"bold"),
                                  bg=self.bg_color, fg="#05445e", anchor="w")
        self.doc_title.pack(fill="x", padx=10, pady=(10,5))

        self.text_widget = scrolledtext.ScrolledText(self.content_frame, wrap="word",
                                                     font=self.mono_font, bg=self.bg_color)
        self.text_widget.pack(fill="both", expand=True, padx=10, pady=(0,10))

        self.docs = self.load_docs()
        self.buttons = []
        self.active_btn = None
        self.create_nav_buttons()

        if self.docs:
            self.select_doc(0)

    def load_docs(self):
        docs = []
        for fname in os.listdir(LICENSES_FOLDER):
            if fname.lower().endswith(".txt") or fname.upper() == "LICENSE":
                docs.append({
                    "name": os.path.splitext(fname)[0].replace("_", " ").title(),
                    "path": os.path.join(LICENSES_FOLDER, fname)
                })
        docs.sort(key=lambda x: x["name"])
        return docs

    def create_nav_buttons(self):
        for index, doc in enumerate(self.docs):
            btn = tk.Label(self.nav_frame, text=doc["name"], bg=self.nav_bg, fg="#222",
                           anchor="w", padx=15, pady=8, font=self.font_family, cursor="hand2")
            btn.pack(fill="x")
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#e6f0ff"))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=self.active_bg if b==self.active_btn else self.nav_bg))
            btn.bind("<Button-1>", lambda e, idx=index: self.select_doc(idx))
            self.buttons.append(btn)

    def select_doc(self, index):
        doc = self.docs[index]
        if self.active_btn:
            self.active_btn.configure(bg=self.nav_bg, fg="#222", font=self.font_family)
        self.active_btn = self.buttons[index]
        self.active_btn.configure(bg=self.active_bg, fg="#05445e", font=("Segoe UI",10,"bold"))

        self.text_widget.delete("1.0", tk.END)
        self.doc_title.configure(text=doc["name"])
        try:
            with open(doc["path"], "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"Error reading file: {e}"
        self.text_widget.insert(tk.END, content)
        self.text_widget.yview_moveto(0)