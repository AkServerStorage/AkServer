import os
import sys
import json
import urllib.request
import ssl # ssl._create_unverified_context is used
import socket
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, filedialog
from ttkbootstrap import Window, ttk
import webbrowser
from ttkbootstrap.constants import *
import qrcode # For QR code generation
from PIL import Image, ImageTk # Ensure ImageTk is imported
import datetime

if getattr(sys, 'frozen', False):
    APPLICATION_PATH = os.path.dirname(sys.executable) # Directory of AkServer_GUI.exe
else:
    APPLICATION_PATH = os.path.dirname(os.path.abspath(__file__))

SERVER_SCRIPT_NAME = "AkServer.py" # Name of the server Python script

# GUI Config file location in LocalAppData
LOCALAPPDATA_AKSERVER_BASE = os.path.join(os.getenv('LOCALAPPDATA', ''), 'AkServer')
GUI_CONFIG_PATH = os.path.join(LOCALAPPDATA_AKSERVER_BASE, 'GUI')
CONFIG_FILE = os.path.join(GUI_CONFIG_PATH, "AkServer_config.json")

DEFAULT_SAVE_DIR_SERVER = os.path.join(os.path.expanduser("~"), "AkServerUploads") # User-specific default
AUTH_ENABLED_FOR_SERVER = True
TRIAL_DURATION_DAYS = 60 # Should match server
APP_NAME_FOR_TRIAL = "AkServer" # Consistent name for shared trial status
FEEDBACK_URL = "https://forms.gle/mWgUnNddhLbAyg3x8" # <-- Add your feedback URL here

# --- Global Variables ---
root = None
# server_process = None # GUI will no longer directly manage server process via Popen primarily
app_icon_tk_ref = None # Keep a reference to the app icon
logo_image_tk = None # To keep a reference to the logo image
# server_lock = threading.Lock() # Less critical if not managing Popen process as strictly
server_button = None
server_status_label = None
otp_display_label_settings = None
generate_otp_button_settings = None
BUTTON_COLORS = {"start": SUCCESS, "stop": DANGER}
PORT = 8443

# Globals for Connected Devices page
trusted_devices_tree = None
active_sessions_tree = None
last_updated_time = None  # To store last updated time for status bar
ACTIVE_SESSION_RECENCY_THRESHOLD_SECONDS = 5 * 60  # 5 minutes for a session to be considered "recently active"

# --- TrialManager Class (Integrated) ---
class TrialManager:
    """
    Manages a trial period for an application.
    Stores the first run date in a file in the user's local app data directory.
    """
    def __init__(self, app_name: str, trial_duration_days: int = 15):
        """
        Initializes the TrialManager.

        Args:
            app_name (str): The name of the application. Used to create a unique storage folder.
            trial_duration_days (int): The duration of the trial period in days.
        """
        self.app_name = app_name
        self.trial_duration_days = trial_duration_days
        self._storage_dir = self._get_storage_directory()
        self._trial_file_path = os.path.join(self._storage_dir, "trial_info.json")
        
        # Ensure storage directory exists
        if not os.path.exists(self._storage_dir):
            try:
                os.makedirs(self._storage_dir, exist_ok=True)
            except OSError as e:
                print(f"Error creating primary trial storage directory {self._storage_dir}: {e}")
                # Fallback to application path if appdata fails (e.g., permissions)
                self._storage_dir = APPLICATION_PATH
                self._trial_file_path = os.path.join(self._storage_dir, f"{self.app_name}_trial_info_gui_fallback.json") # Distinct fallback filename
                if not os.path.exists(self._storage_dir): # Try creating fallback dir
                    try:
                        os.makedirs(self._storage_dir, exist_ok=True)
                    except OSError as e_fallback:
                        print(f"Error creating fallback trial storage directory {self._storage_dir}: {e_fallback}")
                        # At this point, trial functionality might be compromised,
                        # as _trial_file_path might not be writable.
                        # _read_first_run_date and _write_first_run_date will handle IOErrors.


    def _get_storage_directory(self) -> str:
        """Determines the appropriate directory for storing trial information."""
        if sys.platform == "win32":
            base_path = os.getenv('LOCALAPPDATA')
        elif sys.platform == "darwin": # macOS
            base_path = os.path.expanduser('~/Library/Application Support')
        else: # Linux and other Unix-like
            base_path = os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        
        if not base_path: # Fallback if environment variable is not set
            base_path = os.path.expanduser("~")
            
        return os.path.join(base_path, self.app_name)

    def _read_first_run_date(self) -> datetime.date | None:
        """Reads the first run date from the trial file."""
        if not os.path.exists(self._trial_file_path):
            return None
        try:
            with open(self._trial_file_path, 'r') as f:
                data = json.load(f)
                first_run_str = data.get("first_run_date")
                if first_run_str:
                    return datetime.date.fromisoformat(first_run_str)
        except (json.JSONDecodeError, IOError, ValueError) as e:
            print(f"Error reading trial file: {e}")
        return None

    def _write_first_run_date(self, date_to_write: datetime.date) -> None:
        """Writes the first run date to the trial file."""
        try:
            with open(self._trial_file_path, 'w') as f:
                json.dump({"first_run_date": date_to_write.isoformat()}, f)
        except IOError as e:
            print(f"Error writing trial file: {e}")

    def start_trial_if_not_started(self) -> None:
        """If the trial hasn't started (no first run date recorded), records today as the first run date."""
        if self._read_first_run_date() is None:
            today = datetime.date.today()
            self._write_first_run_date(today)
            print(f"Trial started on: {today.isoformat()}")

    def get_trial_status(self) -> tuple[bool, int | None, datetime.date | None]:
        """
        Checks the status of the trial period.

        Returns:
            tuple[bool, int | None, datetime.date | None]: 
                - is_active (bool): True if the trial is currently active, False otherwise.
                - days_remaining (int | None): Number of days remaining in the trial. None if trial not started or expired.
                - expiry_date (datetime.date | None): The date when the trial expires. None if not started.
        """
        first_run_date = self._read_first_run_date()
        if first_run_date is None:
            # Trial not started or file unreadable
            return False, None, None 

        today = datetime.date.today()
        expiry_date = first_run_date + datetime.timedelta(days=self.trial_duration_days)
        
        if today >= expiry_date:
            return False, 0, expiry_date # Trial expired

        days_remaining = (expiry_date - today).days
        return True, days_remaining, expiry_date

