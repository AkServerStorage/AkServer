# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    GUI interface for akserver with system tray, QR sharing, and themed widgets.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025 AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""


# ------------------------------------------------------------------ Python Standard library

import os, sys, threading, time, ctypes, webbrowser, ssl, urllib.request, pystray, qrcode

# ------------------------------------------------------------------ Third-party

import tkinter as tk
import tkinter.ttk as tk_ttk
from tkinter import filedialog
from PIL import Image, ImageTk
from ttkbootstrap import ttk, Window
from ttkbootstrap.constants import (
    INFO, DANGER, LEFT, X, BOTTOM, W, SECONDARY, 
    OUTLINE, SUCCESS, DARK, BOTH, RIGHT, SUNKEN
)

# ------------------------------------------------------------------ Local modules

from akserver_gui_helper_functions import truncate_path, add_hover_effect, add_bootstyle_hover, get_local_ip
from akserver_gui_server_control import start_server_logic, stop_server_logic, update_server_ui_state, restart_server_logic
from akserver_gui_settings import handle_generate_otp_request, custom_yes_no_dialog
from akserver_gui_connected_devices import _fetch_devices_from_server_thread
from akserver_gui_helper_functions import clear_frame, LicensesWindow
from akserver_config import PORT, CONFIG, load_config, save_config, LOGGER as server_logger
from akserver_trial import check_trial

# ------------------------------------------------------------------ akserver Software info

FEEDBACK_URL = "https://akserverstorage.github.io/akserver_announcement/akserver_gui_feedback.html"

# ------------------------------------------------------------------ For linking main server file 

SERVER_SCRIPT_NAME = "akserver.py"

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
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = APPLICATION_PATH
        
    static_path = os.path.join(base_path, "static")
    
    return os.path.join(static_path, relative_path)

# ------------------------------------------------------------------ Main - UI

