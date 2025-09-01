# =============================================================================
# akserver - Main Application (Proprietary Edition)
# =============================================================================

"""
File:           akserver_gui.py
Description:    GUI interface for akserver with system tray, QR sharing, and themed widgets.
Author:         AkshAy S (akserver Project)
Version:        1.0.0
License:        akserver Custom Freemium License (See LICENSE.txt)

This software provides a desktop GUI and tray interface with:
- System tray integration for background operation.
- Server start, stop, and status monitoring.
- GUI-based device and setting management.
- Local network QR code generation for easy device pairing.

Third-Party Dependencies:
  - pystray (LGPL-3.0)
  - qrcode (BSD)
  - Pillow (HPND)
  - ttkbootstrap (MIT)

Copyright © 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""


# ------------------------------------------------------------------ Python Standard library

import os
import sys
import threading
import time
import ctypes
import webbrowser
import pystray
import qrcode

# ------------------------------------------------------------------ Third-party

import tkinter as tk
from tkinter import filedialog
from ttkbootstrap import ttk, Window
import tkinter.ttk as tk_ttk
from PIL import Image, ImageTk
from ttkbootstrap import ttk, Window
from ttkbootstrap.constants import (
    WARNING, INFO, DANGER, LEFT, X, BOTTOM, W, SECONDARY, OUTLINE, SUCCESS, DARK, BOTH, RIGHT, SUNKEN
)

# ------------------------------------------------------------------ Local modules

from akserver_gui_helper_functions import truncate_path, add_hover_effect, add_bootstyle_hover, get_local_ip
from akserver_gui_server_control import start_server_logic, stop_server_logic, update_server_ui_state, restart_server_logic
from akserver_gui_settings import handle_generate_otp_request, custom_yes_no_dialog
from akserver_gui_connected_devices import _fetch_devices_from_server_thread
from akserver_gui_helper_functions import clear_frame
from akserver_config import PORT, CONFIG, load_config, save_config, LOGGER as server_logger

# ------------------------------------------------------------------ akserver Software info

FEEDBACK_URL = "https://akserverstorage.github.io/akserver_announcement/akserver_gui_feedback.html"

# ------------------------------------------------------------------ For linking main server file 

SERVER_SCRIPT_NAME = "akserver.py"  # Name of the server Python script

# ------------------------------------------------------------------ Subdirectory Paths

AUTH_ENABLED_FOR_SERVER = True
timestamp = int(time.time())
current_gui_save_dir = CONFIG["save_dir"]
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ------------------------------------------------------------------ GLobal config

FONT_HEADER = ("Helvetica", 18, "bold")
FONT_LABEL = ("Helvetica", 10)
FONT_SMALL = ("Helvetica", 8)

# ------------------------------------------------------------------ Prevent duplicate icons in taskbar

if sys.platform == "win32":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("akserver.GUI")

# ------------------------------------------------------------------ Determine executable location

if getattr(sys, "frozen", False):
    APPLICATION_PATH = os.path.dirname(sys.executable)
else:
    APPLICATION_PATH = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ Resource Path

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller.
    
    This version automatically looks inside the 'static' folder for assets.
    """
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = APPLICATION_PATH
        
    static_path = os.path.join(base_path, "static")
    
    return os.path.join(static_path, relative_path)

# ------------------------------------------------------------------ Main - UI