# --- Configuration Management ---
def load_config():
    global DEFAULT_SAVE_DIR_SERVER
    try:
        os.makedirs(GUI_CONFIG_PATH, exist_ok=True) # Ensure directory exists
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                DEFAULT_SAVE_DIR_SERVER = config.get("save_dir", DEFAULT_SAVE_DIR_SERVER)
        else: # If config doesn't exist, save defaults
            save_config()
    except Exception as e:
        print(f"Error loading config: {e}. Using defaults.")
        # Attempt to save defaults if loading failed significantly
        save_config()

def save_config():
    config = {"save_dir": DEFAULT_SAVE_DIR_SERVER}
    try:
        os.makedirs(GUI_CONFIG_PATH, exist_ok=True) # Ensure directory exists
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")
# --- Utility Functions ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = APPLICATION_PATH
    return os.path.join(base_path, relative_path)

def clear_frame(frame):
    for widget in frame.winfo_children():
        widget.destroy()

def update_server_ui_state(is_running, status_text=None, status_color="black"):
    global server_button, server_status_label
    if server_button and server_status_label:
        try:
            if not server_button.winfo_exists() or not server_status_label.winfo_exists():
                return # Widgets might have been destroyed
            server_button.config(
                text="Stop Server" if is_running else "Start Server",
                bootstyle=BUTTON_COLORS["stop" if is_running else "start"]
            )
        except tk.TclError:
            return
        default_text, default_color = ("Server Online", SUCCESS) if is_running else ("Server Offline", DANGER)
        if is_running and AUTH_ENABLED_FOR_SERVER and "OTP" not in (status_text or ""):
            # If server is running and auth is on, but no specific OTP message,
            # it might be better to show a generic "Server Online" or "Server Online (Auth Enabled)"
            # The OTP message is now handled by the API response.
            default_text, default_color = "Server Online", SUCCESS # Or WARNING if you want to indicate auth is on
        try:
            server_status_label.config(text=status_text or default_text, bootstyle=status_color or default_color)
        except tk.TclError:
            pass

def check_server_status_api():
    """Checks server status via API and updates UI."""
    if not root or not server_status_label or not server_status_label.winfo_exists():
        return # GUI not ready

    try:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(f"https://127.0.0.1:{PORT}/api/status", context=context, timeout=2) as response:
            if response.status == 200:
                # data = json.loads(response.read().decode()) # Optional: use data if needed
                root.after(0, lambda: update_server_ui_state(True))
                return True
            else:
                root.after(0, lambda: update_server_ui_state(False, status_text="Server Unresponsive", status_color=WARNING))
                return False
    except Exception:
        root.after(0, lambda: update_server_ui_state(False, status_text="Server Offline/Unreachable", status_color=DANGER))
        return False

def periodic_status_check():
    """Periodically checks server status."""
    check_server_status_api()
    if root: # Check if root window still exists
        root.after(15000, periodic_status_check) # Check every 15 seconds