def display_main_app_ui(app, parent_frame, root_window):
    """Display the main application UI and update server + trial status."""

 
    from akserver import is_wifi_enabled, is_wifi_connected
    if is_wifi_enabled():
        ssid = is_wifi_connected()
        if ssid:
            app.parent_frame = parent_frame
            app.show_wifi_status_overlay()
            return
    
    trial_status = check_trial()
    if not trial_status["active"]:
        app.parent_frame = parent_frame
        app.show_trial_expired_overlay()
        return

    clear_frame(parent_frame)
    root_window.title("AkServer Dashboard")

    header_frame = ttk.Frame(parent_frame)
    header_frame.pack(pady=(10, 5)) 

    try:
        logo_path = resource_path("akserver_logo.png")
        if os.path.exists(logo_path):
            logo_label_header = ttk.Label(header_frame, image=app.logo_image_tk)
            logo_label_header.pack(side=LEFT, padx=(0, 10))
    except Exception as e:
        server_logger.info(f"Error loading or placing logo in header: {e}")

    ttk.Label(header_frame, text="AkServer", font=("Helvetica", 18, "bold")).pack(side=LEFT)

    tagline_frame = ttk.Frame(parent_frame, padding=(12, 10), bootstyle="light")
    tagline_frame.pack(pady=(5, 15), padx=20, fill=X)

    ttk.Label(
        tagline_frame,
        text="We empower you to create your own private data storage system on your local network.\n\nYour Files. Your Network. Your Control.",
        font=("Helvetica", 10, "italic"),
        bootstyle=DARK,
        wraplength=500,
        justify="center",
    ).pack(expand=True, fill=BOTH)

    button_block_frame = ttk.Frame(parent_frame, padding=(0, 10))
    button_block_frame.pack(pady=(30, 10), fill=X, padx=20)

    left_button_column = ttk.Frame(button_block_frame)
    left_button_column.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))

    right_button_column = ttk.Frame(button_block_frame)
    right_button_column.pack(side=RIGHT, fill=BOTH, expand=True, padx=(5, 0))

    button_height_padding = (10, 12)
    button_common_width = 16  

    app.server_button = ttk.Button(
        left_button_column,
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

    ttk.Button(
        right_button_column,
        text="Connection & Settings",
        bootstyle=(INFO, OUTLINE),
        width=button_common_width,
        padding=button_height_padding,
        command=lambda: display_settings_ui(app, parent_frame, root_window),
    ).pack(pady=(0, 5), fill=X, expand=True)
    ttk.Button(
        right_button_column,
        text="About",
        bootstyle=(SECONDARY, OUTLINE),
        width=button_common_width,
        padding=button_height_padding,
        command=lambda: display_about_ui(app, parent_frame, root_window), #webbrowser.open(FEEDBACK_URL),
    ).pack(pady=(5, 0), fill=X, expand=True)

    app.root.after(50, lambda: update_main_status(app))


def update_main_status(app):
    """Update bottom status with server online/offline and trial info."""

    running = app.server_process and app.server_process.poll() is None

    trial_info = app.get_trial_status()
    trial_active = trial_info.get("active", False)
    days_left = trial_info.get("days_left", 0)

    if running:
        server_text = "Server Online"
        server_color = SUCCESS
    else:
        server_text = "Server Offline"
        server_color = DANGER

    if trial_active:
        trial_text = f"Trial active — {days_left} days remaining"
        if not running:
            app.server_button.config(state="normal")
    else:
        trial_text = "Trial Expired — Upgrade required!"
        if not running:
            app.server_button.config(state="disabled")

    combined_text = f"{server_text} | {trial_text}"
    
    combined_color = DANGER if not trial_active else server_color
    app.set_bottom_status_message(combined_text, combined_color)

# ------------------------------------------------------------------ Settings - UI

def display_settings_ui(app, parent_frame, root_window):
    """Display the settings window with Connect, OTP, QR, and folder options."""

    clear_frame(parent_frame)
    root_window.title("Server Settings")

    top_frame = ttk.Frame(parent_frame)
    top_frame.pack(fill=X, pady=5, padx=10)

    back_button = ttk.Button(
        top_frame,
        text="⬅",
        bootstyle="info",
        command=lambda: app.root.after(50, lambda: display_main_app_ui(app, parent_frame, root_window))
    )
    back_button.pack(side=LEFT)
    add_bootstyle_hover(back_button, normal="info", hover="primary")


    def show_qr_and_otp():
        connect_button.pack_forget()
        qr_frame.pack(pady=(5, 0), fill=X, padx=15)
        otp_frame.pack(pady=5, fill=X, padx=15)

    connect_button = ttk.Button(
        parent_frame,
        text="Add Device",
        bootstyle="primary",
        command=show_qr_and_otp
    )
    connect_button.pack(pady=(5, 10))
    add_bootstyle_hover(connect_button, normal="primary", hover="success")
    app.connect_button = connect_button

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

    otp_frame = ttk.Frame(parent_frame)
    app.otp_display_label_settings = ttk.Label(otp_frame, text="", font=("Helvetica", 12, "bold"))
    app.generate_otp_button_settings = ttk.Button(
        otp_frame,
        text="Generate Code",
        bootstyle="Primary",
        command=lambda: handle_generate_otp_request(app)
    )
    if AUTH_ENABLED_FOR_SERVER:
        app.generate_otp_button_settings.pack()
        add_bootstyle_hover(app.generate_otp_button_settings, normal="success", hover="warning")

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
    root_window.title("Linked Devices")

    parent_frame.grid_rowconfigure(0, weight=0)
    parent_frame.grid_rowconfigure(1, weight=1)
    parent_frame.grid_rowconfigure(2, weight=0)
    parent_frame.grid_columnconfigure(0, weight=1)

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

    main_frame = ttk.Frame(parent_frame, padding=(10, 0))
    main_frame.grid(row=1, column=0, sticky="nsew")
    main_frame.grid_rowconfigure(0, weight=1)
    main_frame.grid_rowconfigure(1, weight=1)
    main_frame.grid_columnconfigure(0, weight=1)

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


    threading.Thread(
        target=_fetch_devices_from_server_thread,
        args=(app, local_status_label_devices, root_window, refresh_button),
        daemon=True
    ).start()

# ------------------------------------------------------------------ Info - UI
def display_about_ui(app, parent_frame, root_window):
    clear_frame(parent_frame)
    root_window.title("About AkServer")

    top_frame = ttk.Frame(parent_frame)
    top_frame.pack(fill=X, pady=5)

    back_button = ttk.Button(
        top_frame,
        text="⬅",
        bootstyle="info",
        command=lambda: app.root.after(
            50, lambda: display_main_app_ui(app, parent_frame, root_window)
        ),
    )
    back_button.pack(side=LEFT, padx=(5,0))
    add_bootstyle_hover(back_button, normal="info", hover="primary")

    title_label = ttk.Label(top_frame, text="AkServer v1.0.0", font=("Segoe UI",14,"bold"))
    title_label.place(relx=0.5, rely=0, anchor='n')  

    ttk.Label(parent_frame, text="© 2025 AkServer Storage — All rights reserved",
              font=("Segoe UI",9), foreground="gray").pack(pady=(0,15))

    content_frame = ttk.Frame(parent_frame)
    content_frame.pack(fill=BOTH, expand=True, pady=5, padx=25)

    def open_url(url):
        webbrowser.open(url)

    ttk.Label(content_frame, text="Secure • Fast • Private Local Cloud Storage",
              font=("Segoe UI",10,"italic"), foreground="gray").pack(pady=(0,8))

    ttk.Label(content_frame, text="Developed by Akshay Shinde",
              font=("Segoe UI",10)).pack(pady=(0,8))

    ttk.Label(content_frame,
              text="Proprietary software — all rights reserved.\nYour data stays local and private; no personal files are uploaded or shared.",
              font=("Segoe UI",9), foreground="gray", justify="center").pack(pady=(0,15))

    links_row = ttk.Frame(content_frame)
    links_row.pack(pady=(0,5))

    def add_clickable_label(parent, text, url):
        label = ttk.Label(
            parent,
            text=text,
            foreground="darkblue",
            cursor="hand2",
            font=("Segoe UI", 10, "underline")
        )
        label.bind("<Button-1>", lambda e: webbrowser.open(url))

        def on_enter(e):
            label.configure(foreground="blue")
        def on_leave(e):
            label.configure(foreground="darkblue")
        label.bind("<Enter>", on_enter)
        label.bind("<Leave>", on_leave)

        return label

    license_label = add_clickable_label(links_row, "Licenses & Privacy Policy", "#")
    license_label.bind("<Button-1>", lambda e: LicensesWindow(root_window))
    license_label.pack(side=LEFT, padx=20)

    website_label = add_clickable_label(links_row, "Website", "https://akserverstorage.github.io/akserver-website/")
    website_label.pack(side=LEFT, padx=20)

    email_address = "akserverstorage@gmail.com"
    mailto_link = f"mailto:{email_address}?subject=Support%20Request&body=Hello%20AkServer%20Team,"
    email_label = add_clickable_label(content_frame, email_address, mailto_link)
    email_label.configure(wraplength=300)
    email_label.pack(pady=(0,15))

    social_frame = ttk.Frame(content_frame)
    social_frame.pack()

    def add_icon_link(parent, img_path, url):
        try:
            img = Image.open(os.path.join(STATIC_DIR,img_path))
            img = img.resize((32,32), Image.LANCZOS)
            icon = ImageTk.PhotoImage(img)
            btn = ttk.Label(parent,image=icon,cursor="hand2")
            btn.image = icon
            btn.pack(side=LEFT, padx=10)
            btn.bind("<Button-1>", lambda e: open_url(url))
        except Exception as e:
            print(f"[WARN] Icon not loaded: {img_path} → {e}")

    add_icon_link(social_frame, "Instagram_Glyph_Gradient.png", "https://www.instagram.com/akserverstorage/")
    add_icon_link(social_frame, "x-logo.png", "https://x.com/akserverstorage")
    
# ------------------------------------------------------------------ GUI Application Class

class akserverGUI:
    
    # ------------------------------------------------------------------ Init
    def __init__(self, start_in_tray=False):
        load_config()
        self.root = Window(themename="flatly")
        self.root.withdraw()
        self.root.title("AkServer")
        self.root.geometry("600x450")
        self.root.resizable(False, False)
        self._center_window(600, 450)

        self._init_ui_variables()
        self._show_splash_screen()
        self.root.after(1500, self._setup_ui_after_splash)

        if start_in_tray:
            self.root.after(2000, lambda: threading.Thread(target=self.create_tray_icon, daemon=True).start())

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ------------------------------------------------------------------ UI Variables
    def _init_ui_variables(self):
        self.server_button = None
        self.server_status_label = None
        self.server_process = None
        self.app_icon_tk_ref = None
        self.logo_image_tk = None
        self.current_overlay = None
        self.server_busy = False
        self.BUTTON_COLORS = {"start": SUCCESS, "stop": DANGER}

    # ------------------------------------------------------------------ Window Helpers
    def _center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------------ Splash Screen
    def _show_splash_screen(self, duration=2000):
        self.splash = tk.Toplevel()
        self.splash.overrideredirect(True)
        self.splash.attributes("-topmost", True)
        self._center_splash(300, 240)

        frame = ttk.Frame(self.splash, padding=20)
        frame.pack(expand=True, fill=BOTH)

        try:
            logo_path = resource_path("akserver_logo.png")
            logo_pil = Image.open(logo_path)
            aspect_ratio = logo_pil.width / logo_pil.height
            desired_height = 80
            desired_width = int(desired_height * aspect_ratio)
            self.splash_logo_tk = ImageTk.PhotoImage(
                logo_pil.resize((desired_width, desired_height), Image.Resampling.LANCZOS)
            )
            ttk.Label(frame, image=self.splash_logo_tk).pack(pady=(0, 5))
        except Exception as e:
            server_logger.exception(f"Splash logo load failed: {e}")

        ttk.Label(frame, text="AkServer", font=("Helvetica", 18, "bold")).pack(pady=(0, 5))
        ttk.Label(frame, text="Your Private Storage Server", font=("Helvetica", 10, "italic")).pack()

        self.splash_status_label = ttk.Label(frame, text="Starting server...", font=("Helvetica", 10))
        self.splash_status_label.pack(pady=(15, 0))

        self.splash.update()
        self.root.withdraw()
        self.root.after(duration, self._destroy_splash_and_show_main)

    def _center_splash(self, width, height):
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 2
        self.splash.geometry(f"{width}x{height}+{x}+{y}")

    def _destroy_splash_and_show_main(self):
        if self.splash and self.splash.winfo_exists():
            self.splash.destroy()
        self.root.deiconify()

    def _setup_ui_after_splash(self):
        if self.splash and self.splash.winfo_exists():
            self.splash.destroy()
        self.root.deiconify()
        self._setup_ui()
        self._set_app_icon()

    # ------------------------------------------------------------------ Main UI
    def _setup_ui(self):
        self._trial_banner_frame = ttk.Frame(self.root)
        self._trial_banner_frame.pack(side="top", fill=X)

        self.content_frame = ttk.Frame(self.root, padding=20)
        self.content_frame.pack(fill=BOTH, expand=True)

        current_year = time.strftime("%Y")
        ttk.Label(
            self.root,
            text=f"© {current_year} akserver. All rights reserved.",
            font=("Helvetica", 8),
            bootstyle=SECONDARY,
            anchor="center"
        ).pack(side="bottom", fill=X)

        self.server_status_label = ttk.Label(
            self.root,
            text="Checking Server Status...",
            font=("Helvetica", 10),
            bootstyle=INFO,
            relief=SUNKEN,
            anchor=W,
            padding=5
        )
        self.server_status_label.pack(side="bottom", fill=X)

        try:
            logo_path = resource_path("akserver_logo.png")
            logo_pil = Image.open(logo_path)
            aspect_ratio = logo_pil.width / logo_pil.height
            self.logo_image_tk = ImageTk.PhotoImage(
                logo_pil.resize((int(45 * aspect_ratio), 45), Image.Resampling.LANCZOS)
            )
        except Exception as e:
            server_logger.exception(f"Logo preload failed: {e}")

        self.parent_frame = self.content_frame
        display_main_app_ui(self, self.content_frame, self.root)
        self.root.after(2000, self.periodic_status_check)

    # ------------------------------------------------------------------ Trial
    def get_trial_status(self):
        return check_trial()

    def _update_trial_ui(self):
        trial_info = self.get_trial_status()
        trial_active = trial_info.get("active", True)
        days_left = trial_info.get("days_left", 0)
        server_running = self.server_process and self.server_process.poll() is None

        server_text = "Server Online" if server_running else "Server Offline"
        trial_text = f"Trial active — {days_left} days remaining" if trial_active else "Trial Expired — Upgrade required!"
        combined_text = f"{server_text} | {trial_text}"
        combined_color = SUCCESS if server_running and trial_active else DANGER

        if self.server_status_label and self.server_status_label.winfo_exists():
            self.server_status_label.config(text=combined_text, bootstyle=combined_color)

        if self.server_button and self.server_button.winfo_exists():
            self.server_button.config(state="normal" if trial_active and not self.server_busy else "disabled")

        if not trial_active:
            self.show_trial_expired_overlay()

    def show_trial_expired_overlay(self):
        if getattr(self, "current_overlay", None) and self.current_overlay.winfo_exists():
            return

        for widget in self.content_frame.winfo_children():
            widget.destroy()

        style = ttk.Style()
        style.configure("Card.TFrame", background="white")
        style.configure("Card.TLabel", background="white", foreground="#333", font=("Helvetica", 11))
        style.configure("CardBold.TLabel", background="white", foreground="#333", font=("Helvetica", 16, "bold"))

        card = ttk.Frame(self.content_frame, padding=30, style="Card.TFrame")
        card.place(relx=0.5, rely=0.5, anchor="center")

        if self.logo_image_tk:
            ttk.Label(card, image=self.logo_image_tk, style="Card.TLabel").pack(pady=(0, 15))

        ttk.Label(card, text="Your Trial Has Expired", style="CardBold.TLabel").pack(pady=(0, 10))
        ttk.Label(card, text="Please upgrade to continue using AkServer.", style="Card.TLabel", wraplength=300, justify="center").pack(pady=(0, 20))

        ttk.Button(card, text="Upgrade Now", bootstyle="success", command=lambda: webbrowser.open("https://akserverstorage.github.io/akserver-website")).pack(pady=(0, 10))
        self.current_overlay = card

    # ------------------------------------------------------------------ Periodic Update
    def periodic_status_check(self):
        if not self.root.winfo_exists():
            return
        try:
            from akserver import is_wifi_enabled
            if not is_wifi_enabled():
                self.show_wifi_status_overlay()
            else:
                if getattr(self, "wifi_current_overlay", None) and self.wifi_current_overlay.winfo_exists():
                    try:
                        self.wifi_current_overlay.destroy()
                    except Exception:
                        pass
                    self.wifi_current_overlay = None
                    display_main_app_ui(self, self.parent_frame or self.content_frame, self.root)
            self._update_trial_ui()
        finally:
            self.root.after(5000, self.periodic_status_check)

    # ------------------------------------------------------------------ App Icon
    def _set_app_icon(self):
        try:
            icon_path_ico = resource_path("akserver_icon.ico")
            icon_path_png = resource_path("akserver_icon.png")
            icon_set = False

            if sys.platform == "win32" and os.path.exists(icon_path_ico):
                try:
                    self.root.iconbitmap(icon_path_ico)
                    icon_set = True
                except Exception as e:
                    server_logger.exception(f"ICO icon error: {e}")

            if not icon_set and os.path.exists(icon_path_png):
                img = Image.open(icon_path_png).convert("RGBA")
                self.app_icon_tk_ref = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self.app_icon_tk_ref)

        except Exception as e:
            server_logger.exception(f"General icon setup error: {e}")

    def set_bottom_status_message(self, message, style=None):
        if self.server_status_label and self.server_status_label.winfo_exists():
            self.server_status_label.config(text=message, bootstyle=style or "secondary")
            self.server_status_label.update_idletasks()

    # ------------------------------------------------------------------ Tray
    def create_tray_icon(self):
        def show_window(icon, item):
            self.root.after(0, self.root.deiconify)
            icon.stop()

        def quit_window(icon, item):
            try:
                context = ssl._create_unverified_context()
                req = urllib.request.Request(f"https://127.0.0.1:{PORT}/api/shutdown", method="POST")
                urllib.request.urlopen(req, context=context, timeout=5)
            except Exception as e:
                server_logger.exception(f"[Tray] Shutdown failed: {e}")
            finally:
                icon.stop()
                self.root.after(0, self.root.destroy)

        icon_path_ico = resource_path("akserver_icon.ico")
        icon_path_png = resource_path("akserver_icon.png")
        image = Image.open(icon_path_ico if os.path.exists(icon_path_ico) else icon_path_png)
        menu = pystray.Menu(pystray.MenuItem("Show", show_window), pystray.MenuItem("Exit", quit_window))
        pystray.Icon("akserver", image, "akserver", menu).run()

    # ------------------------------------------------------------------ Window Close
    def on_closing(self):
        self.root.withdraw()
        if not hasattr(self, "tray_thread") or not self.tray_thread.is_alive():
            self.tray_thread = threading.Thread(target=self.create_tray_icon, daemon=True)
            self.tray_thread.start()

    # ------------------------------------------------------------------ Run
    def run(self):
        start_server_logic(self)
        self.root.mainloop()


    # ------------------------------------------------------------------ wifi checking
    def show_wifi_status_overlay(self):
        """Show a centered overlay that blocks the UI while Wi-Fi is not available."""
        
        if getattr(self, "wifi_current_overlay", None) and self.wifi_current_overlay.winfo_exists():
            return

        self.parent_frame = self.content_frame

        for widget in self.content_frame.winfo_children():
            widget.destroy()

        style = ttk.Style()
        style.configure("WiFiCard.TFrame", background="white")
        style.configure("WiFiCard.TLabel", background="white", foreground="#333", font=("Helvetica", 11))
        style.configure("WiFiCardBold.TLabel", background="white", foreground="#333", font=("Helvetica", 16, "bold"))

        card = ttk.Frame(self.content_frame, padding=30, style="WiFiCard.TFrame")
        card.place(relx=0.5, rely=0.5, anchor="center")

        if self.logo_image_tk:
            ttk.Label(card, image=self.logo_image_tk, style="WiFiCard.TLabel").pack(pady=(0, 12))

        ttk.Label(card, text="No network detected", style="WiFiCardBold.TLabel").pack(pady=(0, 8))
        ttk.Label(
            card,
            text="Please connect to a Wi-Fi network to use AkServer.\nThe UI will refresh automatically when a network is available.",
            style="WiFiCard.TLabel",
            wraplength=380,
            justify="center"
        ).pack(pady=(0, 15))

        retry_btn = ttk.Button(card, text="Retry", bootstyle="primary", command=lambda: self._check_wifi_and_update())
        retry_btn.pack(pady=(6, 4))

        if sys.platform == "win32":
            def open_net_settings():
                try:
                    import subprocess
                    subprocess.Popen(["start", "ms-settings:network"], shell=True)
                except Exception as e:
                    server_logger.debug(f"[WiFi Overlay] open_net_settings failed: {e}")
                    self.set_bottom_status_message("Cannot open Network Settings.", DANGER)

            ttk.Button(card, text="Open Network Settings", bootstyle="secondary", command=open_net_settings).pack(pady=(2, 0))

        self.wifi_current_overlay = card

    def _check_wifi_and_update(self):
        """Immediate check called by Retry button or other events."""
        from akserver import is_wifi_enabled

        if is_wifi_enabled():
            if getattr(self, "wifi_current_overlay", None) and self.wifi_current_overlay.winfo_exists():
                try:
                    self.wifi_current_overlay.destroy()
                except Exception:
                    pass
                self.wifi_current_overlay = None

            display_main_app_ui(self, self.parent_frame, self.root)
            self._update_trial_ui()
        else:
            self.set_bottom_status_message("No Wi-Fi detected. Still offline.", DANGER)


# ------------------------------------------------------------------ Entry Point
if __name__ == "__main__":
    start_in_tray = "--tray-start" in sys.argv
    app = akserverGUI(start_in_tray=start_in_tray)
    app.run()

    