def display_main_app_ui(app, parent_frame, root_window):
    """Display the main application UI."""
    
    clear_frame(parent_frame)
    root_window.title("akserver Dashboard")

    # --- Header Frame for Logo and Title ---
    header_frame = ttk.Frame(parent_frame)
    header_frame.pack(pady=(10, 5)) 

    try:
        logo_path = resource_path("akserver_logo.png")
        if os.path.exists(logo_path):
            logo_pil = Image.open(logo_path)
            desired_height = 45
            aspect_ratio = logo_pil.width / logo_pil.height
            desired_width = int(desired_height * aspect_ratio)
            logo_pil_resized = logo_pil.resize(
                (desired_width, desired_height), Image.Resampling.LANCZOS
            )

            app.logo_image_tk = ImageTk.PhotoImage(logo_pil_resized)

            logo_label_header = ttk.Label(header_frame, image=app.logo_image_tk)
            logo_label_header.pack(side=LEFT, padx=(0, 10))
    except Exception as e:
        server_logger.info(f"Error loading or placing logo in header: {e}")

    ttk.Label(header_frame, text="akserver", font=("Helvetica", 18, "bold")).pack(
        side=LEFT
    )

    # --- Tagline Block ---
    tagline_frame = ttk.Frame(parent_frame, padding=(12, 10), bootstyle="light")
    tagline_frame.pack(pady=(5, 15), padx=20, fill=X)

    ttk.Label(
        tagline_frame,
        text="We empower you to establish your very own, completely private file storage system, operating entirely on your local network \n– Your Files, Your Network, Your Control.",  # noqa
        font=("Helvetica", 10, "italic"),
        bootstyle=DARK,
        wraplength=500,
        justify="center",
    ).pack(expand=True, fill=BOTH)

    # --- Button Block ---
    button_block_frame = ttk.Frame(parent_frame, padding=(0, 10))
    button_block_frame.pack(pady=(35, 10), fill=X, padx=20)

    # --- Create two columns within the block ---
    left_button_column = ttk.Frame(button_block_frame)
    left_button_column.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))

    right_button_column = ttk.Frame(button_block_frame)
    right_button_column.pack(side=RIGHT, fill=BOTH, expand=True, padx=(5, 0))

    # --- (left/right, top/bottom) internal padding ---
    button_height_padding = (10, 12)
    button_common_width = 16  

    # --- Left Column Buttons ---
    app.server_button = ttk.Button(
        left_button_column,
        text="Start Server",
        bootstyle=app.BUTTON_COLORS["start"],
        width=button_common_width,
        padding=button_height_padding,
        command=lambda: (
            start_server_logic(app)
            if app.server_button["text"] == "Start Server"
            else stop_server_logic(app)
        ),
    )
    app.server_button.pack(pady=(0, 5), fill=X, expand=True)
    if app.server_process and app.server_process.poll() is None:
        update_server_ui_state(app, True)
    else:
        update_server_ui_state(app, False)
    ttk.Button(
        left_button_column,
        text="Linked Devices",
        bootstyle=(INFO, OUTLINE),
        width=button_common_width,
        padding=button_height_padding,
        command=lambda: display_connected_devices_ui(app, parent_frame, root_window),
    ).pack(pady=(5, 0), fill=X, expand=True)

    # --- Right Column Buttons ---
    ttk.Button(
        right_button_column,
        text="Settings",
        bootstyle=(INFO, OUTLINE),
        width=button_common_width,
        padding=button_height_padding,
        command=lambda: display_settings_ui(app, parent_frame, root_window),
    ).pack(pady=(0, 5), fill=X, expand=True)
    ttk.Button(
        right_button_column,
        text="Info & Feedback",
        bootstyle=(SECONDARY, OUTLINE),
        width=button_common_width,
        padding=button_height_padding,
        command=lambda: webbrowser.open(FEEDBACK_URL),
    ).pack(pady=(5, 0), fill=X, expand=True)

# ------------------------------------------------------------------ Settings - UI