def start_server_logic():
    """Attempts to start the server if it's not running."""
    # --- Debugging ---
    is_frozen_debug = getattr(sys, 'frozen', False)
    executable_path_for_debug = sys.executable
    # APPLICATION_PATH is a global, its value depends on when it was set (at script load)
    application_path_for_debug = APPLICATION_PATH 
    debug_message = (
        f"Debug Info for start_server_logic:\n"
        f"sys.frozen: {is_frozen_debug}\n"
        f"sys.executable: {executable_path_for_debug}\n"
        f"APPLICATION_PATH (global): {application_path_for_debug}\n"
        f"Current working directory: {os.getcwd()}"
    )
    # messagebox.showinfo("Startup Debug", debug_message) # Comment out for release
    # --- End Debugging ---

    # --- Trial Check before attempting to start server ---
    trial_manager_server_check = TrialManager(app_name=APP_NAME_FOR_TRIAL, trial_duration_days=TRIAL_DURATION_DAYS)
    is_active, _, expiry_date = trial_manager_server_check.get_trial_status()
    if not is_active and expiry_date: # Expired
        messagebox.showerror("Trial Expired", f"Your trial period for AkServer expired on {expiry_date.isoformat()}.\nPlease purchase a license to continue using the server.")
        update_server_ui_state(False, status_text="Trial Expired", status_color=DANGER)
        return
    
    # Removed the pre-check: if check_server_status_api(): ... return
    # This allows the start attempt to proceed more quickly.
    # The server itself will handle port conflicts if already running.

    # Determine the command to run the server
    server_command_list = []
    if getattr(sys, 'frozen', False): # Bundled application
        # When bundled, PyInstaller creates AkServer.exe from AkServer.py (due to --name AkServer)
        # Both AkServer_GUI.exe and AkServer.exe will be in APPLICATION_PATH after installation.
        server_exe_name = "AkServer.exe" 
        server_executable_path = os.path.join(APPLICATION_PATH, server_exe_name)
        if not os.path.exists(server_executable_path):
            messagebox.showerror("Error", f"Server executable not found: {server_executable_path}")
            update_server_ui_state(False, status_text="Server Executable Missing", status_color=DANGER)
            return
        server_command_list = [server_executable_path]
    else: # Running as a script
        server_script_path = os.path.join(APPLICATION_PATH, SERVER_SCRIPT_NAME)
        if not os.path.exists(server_script_path):
            messagebox.showerror("Error", f"Server script not found: {server_script_path}")
            update_server_ui_state(False, status_text="Server Script Missing", status_color=DANGER)
            return
        server_command_list = [sys.executable, server_script_path]

    try:
        # Set environment variables for the server process if needed
        server_env = os.environ.copy()
        server_env['AkServer_SAVE_DIR'] = DEFAULT_SAVE_DIR_SERVER # GUI passes its configured save dir
        server_env['AkServer_AUTH_ENABLED'] = 'true' if AUTH_ENABLED_FOR_SERVER else 'false'

        subprocess.Popen(server_command_list, env=server_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        # Optimistically update UI and let periodic check confirm
        root.after(500, lambda: update_server_ui_state(True)) 
    except Exception as e:
        messagebox.showerror("Error", f"Failed to start server: {e}")
        root.after(0, lambda: update_server_ui_state(False, status_text="Server Start Failed", status_color=DANGER))

def stop_server_logic():
    """Sends a shutdown command to the server via API."""
    # update_server_ui_state(True, status_text="Stopping Server...", status_color=WARNING) # Removed for simpler flow
    try:
        context = ssl._create_unverified_context()
        req = urllib.request.Request(f"https://127.0.0.1:{PORT}/api/shutdown", method='POST')
        # Add a small timeout to prevent GUI from hanging indefinitely if server is unresponsive
        with urllib.request.urlopen(req, context=context, timeout=5) as response:
            if response.status == 200:
                # Directly update to "Server Offline" on successful shutdown signal
                root.after(0, lambda: update_server_ui_state(False))
                # root.after(2000, check_server_status_api) # Removed, periodic check will handle
            else:
                # Server responded but indicated failure
                error_body = response.read().decode()
                try:
                    error_detail = json.loads(error_body).get("message", "Unknown error")
                except json.JSONDecodeError:
                    error_detail = error_body if error_body else "Unknown error"
                message = f"Server shutdown failed (HTTP {response.status}): {error_detail}"
                root.after(0, lambda: update_server_ui_state(True, status_text=message, status_color=DANGER))
                messagebox.showerror("Shutdown Error", message)

    except urllib.error.URLError as e: # Catches connection errors, timeouts
        error_msg = f"Failed to connect to server to send shutdown: {e.reason}"
        root.after(0, lambda: update_server_ui_state(True, status_text=error_msg, status_color=DANGER)) # Assume server still running if we can't connect
        messagebox.showerror("Shutdown Error", error_msg)
    except Exception as e:
        error_msg = f"An unexpected error occurred during shutdown: {str(e)}"
        root.after(0, lambda: update_server_ui_state(True, status_text=error_msg, status_color=DANGER))
        messagebox.showerror("Shutdown Error", error_msg)
    finally:
        pass # Removed delayed check_server_status_api, periodic check will handle


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def _get_error_message_from_http_exception(e, default_message_prefix="Error"):
    """Extracts a detailed error message from an HTTPError or similar exception object."""
    try:
        # For urllib.error.HTTPError, e.read() gives the body
        error_body = e.read().decode()
        error_detail = json.loads(error_body).get("message", getattr(e, 'reason', str(e)))
        return f"{default_message_prefix} {getattr(e, 'code', '')}: {error_detail}".strip()
    except Exception: # Includes JSONDecodeError, AttributeError if .read() not present, etc.
        if hasattr(e, 'code') and hasattr(e, 'reason'):
            return f"{default_message_prefix} {e.code}: {e.reason}"
        elif hasattr(e, 'reason'):
             return f"{default_message_prefix}: {e.reason}"
        return f"{default_message_prefix}: {str(e)}"

def _handle_api_error(e, status_label_ref, root_window_ref, error_prefix, clear_ui_callback=None):
    """Handles common error patterns for API calls in the GUI."""
    if isinstance(e, urllib.error.HTTPError):
        error_message = _get_error_message_from_http_exception(e, error_prefix)
    else: # General Exception
        error_message = f"{error_prefix} (General Error): {str(e)}"
    
    if status_label_ref and root_window_ref and status_label_ref.winfo_exists():
        root_window_ref.after(0, lambda msg=error_message: status_label_ref.config(text=msg, bootstyle=DANGER))
    
    if clear_ui_callback and root_window_ref:
        if callable(clear_ui_callback):
            root_window_ref.after(0, clear_ui_callback)

def _send_otp_request_to_server():
    try:
        ip_address = get_local_ip() # The GUI should always use localhost or 127.0.0.1 to talk to its server
        url = f"https://127.0.0.1:{PORT}/request_otp" # Using 127.0.0.1 for GUI initiated OTP request
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(url, context=context, timeout=10) as response:
            response_data_raw = response.read().decode()
            if response.status == 200:
                data = json.loads(response_data_raw)
                if data.get("success") and data.get("otp"):
                    root.after(0, lambda ov=data["otp"]: update_settings_otp_display(ov))
                elif data.get("message"):
                     root.after(0, lambda msg=data["message"]: messagebox.showwarning("OTP Request Info", msg))
                else:
                    root.after(0, lambda: messagebox.showwarning("OTP Request Info", f"Server response: {response.status}\n{response_data_raw}"))
            else: 
                root.after(0, lambda sr=response_data_raw: messagebox.showwarning("OTP Request Info", f"Server response: {response.status}\n{sr}"))
    except urllib.error.HTTPError as e_http:
        _handle_api_error(e_http, otp_display_label_settings, root, "OTP Request HTTPError", clear_settings_otp_display)
    except Exception as e:
        _handle_api_error(e, otp_display_label_settings, root, "Failed to request OTP", clear_settings_otp_display)

def handle_generate_otp_request():
    if check_server_status_api(): # Check if server is running before requesting OTP
        if generate_otp_button_settings:
            generate_otp_button_settings.pack_forget()  # Hide the button
        if otp_display_label_settings:
            otp_display_label_settings.config(text="Requesting OTP...", bootstyle=WARNING)
            otp_display_label_settings.pack(pady=(5,0))  # Show the label
        threading.Thread(target=_send_otp_request_to_server, daemon=True).start()
    else:
        messagebox.showerror("Server Offline", "Cannot request OTP, server is not running or unreachable.")
        clear_settings_otp_display() # Reset UI if server is offline

def update_settings_otp_display(otp_value):
    if AUTH_ENABLED_FOR_SERVER and otp_display_label_settings:
        otp_display_label_settings.config(text=f"OTP: {otp_value}", bootstyle=INFO)
        otp_display_label_settings.pack(pady=(5, 0))
        root.after(10000, clear_settings_otp_display)

def clear_settings_otp_display():
    if otp_display_label_settings:
        otp_display_label_settings.config(text="")
        otp_display_label_settings.pack_forget()  # Hide the label
    if AUTH_ENABLED_FOR_SERVER and generate_otp_button_settings:
        generate_otp_button_settings.pack()  # Show the button again

# --- UI Functions ---
def display_settings_ui(parent_frame, root_window):
    global otp_display_label_settings, generate_otp_button_settings
    clear_frame(parent_frame)
    root_window.title("Settings")
    
    ttk.Button(parent_frame, text="⬅ Back", bootstyle=INFO, command=lambda: display_main_app_ui(parent_frame, root_window)).pack(side=TOP, anchor=NW, padx=10, pady=(5, 5))
    
    # Frame to hold the QR code and URL, initially hidden
    qr_url_frame = ttk.Frame(parent_frame)

    local_ip = get_local_ip()
    server_url = f"https://{local_ip}:{PORT}/login" if AUTH_ENABLED_FOR_SERVER else f"https://{local_ip}:{PORT}/"
    qr = qrcode.QRCode(box_size=3, border=2)
    qr.add_data(server_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_img_tk = ImageTk.PhotoImage(qr_img)
    qr_label = ttk.Label(qr_url_frame, image=qr_img_tk)
    qr_label.image = qr_img_tk
    qr_label.pack(pady=(5,0))
    ttk.Label(qr_url_frame, text=f"Scan to connect: {server_url}", font=("Helvetica", 9)).pack(pady=(2, 5))

    # OTP section (do not pack yet)
    otp_section_frame = ttk.Frame(parent_frame)
    otp_display_label_settings = ttk.Label(
        otp_section_frame, text="", font=("Helvetica", 12, "bold"), bootstyle=INFO
    )

    generate_otp_button_settings = ttk.Button(
        otp_section_frame, text="Gen Code", bootstyle=PRIMARY, command=handle_generate_otp_request
    )
    if AUTH_ENABLED_FOR_SERVER:
        generate_otp_button_settings.pack()

    # Button to reveal QR code and URL (and OTP section)
    def show_qr_and_otp():
        connect_button.pack_forget()
        qr_url_frame.pack(pady=(5,0))
        otp_section_frame.pack(pady=5)

    connect_button = ttk.Button(parent_frame, text="Connect", bootstyle=PRIMARY, command=show_qr_and_otp)
    connect_button.pack(pady=(10, 5))

    folder_var = tk.StringVar(value=DEFAULT_SAVE_DIR_SERVER)
    def choose_folder():
        folder_selected = filedialog.askdirectory(parent=root_window, title="Select Sync Folder")
        if folder_selected:
            folder_var.set(folder_selected)
            global DEFAULT_SAVE_DIR_SERVER
            DEFAULT_SAVE_DIR_SERVER = folder_selected
            save_config() # Save the new path
            messagebox.showinfo("Sync Folder Changed", f"Sync folder set to:\n{folder_selected}\n\nRestart the server to apply.")
    
    folder_frame = ttk.LabelFrame(parent_frame, text="Sync Folder Location", padding=10)
    folder_frame.pack(side=BOTTOM, fill=X, padx=10, pady=(5,5))
    ttk.Label(folder_frame, textvariable=folder_var, wraplength=300, anchor=W).pack(side=LEFT, padx=(0, 5), fill=X, expand=True)
    ttk.Button(folder_frame, text="Select Path", bootstyle=SECONDARY, command=choose_folder).pack(side=LEFT, padx=5)

def _fetch_devices_from_server_thread(status_label_ref, root_window_ref, refresh_button_ref=None):
    global trusted_devices_tree, active_sessions_tree, last_updated_time
    try:
        if refresh_button_ref:
            root_window_ref.after(0, lambda: refresh_button_ref.config(text="Refreshing...", state=DISABLED, bootstyle=(SECONDARY, OUTLINE)))

        ip_address = "127.0.0.1" # GUI always queries localhost for device management
        url = f"https://{ip_address}:{PORT}/api/devices"
        # Using _create_unverified_context as GUI connects to localhost with self-signed cert.
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url)
        root_window_ref.after(0, lambda: status_label_ref.config(text="Refreshing device list...", bootstyle=INFO))
        
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                root_window_ref.after(0, lambda d=data, slr=status_label_ref: _update_devices_ui(d, slr))
                last_updated_time = time.strftime("%I:%M %p")
                if data.get("trusted_devices") or data.get("active_otp_sessions"):
                    root_window_ref.after(0, lambda: status_label_ref.config(text="Device list updated.", bootstyle=SUCCESS))
                else:
                    root_window_ref.after(0, lambda: status_label_ref.config(text="No connected devices found.", bootstyle=INFO))
    except Exception as e:
        _handle_api_error(e, status_label_ref, root_window_ref, "Failed to refresh list", _clear_devices_ui)
    finally:
        if refresh_button_ref and refresh_button_ref.winfo_exists():
            root_window_ref.after(0, lambda: refresh_button_ref.config(text="Refresh", state=NORMAL, bootstyle=(SECONDARY, OUTLINE)))

def _update_devices_ui(data, status_label_ref):
    device_type_icons = {
        "laptop": "💻",
        "phone": "📱",
        "default": "🖥️"
    }

    if trusted_devices_tree:
        for widget in trusted_devices_tree.winfo_children():
            widget.destroy()
        if data.get("trusted_devices"):
            for device in data["trusted_devices"]:
                trusted_device_name = device.get("name", "Unnamed Device")
                token_partial = device.get("token_partial", "N/A")
                device_type = device.get("device_type", "laptop")  # Assume server provides this
                icon = device_type_icons.get(device_type, device_type_icons["default"])

                # Create a card-like frame for each device
                device_frame = ttk.Frame(trusted_devices_tree, borderwidth=1, relief=SOLID, padding=5)
                device_frame.pack(fill=X, pady=2, padx=2)

                # Device icon and name
                device_label = ttk.Label(device_frame, text=f"{icon} {trusted_device_name}", font=("Helvetica", 12))
                device_label.pack(side=LEFT, padx=5)

                # Forget button
                forget_button = ttk.Button(
                    device_frame, text="Forget", bootstyle=DANGER,
                    command=lambda tp=token_partial, slr=status_label_ref: threading.Thread(
                        target=_forget_device_thread, args=(tp, slr, root), daemon=True
                    ).start()
                )
                forget_button.pack(side=RIGHT, padx=5)

        else:
            ttk.Label(trusted_devices_tree, text="No trusted devices found.", bootstyle=INFO).pack(pady=10)

    if active_sessions_tree:
        for widget in active_sessions_tree.winfo_children():
            widget.destroy()
        
        active_sessions_data = data.get("active_otp_sessions")
        displayed_sessions_count = 0
        if active_sessions_data:
            for session in active_sessions_data:
                last_seen_s = session.get("last_seen_ago_s", float('inf'))

                if last_seen_s < ACTIVE_SESSION_RECENCY_THRESHOLD_SECONDS:
                    session_display_name = session.get("name", "N/A")
                    active_for_m = round(last_seen_s / 60)
                    device_type = session.get("device_type", "phone") 
                    session_started_at = session.get("session_started_at", "Unknown") 
                    icon = device_type_icons.get(device_type, device_type_icons["default"])

                    session_frame = ttk.Frame(active_sessions_tree, borderwidth=1, relief=SOLID, padding=5)
                    session_frame.pack(fill=X, pady=2, padx=2)

                    session_label_text = f"{icon} {session_display_name}"
                    session_label = ttk.Label(session_frame, text=session_label_text, font=("Helvetica", 12))
                    session_label.pack(side=LEFT, padx=5)

                    details_text = f"Session Started: {session_started_at} | Last Seen: ~{active_for_m} min ago"
                    details_label = ttk.Label(session_frame, text=details_text, font=("Helvetica", 10), bootstyle=SECONDARY)
                    details_label.pack(side=LEFT, padx=5)

                    status_dot = ttk.Label(session_frame, text="●", foreground="green", font=("Helvetica", 12))
                    status_dot.pack(side=RIGHT, padx=5)
                    displayed_sessions_count += 1
        
        if displayed_sessions_count == 0:
            ttk.Label(active_sessions_tree, text="No recently active sessions found.", bootstyle=INFO).pack(pady=10)

def _clear_devices_ui():
    if trusted_devices_tree:
        for widget in trusted_devices_tree.winfo_children():
            widget.destroy()
        ttk.Label(trusted_devices_tree, text="No trusted devices found (or error fetching).", bootstyle=INFO).pack(pady=10)
    if active_sessions_tree:
        for widget in active_sessions_tree.winfo_children():
            widget.destroy()
        ttk.Label(active_sessions_tree, text="No active sessions found (or error fetching).", bootstyle=INFO).pack(pady=10)

def _forget_device_thread(token_partial, status_label_ref, root_window_ref):
    try:
        ip_address = "127.0.0.1" # GUI always queries localhost
        url = f"https://{ip_address}:{PORT}/api/devices/forget"
        payload = json.dumps({"token_partial": token_partial}).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        # Using _create_unverified_context as GUI connects to localhost with self-signed cert.
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        
        root_window_ref.after(0, lambda: status_label_ref.config(text=f"Forgetting {token_partial}...", bootstyle=WARNING))
        
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            if response.status == 200:
                root_window_ref.after(0, lambda: status_label_ref.config(text=f"Device {token_partial} forgotten. Refreshing list...", bootstyle=SUCCESS))
                # Refresh the list
                root_window_ref.after(0, lambda: threading.Thread(target=_fetch_devices_from_server_thread, args=(status_label_ref, root_window_ref, None), daemon=True).start())
    except Exception as e:
        _handle_api_error(e, status_label_ref, root_window_ref, f"Error forgetting {token_partial}")

def display_connected_devices_ui(parent_frame, root_window):
    global trusted_devices_tree, active_sessions_tree
    clear_frame(parent_frame)
    root_window.title("Connected Devices Management")

    # Top Bar with Back and Refresh Buttons
    top_bar = ttk.Frame(parent_frame)
    top_bar.pack(side=TOP, fill=X, pady=(5, 10))
    ttk.Button(top_bar, text="⬅ Back", bootstyle=INFO, command=lambda: display_main_app_ui(parent_frame, root_window)).pack(side=LEFT, padx=10)
    
    local_status_label_devices = ttk.Label(top_bar, text="Loading device data...", bootstyle=INFO)
    local_status_label_devices.pack(side=LEFT, padx=10, expand=True, fill=X)
    
    refresh_button = ttk.Button(top_bar, text="Refresh", bootstyle=(SECONDARY, OUTLINE))
    refresh_button.config(command=lambda: threading.Thread(target=_fetch_devices_from_server_thread, args=(local_status_label_devices, root_window, refresh_button), daemon=True).start())
    refresh_button.pack(side=RIGHT, padx=10)

    # Trusted Devices Section
    trusted_frame = ttk.LabelFrame(parent_frame, text="Trusted Devices", padding=10)
    trusted_frame.pack(pady=5, padx=5, fill=BOTH, expand=True)
    trusted_devices_tree = ttk.Frame(trusted_frame)
    trusted_devices_tree.pack(fill=BOTH, expand=True)

    # Active Sessions Section
    active_frame = ttk.LabelFrame(parent_frame, text="Active Sessions", padding=10)
    active_frame.pack(pady=5, padx=5, fill=BOTH, expand=True)
    active_sessions_tree = ttk.Frame(active_frame)
    active_sessions_tree.pack(fill=BOTH, expand=True)

    threading.Thread(target=_fetch_devices_from_server_thread, args=(local_status_label_devices, root_window, refresh_button), daemon=True).start()

def display_main_app_ui(parent_frame, root_window):
    global server_button, server_status_label
    global logo_image_tk

    clear_frame(parent_frame)
    root_window.title("AkServer Dashboard (beta Version 0.1)")

    # --- Header Frame for Logo and Title ---
    header_frame = ttk.Frame(parent_frame)
    header_frame.pack(pady=(10, 5)) # Adjust padding as needed

    try:
        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            logo_pil = Image.open(logo_path)
            desired_height = 45 
            aspect_ratio = logo_pil.width / logo_pil.height
            desired_width = int(desired_height * aspect_ratio)
            logo_pil_resized = logo_pil.resize((desired_width, desired_height), Image.Resampling.LANCZOS)
            
            logo_image_tk = ImageTk.PhotoImage(logo_pil_resized) # Assign to global
            
            logo_label_header = ttk.Label(header_frame, image=logo_image_tk)
            logo_label_header.pack(side=LEFT, padx=(0, 10))
    except Exception as e:
        print(f"Error loading or placing logo in header: {e}")

    ttk.Label(header_frame, text="AkServer", font=("Helvetica", 18, "bold")).pack(side=LEFT)

    # --- Trial Status Display ---
    trial_status_frame_gui = ttk.Frame(parent_frame)
    trial_status_frame_gui.pack(pady=(0, 10), fill=X, padx=20)

    gui_trial_manager = TrialManager(app_name=APP_NAME_FOR_TRIAL, trial_duration_days=TRIAL_DURATION_DAYS)
    is_gui_trial_active, gui_days_remaining, gui_trial_expiry_date = gui_trial_manager.get_trial_status()
    
    trial_text = "Trial status: Unknown"
    trial_style = WARNING # ttkbootstrap style constant
    if not is_gui_trial_active and gui_trial_expiry_date:
        trial_text = f"Trial Expired on {gui_trial_expiry_date.isoformat()}"
        trial_style = DANGER
    elif is_gui_trial_active and gui_days_remaining is not None:
        trial_text = f"Trial Active: {gui_days_remaining} days remaining."
        trial_style = SUCCESS
    
    ttk.Label(trial_status_frame_gui, text=trial_text, font=("Helvetica", 9), bootstyle=trial_style, anchor="center").pack(fill=X)

    # Tagline Block
    tagline_frame = ttk.Frame(parent_frame, padding=(12, 10), bootstyle="light")
    tagline_frame.pack(pady=(5, 15), padx=20, fill=X)

    ttk.Label(
        tagline_frame,
        text="We empower you to establish your very own, completely private file storage system, operating entirely on your local network \n– Your Files, Your Network, Your Control.",
        font=("Helvetica", 10, "italic"),
        bootstyle=DARK,
        wraplength=340,
        justify="center"
    ).pack(expand=True, fill=BOTH)

    # --- Button Block ---
    button_block_frame = ttk.Frame(parent_frame, padding=(0, 10))
    button_block_frame.pack(pady=(15, 10), fill=X, padx=20)

    # Create two columns within the block
    left_button_column = ttk.Frame(button_block_frame)
    left_button_column.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))

    right_button_column = ttk.Frame(button_block_frame)
    right_button_column.pack(side=RIGHT, fill=BOTH, expand=True, padx=(5, 0))

    button_height_padding = (10, 7) # (left/right, top/bottom) internal padding
    button_common_width = 16 # Adjusted width to fit two side-by-side

    # Left Column Buttons
    server_button = ttk.Button(
        left_button_column,
        text="Start Server", 
        bootstyle=BUTTON_COLORS["start"], 
        width=button_common_width,
        padding=button_height_padding,
        command=lambda: start_server_logic() if server_button["text"] == "Start Server" else stop_server_logic(),
    )
    server_button.pack(pady=(0, 5), fill=X, expand=True)

    ttk.Button(left_button_column, text="Linked Devices", bootstyle=(INFO, OUTLINE), width=button_common_width, padding=button_height_padding, command=lambda: display_connected_devices_ui(parent_frame, root_window)).pack(pady=(5, 0), fill=X, expand=True)

    # Right Column Buttons
    ttk.Button(right_button_column, text="Settings", bootstyle=(INFO, OUTLINE), width=button_common_width, padding=button_height_padding, command=lambda: display_settings_ui(parent_frame, root_window)).pack(pady=(0, 5), fill=X, expand=True)
    ttk.Button(right_button_column, text="Provide Feedback", bootstyle=(SECONDARY, OUTLINE), width=button_common_width, padding=button_height_padding, command=lambda: webbrowser.open(FEEDBACK_URL)).pack(pady=(5, 0), fill=X, expand=True)

    # Ensure UI reflects current server state if already known
    # This will be handled by the initial call to check_server_status_api in main()
    # and subsequent periodic checks.
    # is_server_running = server_process and server_process.poll() is None # No longer using server_process this way
    # update_server_ui_state(is_server_running) # Initial state will be set by check_server_status_api

def on_gui_close_actions():
    """Actions to perform when GUI is closing. Does NOT stop the server."""
    # Server is designed to run independently. GUI close should not affect it.
    # If there were GUI-specific resources to clean up, they'd go here.
    if root:
        root.destroy()

def main():
    global root, server_status_label, logo_image_tk, app_icon_tk_ref

    load_config()

    # --- Initialize and Check Trial Period ---
    trial_manager = TrialManager(app_name=APP_NAME_FOR_TRIAL, trial_duration_days=TRIAL_DURATION_DAYS)
    trial_manager.start_trial_if_not_started() # Ensures first run date is set
    is_trial_active, days_remaining, trial_expiry_date = trial_manager.get_trial_status()

    if not is_trial_active and trial_expiry_date: # Trial has started and expired
        messagebox.showerror("Trial Expired", f"Your trial period for AkServer GUI expired on {trial_expiry_date.isoformat()}.\nServer functionality might be affected if its trial also expired.")
    # elif is_trial_active and days_remaining is not None: # Suppressed for cleaner flow
        # print(f"Trial Active: {days_remaining} days remaining.") # Optional: log to console instead


    # --- Initialize GUI ---
    root = Window(themename="flatly") 
    root.title("AkServer Control")
    root.geometry("450x410")
    root.resizable(False, False)

    # --- Set Application Icon (More Robustly) ---
    try:
        icon_path_png = resource_path("app_icon.png")
        icon_path_ico = resource_path("app_icon.ico") # For Windows

        icon_set = False
        # On Windows, try .ico first as it's often more reliable
        if sys.platform == "win32" and os.path.exists(icon_path_ico):
            try:
                root.iconbitmap(icon_path_ico)
                icon_set = True
                print(f"Application icon set using '{os.path.basename(icon_path_ico)}'.")
            except Exception as e_ico:
                print(f"Error setting .ico application icon: {e_ico}. Will try .png.")
        
        # Fallback to .png if .ico failed or not on Windows
        if not icon_set and os.path.exists(icon_path_png):
            try:
                app_icon_pil = Image.open(icon_path_png)
                # Convert to RGBA to handle transparency consistently, can help with rendering
                if app_icon_pil.mode != 'RGBA':
                    app_icon_pil = app_icon_pil.convert('RGBA')

                app_icon_tk_ref = ImageTk.PhotoImage(app_icon_pil) # Store in global
                root.iconphoto(True, app_icon_tk_ref) # True makes it default
                icon_set = True
                print(f"Application icon set using '{os.path.basename(icon_path_png)}'.")
            except Exception as e_png:
                print(f"Error setting .png application icon: {e_png}")

        if not icon_set:
            if not os.path.exists(icon_path_ico) and not os.path.exists(icon_path_png):
                print(f"No application icon file found (expected 'app_icon.ico' or 'app_icon.png' at {APPLICATION_PATH}).")
            elif sys.platform == "win32" and not os.path.exists(icon_path_ico) and not icon_set:
                 print(f"Application icon 'app_icon.ico' not found or failed to load. Check path: {icon_path_ico}")
            elif not os.path.exists(icon_path_png) and not icon_set:
                 print(f"Application icon 'app_icon.png' not found or failed to load. Check path: {icon_path_png}")
    except Exception as e:
        print(f"General error during application icon setup: {e}")

    content_frame = ttk.Frame(root, padding=20)
    content_frame.pack(fill=BOTH, expand=True)

    # Copyright label (bottom-most)
    current_year = time.strftime("%Y")
    copyright_label = ttk.Label(
        root,
        text=f"© {current_year} AkServer. All rights reserved.",
        font=("Helvetica", 8),
        bootstyle=SECONDARY,
        anchor="center"
    )
    copyright_label.pack(side=BOTTOM, fill=X)

    # Server status label above copyright and definition
    server_status_label = ttk.Label(root, text="Checking Server Status...", font=("Helvetica", 10), bootstyle=WARNING, relief=SUNKEN, anchor=W, padding=5)
    server_status_label.pack(side=BOTTOM, fill=X)

    display_main_app_ui(content_frame, root)

    # --- Automatically attempt to start the server ---
    root.after(100, start_server_logic) # Short delay to allow GUI to draw first

    root.protocol("WM_DELETE_WINDOW", on_gui_close_actions) # GUI close does not stop server
    
    root.after(500, check_server_status_api) # Initial check of server status
    root.after(15000, periodic_status_check) # Start periodic checks
    
    root.mainloop()

if __name__ == "__main__":
    main()