def display_settings_ui(app, parent_frame, root_window):
    """Display the settings window with Connect, OTP, QR, and folder options."""

    # --- Clear frame ---
    clear_frame(parent_frame)
    root_window.title("Settings")

    # --- Top Frame (Back + Instruction) ---
    top_frame = ttk.Frame(parent_frame)
    top_frame.pack(fill=X, pady=5, padx=10)

    # --- Back button ---
    back_button = ttk.Button(
        top_frame,
        text="⬅",
        bootstyle="info",
        command=lambda: display_main_app_ui(app, parent_frame, root_window)
    )
    back_button.pack(side=LEFT)
    add_bootstyle_hover(back_button, normal="info", hover="primary")

    # --- Instruction label centered ---
    instruction_label = ttk.Label(
        parent_frame,
        text="Click 'Connect' to securely add a new device.",
        font=("Segoe UI", 11, "italic"),
        foreground="#333333",
        wraplength=500,
        justify="center"
    )
    instruction_label.place(relx=0.5, y=10, anchor="n")
    app.instruction_label = instruction_label

    # --- Connect Button ---
    def show_qr_and_otp():
        connect_button.pack_forget()
        qr_frame.pack(pady=(5, 0), fill=X, padx=15)
        otp_frame.pack(pady=5, fill=X, padx=15)
        instruction_label.config(text="Click 'Gen Code' to get your OTP.")

    connect_button = ttk.Button(
        parent_frame,
        text="Connect",
        bootstyle="primary",
        command=show_qr_and_otp
    )
    connect_button.pack(pady=(5, 10))
    add_bootstyle_hover(connect_button, normal="primary", hover="success")
    app.connect_button = connect_button

    # --- QR Frame ---
    qr_frame = ttk.Frame(parent_frame)
    local_ip = get_local_ip()
    server_url = f"https://{local_ip}:{PORT}/login" if AUTH_ENABLED_FOR_SERVER else f"https://{local_ip}:{PORT}/"
    qr = qrcode.QRCode(box_size=4, border=3)
    qr.add_data(server_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_img_tk = ImageTk.PhotoImage(qr_img)
    qr_label = ttk.Label(qr_frame, image=qr_img_tk)
    qr_label.image = qr_img_tk
    qr_label.pack(pady=(5, 0))
    ttk.Label(qr_frame, text=f"Scan to connect: {server_url}", font=("Helvetica", 9)).pack(pady=(2, 5))

    # --- OTP Frame ---
    otp_frame = ttk.Frame(parent_frame)
    app.otp_display_label_settings = ttk.Label(otp_frame, text="", font=("Helvetica", 12, "bold"))
    app.generate_otp_button_settings = ttk.Button(
        otp_frame,
        text="Gen Code",
        bootstyle="Primary",
        command=lambda: handle_generate_otp_request(app)
    )
    if AUTH_ENABLED_FOR_SERVER:
        app.generate_otp_button_settings.pack()
        add_bootstyle_hover(app.generate_otp_button_settings, normal="success", hover="warning")

    # --- Folder Frame (Bottom) ---
    folder_var = tk.StringVar(value=truncate_path(current_gui_save_dir))

    def choose_folder():
        folder_selected = filedialog.askdirectory(parent=root_window, title="Select Sync Folder")
        if folder_selected:
            folder_var.set(truncate_path(folder_selected))
            CONFIG["save_dir"] = folder_selected
            global current_gui_save_dir
            current_gui_save_dir = folder_selected
            save_config()
            icon_path = os.path.join(STATIC_DIR, "akserver_icon.png")
            restart_now = custom_yes_no_dialog(
                icon_path=icon_path,
                title="Restart Required",
                msg="Sync folder changed. Restart server now?",
                parent_window=root_window
            )
            if restart_now:
                restart_server_logic(app)
            else:
                app.set_bottom_status_message("Folder updated. Restart server later.", DANGER)

    
    folder_frame = ttk.LabelFrame(parent_frame, text="Sync Folder Location", padding=10)
    folder_frame.pack(side=BOTTOM, fill=X, padx=10, pady=(5, 5))
    ttk.Label(folder_frame, textvariable=folder_var, wraplength=300, anchor=W).pack(
        side=LEFT, padx=(0, 5), fill=X, expand=True
    )
    select_btn = ttk.Button(folder_frame, text="Select Path", bootstyle="secondary", command=choose_folder)
    select_btn.pack(side=LEFT, padx=5)
    add_hover_effect(back_button, "info", "primary")
    add_hover_effect(connect_button, "primary", "info") 
    add_hover_effect(app.generate_otp_button_settings, "primary", "info")
    add_hover_effect(select_btn, "secondary", "info")

# ------------------------------------------------------------------ Linked Devices - UI

def display_connected_devices_ui(app, parent_frame, root_window):
    """Professional connected devices window with top, main, and bottom sections."""

    clear_frame(parent_frame)
    root_window.title("Connected Devices Management")

    # --- Parent frame layout ---
    parent_frame.grid_rowconfigure(0, weight=0)  # Top bar
    parent_frame.grid_rowconfigure(1, weight=1)  # Main content
    parent_frame.grid_rowconfigure(2, weight=0)  # Bottom frame
    parent_frame.grid_columnconfigure(0, weight=1)

    # ------------------ Top Bar ------------------
    top_bar = ttk.Frame(parent_frame, padding=(10, 5))
    top_bar.grid(row=0, column=0, sticky="ew")
    top_bar.grid_columnconfigure(1, weight=1)

    back_button = ttk.Button(
        top_bar,
        text="⬅",
        bootstyle="info",
        command=lambda: display_main_app_ui(app, parent_frame, root_window)
    )
    back_button.grid(row=0, column=0, sticky="w")
    add_bootstyle_hover(back_button, normal="info", hover="primary")

    local_status_label_devices = ttk.Label(top_bar, text="Loading device data...", bootstyle=INFO)
    local_status_label_devices.grid(row=0, column=1, sticky="ew", padx=10)

    refresh_button = ttk.Button(top_bar, text="Refresh", bootstyle=(SECONDARY, OUTLINE))
    refresh_button.config(
        command=lambda: threading.Thread(
            target=_fetch_devices_from_server_thread,
            args=(app, local_status_label_devices, root_window, refresh_button),
            daemon=True
        ).start()
    )
    refresh_button.grid(row=0, column=2, sticky="e")

    # ------------------ Main Content ------------------
    main_frame = ttk.Frame(parent_frame, padding=(10, 0))
    main_frame.grid(row=1, column=0, sticky="nsew")
    main_frame.grid_rowconfigure(0, weight=1)
    main_frame.grid_rowconfigure(1, weight=1)
    main_frame.grid_columnconfigure(0, weight=1)

    # --- Trusted Devices ---
    trusted_frame_outer = ttk.LabelFrame(main_frame, text="Trusted Devices", padding=(10, 10), bootstyle="primary")
    trusted_frame_outer.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
    trusted_frame_outer.grid_rowconfigure(0, weight=1)
    trusted_frame_outer.grid_columnconfigure(0, weight=1)

    app.trusted_devices_canvas = tk.Canvas(trusted_frame_outer, borderwidth=0, highlightthickness=0)
    app.trusted_devices_scrollbar = tk_ttk.Scrollbar(trusted_frame_outer, orient="vertical", command=app.trusted_devices_canvas.yview)
    app.trusted_devices_tree = ttk.Frame(app.trusted_devices_canvas)

    app.trusted_devices_window_id = app.trusted_devices_canvas.create_window((0,0), window=app.trusted_devices_tree, anchor="nw")
    app.trusted_devices_canvas.configure(yscrollcommand=app.trusted_devices_scrollbar.set)
    app.trusted_devices_canvas.grid(row=0, column=0, sticky="nsew")
    app.trusted_devices_scrollbar.grid(row=0, column=1, sticky="ns")

    app.trusted_devices_tree.bind(
        "<Configure>",
        lambda e: app.trusted_devices_canvas.configure(scrollregion=app.trusted_devices_canvas.bbox("all"))
    )
    app.trusted_devices_canvas.bind(
        "<Configure>",
        lambda e: app.trusted_devices_canvas.itemconfig(app.trusted_devices_window_id, width=e.width)
    )

    # --- Active Sessions ---
    active_frame_outer = ttk.LabelFrame(main_frame, text="Active Sessions", padding=(10, 10), bootstyle="info")
    active_frame_outer.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
    active_frame_outer.grid_rowconfigure(0, weight=1)
    active_frame_outer.grid_columnconfigure(0, weight=1)

    app.active_sessions_canvas = tk.Canvas(active_frame_outer, borderwidth=0, highlightthickness=0)
    app.active_sessions_scrollbar = tk_ttk.Scrollbar(active_frame_outer, orient="vertical", command=app.active_sessions_canvas.yview)
    app.active_sessions_tree = ttk.Frame(app.active_sessions_canvas)

    app.active_sessions_window_id = app.active_sessions_canvas.create_window((0,0), window=app.active_sessions_tree, anchor="nw")
    app.active_sessions_canvas.configure(yscrollcommand=app.active_sessions_scrollbar.set)
    app.active_sessions_canvas.grid(row=0, column=0, sticky="nsew")
    app.active_sessions_scrollbar.grid(row=0, column=1, sticky="ns")

    app.active_sessions_canvas.bind(
        "<Configure>",
        lambda e: app.active_sessions_canvas.itemconfig(app.active_sessions_window_id, width=e.width)
    )


    # --- Fetch devices automatically ---
    threading.Thread(
        target=_fetch_devices_from_server_thread,
        args=(app, local_status_label_devices, root_window, refresh_button),
        daemon=True
    ).start()

# ------------------------------------------------------------------ Application Class

class akserverGUI:
            
    def __init__(self, start_in_tray=False):
        load_config()

        self.root = Window(themename="flatly")
        self.root.title("akserver Control")
        self.root.geometry("600x450")
        self.root.resizable(False, False)

        # --- Instance variables for state and UI widgets ---
        self.app_icon_tk_ref = None
        self.logo_image_tk = None
        self.server_button = None
        self.server_status_label = None
        self.otp_display_label_settings = None
        self.generate_otp_button_settings = None
        self.trusted_devices_tree = None
        self.active_sessions_tree = None
        self.last_updated_time = None
        self.ACTIVE_SESSION_RECENCY_THRESHOLD_SECONDS = 5 * 60
        self.BUTTON_COLORS = {"start": SUCCESS, "stop": DANGER}
        self.PORT = 8443
        self.server_process = None

        self._set_app_icon()
        self._setup_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        if start_in_tray:
            self.root.withdraw()
            threading.Thread(target=self.create_tray_icon, daemon=True).start()


    def _set_app_icon(self):
        try:
            icon_path_png = resource_path("akserver_icon.png")
            icon_path_ico = resource_path("akserver_icon.ico")

            icon_set = False
            if sys.platform == "win32" and os.path.exists(icon_path_ico):
                try:
                    self.root.iconbitmap(icon_path_ico)
                    icon_set = True
                except Exception as e_ico:
                    server_logger.info(
                        f"Error setting .ico application icon: {e_ico}. Will try .png."
                    )

            if not icon_set and os.path.exists(icon_path_png):
                try:
                    app_icon_pil = Image.open(icon_path_png)
                    if app_icon_pil.mode != "RGBA":
                        app_icon_pil = app_icon_pil.convert("RGBA")
                    self.app_icon_tk_ref = ImageTk.PhotoImage(app_icon_pil)
                    self.root.iconphoto(True, self.app_icon_tk_ref)
                    icon_set = True
                except Exception as e_png:
                    server_logger.info(f"Error setting .png application icon: {e_png}")

            if not icon_set:
                server_logger.info("Warning: Application icon file not found.")
        except Exception as e:
            server_logger.info(f"General error during application icon setup: {e}")


    def _setup_ui(self):
        content_frame = ttk.Frame(self.root, padding=20)
        content_frame.pack(fill=BOTH, expand=True)

        current_year = time.strftime("%Y")
        copyright_label = ttk.Label(
            self.root,
            text=f"© {current_year} akserver. All rights reserved.",
            font=("Helvetica", 8),
            bootstyle=SECONDARY,
            anchor="center",
        )
        copyright_label.pack(side=BOTTOM, fill=X)

        self.server_status_label = ttk.Label(
            self.root,
            text="Checking Server Status...",
            font=("Helvetica", 10),
            bootstyle=WARNING,
            relief=SUNKEN,
            anchor=W,
            padding=5,
        )
        self.server_status_label.pack(side=BOTTOM, fill=X)

        display_main_app_ui(self, content_frame, self.root)


    def set_bottom_status_message(self, text: str, bootstyle: str = INFO):
        """
        Update the permanent bottom status bar with given text and color style.
        """
        if self.server_status_label and self.server_status_label.winfo_exists():
            self.server_status_label.config(text=text, bootstyle=bootstyle)


    def periodic_status_check(self):
        """Safely checks server and updates UI."""
        if not self.root.winfo_exists() or not (self.server_button and self.server_button.winfo_exists()):
            return
        try:
            running = self.server_process and self.server_process.poll() is None
            update_server_ui_state(self, running)
        except Exception as e:
            server_logger.error(f"Error in periodic_status_check: {e}")
        finally:
            self._status_check_id = self.root.after(2000, self.periodic_status_check)


    def _start_background_tasks(self):
        start_server_logic(self)
        self.root.after(100, self.periodic_status_check)


    def run(self):
        self._start_background_tasks()
        self.root.mainloop()


    def update_status_message(self, text: str, bootstyle: str = INFO, duration: int = 3000):
        """Show a temporary overlay message at top of root window."""
        popup_label = tk.Label(
            self.root,
            text=text,
            bg="#e0f7fa", fg="#004d40",
            font=("Segoe UI", 8, "bold"),
            padx=18, pady=8, bd=1, relief="groove"
        )
        popup_label.place(relx=0.5, rely=0.05, anchor="n")
        popup_label.lift()
        self.root.after(duration, popup_label.destroy)


    def create_tray_icon(self):
        """Creates and runs the system tray icon."""

        def show_window(icon, item):
            self.root.after(0, self.root.deiconify)
            icon.stop()

        def quit_window(icon, item):
            def shutdown_and_exit():
                try:
                    import ssl, urllib.request

                    context = ssl._create_unverified_context()
                    req = urllib.request.Request("https://127.0.0.1:8443/api/shutdown", method="POST")
                    urllib.request.urlopen(req, context=context, timeout=5)
                    server_logger.info("[Tray] Shutdown signal sent to server.")
                except Exception as e:
                    server_logger.info(f"[Tray] Shutdown failed or server not running: {e}")

                time.sleep(1)  # Give server time to shut down

                try:
                    icon.stop()
                except:
                    pass
                self.root.after(0, self.root.destroy)

            threading.Thread(target=shutdown_and_exit, daemon=True).start()


        icon_path_ico = resource_path("akserver_icon.ico")
        icon_path_png = resource_path("akserver_icon.png")

        image = None
        if sys.platform == "win32" and os.path.exists(icon_path_ico):
            image = Image.open(icon_path_ico)
        elif os.path.exists(icon_path_png):
            image = Image.open(icon_path_png)

        menu = pystray.Menu(
            pystray.MenuItem("Show", show_window), pystray.MenuItem("Exit", quit_window)
        )
        tray_icon = pystray.Icon("akserver", image, "akserver", menu)
        tray_icon.run()


    def on_server_button_click(self):
        try:
            if self.server_button["text"] == "Start Server":
                start_server_logic(self)
            else:
                stop_server_logic(self)
        except Exception as e:
            self.update_status_message(f"Server action failed: {e}", DANGER)


    def on_closing(self):
        """Minimizes the window to the system tray safely."""
        self.root.withdraw()
        if not hasattr(self, "tray_thread") or not self.tray_thread.is_alive():
            self.tray_thread = threading.Thread(target=self.create_tray_icon, daemon=True)
            self.tray_thread.start()


    def on_server_started(self, process):
        """Updates the server process variable on the main thread and starts the status check."""
        self.server_process = process
        self.periodic_status_check()

# ------------------------------------------------------------------ Entry Point

if __name__ == "__main__":
    start_in_tray = "--tray-start" in sys.argv
    app = akserverGUI(start_in_tray=start_in_tray)
    app.run()

    