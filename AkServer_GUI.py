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
from ttkbootstrap.constants import *
import qrcode
from PIL import ImageTk

APPLICATION_PATH = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = "AkServer.py"
CONFIG_FILE = os.path.join(APPLICATION_PATH, "AkServer_config.json")
DEFAULT_SAVE_DIR_SERVER = os.path.join(os.path.expanduser("~"), "AkServerUploads") # User-specific default
AUTH_ENABLED_FOR_SERVER = True
PORT = 8443

# --- Global Variables ---
root = None
server_process = None
server_lock = threading.Lock()
server_button = None
server_status_label = None
otp_display_label_settings = None
generate_otp_button_settings = None
BUTTON_COLORS = {"start": SUCCESS, "stop": DANGER}

# Globals for Connected Devices page
trusted_devices_tree = None
active_sessions_tree = None
# status_label_devices is created locally in display_connected_devices_ui and passed as a parameter.
last_updated_time = None  # To store last updated time for status bar
ACTIVE_SESSION_RECENCY_THRESHOLD_SECONDS = 5 * 60  # 5 minutes for a session to be considered "recently active"


# --- Configuration Management ---
def load_config():
    global DEFAULT_SAVE_DIR_SERVER
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                DEFAULT_SAVE_DIR_SERVER = config.get("save_dir", DEFAULT_SAVE_DIR_SERVER)
    except Exception as e:
        print(f"Error loading config: {e}. Using defaults.")

def save_config():
    config = {"save_dir": DEFAULT_SAVE_DIR_SERVER}
    try:
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
            if not server_button.winfo_exists() or not server_status_label.winfo_exists(): # Check both
                return # Widgets might have been destroyed
            server_button.config(
                text="Stop Server" if is_running else "Start Server",
                bootstyle=BUTTON_COLORS["stop" if is_running else "start"]
            )
        except tk.TclError:
            return
        default_text, default_color = ("Server Online", SUCCESS) if is_running else ("Server Offline", DANGER)
        if is_running and AUTH_ENABLED_FOR_SERVER and "OTP" not in (status_text or ""):
            default_text, default_color = "Server Online", WARNING
        try:
            server_status_label.config(text=status_text or default_text, bootstyle=status_color or default_color)
        except tk.TclError:
            pass

def read_server_output(process, window_ref):
    otp_displayed = False
    while process.poll() is None:
        line = process.stdout.readline().strip()
        if not line:
            break
        if "One-Time Password (OTP):" in line and AUTH_ENABLED_FOR_SERVER:
            otp_value = line.split(":")[-1].strip()
            window_ref.after(0, lambda: update_server_ui_state(True, status_text="Server Online. OTP in Settings.", status_color=INFO))
            window_ref.after(0, lambda ov=otp_value: update_settings_otp_display(ov))
            otp_displayed = True
        elif "server running on https" in line and not (AUTH_ENABLED_FOR_SERVER and otp_displayed):
            window_ref.after(0, lambda: update_server_ui_state(True))
    if process.poll() is not None and root:
        root.after(0, lambda: stop_server_logic(True))

def start_server_logic():
    global server_process
    with server_lock:
        if server_process and server_process.poll() is None:
            return
        server_button.config(state=DISABLED, text="Starting...")
        try:
            server_script_path = resource_path(SERVER_SCRIPT)
            if not os.path.exists(server_script_path):
                raise FileNotFoundError(f"Server script '{SERVER_SCRIPT}' not found.")
            python_exec = sys.executable if hasattr(sys, '_MEIPASS') else "python"
            if not os.path.exists(DEFAULT_SAVE_DIR_SERVER):
                os.makedirs(DEFAULT_SAVE_DIR_SERVER, exist_ok=True)
            server_env = os.environ.copy()
            server_env['AkServer_SAVE_DIR'] = DEFAULT_SAVE_DIR_SERVER
            server_env['AkServer_AUTH_ENABLED'] = 'true' if AUTH_ENABLED_FOR_SERVER else 'false'
            server_process = subprocess.Popen(
                [python_exec, server_script_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                env=server_env, bufsize=1
            )
            time.sleep(0.5)
            if server_process.poll() is not None:
                raise RuntimeError("Server failed to start.")
            root.after(0, lambda: update_server_ui_state(True))
            threading.Thread(target=read_server_output, args=(server_process, root), daemon=True).start()
        except Exception as e:
            root.after(0, lambda: update_server_ui_state(False, status_text="Server Start Failed", status_color=DANGER))
            root.after(0, lambda: messagebox.showerror("Error", f"Failed to start server: {e}"))
            server_process = None
        finally:
            server_button.config(state=NORMAL, text="Start Server" if not server_process else "Stop Server")

def stop_server_logic(update_ui_only_if_needed=False):
    global server_process
    with server_lock:
        process_to_stop = server_process
        server_process = None
        if process_to_stop and process_to_stop.poll() is None:
            process_to_stop.terminate()
            try:
                process_to_stop.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process_to_stop.kill()
                process_to_stop.wait()
            root.after(0, lambda: update_server_ui_state(False)) # Normal stop UI update
        elif update_ui_only_if_needed: # Use elif to avoid double UI update if process was just stopped
            root.after(0, lambda: update_server_ui_state(False, status_text="Server Offline (Unexpected Stop)", status_color=DANGER))

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

def _send_otp_request_to_server():
    try:
        ip_address = get_local_ip()
        url = f"https://{ip_address}:{PORT}/request_otp"
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(url, context=context, timeout=10) as response:
            if response.status != 200: # Basic check, though OTP is confirmed via stdout
                server_response = response.read().decode()
                root.after(0, lambda sr=server_response: messagebox.showwarning("OTP Request Info", f"Server response: {response.status}\n{sr}"))
    except urllib.error.HTTPError as e_http:
        err_msg = _get_error_message_from_http_exception(e_http, "OTP Request HTTPError")
        root.after(0, lambda: messagebox.showerror("OTP Error", err_msg))
        root.after(0, lambda: clear_settings_otp_display())
    except Exception as e:
        root.after(0, lambda: messagebox.showerror("OTP Error", f"Failed to request OTP (General Error): {e}"))
        root.after(0, lambda: clear_settings_otp_display())

def handle_generate_otp_request():
    if server_process and server_process.poll() is None:
        if generate_otp_button_settings:
            generate_otp_button_settings.pack_forget()  # Hide the button
        if otp_display_label_settings:
            otp_display_label_settings.config(text="Requesting OTP...", bootstyle=WARNING)
            otp_display_label_settings.pack(pady=(5,0))  # Show the label
        threading.Thread(target=_send_otp_request_to_server, daemon=True).start()
    else:
        messagebox.showerror("Server Offline", "Cannot request OTP, server is not running.")

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
    # Do not pack yet

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
    # Do not pack the label yet; only pack when showing OTP

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

        ip_address = "127.0.0.1"
        url = f"https://{ip_address}:{PORT}/api/devices"
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url)
        root_window_ref.after(0, lambda: status_label_ref.config(text="Refreshing device list...", bootstyle=INFO))
        
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                root_window_ref.after(0, lambda d=data, slr=status_label_ref: _update_devices_ui(d, slr))
                last_updated_time = time.strftime("%I:%M %p")  # Update last updated time
                if data.get("trusted_devices") or data.get("active_otp_sessions"):
                    root_window_ref.after(0, lambda: status_label_ref.config(text="Device list updated.", bootstyle=SUCCESS))
                else:
                    root_window_ref.after(0, lambda: status_label_ref.config(text="No connected devices found.", bootstyle=INFO))
            else:
                error_message = f"Error: {response.status} {response.reason}"
                try:
                    error_detail = json.loads(response.read().decode()).get("message", response.reason)
                    error_message = f"Error {response.status}: {error_detail}"
                except:
                    pass
                root_window_ref.after(0, lambda msg=error_message: status_label_ref.config(text=msg, bootstyle=DANGER))
    except urllib.error.HTTPError as e:
        error_message = _get_error_message_from_http_exception(e, "Failed to refresh list")
        root_window_ref.after(0, lambda msg=error_message: status_label_ref.config(text=msg, bootstyle=DANGER))
        root_window_ref.after(0, _clear_devices_ui)
    except Exception as e:
        root_window_ref.after(0, lambda err=str(e): status_label_ref.config(text=f"Failed to refresh list: {err}", bootstyle=DANGER))
        root_window_ref.after(0, _clear_devices_ui)
    finally:
        if refresh_button_ref:
            root_window_ref.after(0, lambda: refresh_button_ref.config(text="Refresh", state=NORMAL, bootstyle=(SECONDARY, OUTLINE)))

def _update_devices_ui(data, status_label_ref):
    # Device type mapping (simulated; you can fetch this from the server)
    device_type_icons = {
        "laptop": "💻",  # Unicode emoji for laptop
        "phone": "📱",   # Unicode emoji for phone
        "default": "🖥️"  # Default device icon
    }

    if trusted_devices_tree:
        for widget in trusted_devices_tree.winfo_children():
            widget.destroy()
        if data.get("trusted_devices"):
            for device in data["trusted_devices"]:
                trusted_device_name = device.get("name", "Unnamed Device")
                token_partial = device.get("token_partial", "N/A")
                # Simulate device type (replace with actual server data if available)
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
                last_seen_s = session.get("last_seen_ago_s", float('inf')) # Default to very old if missing

                # Only display if the session was seen recently
                if last_seen_s < ACTIVE_SESSION_RECENCY_THRESHOLD_SECONDS:
                    session_display_name = session.get("name", "N/A")
                    active_for_m = round(last_seen_s / 60)
                    # Simulate device type and session start time (replace with actual server data if available)
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
    if trusted_devices_tree: # This is a Frame
        for widget in trusted_devices_tree.winfo_children():
            widget.destroy()
        ttk.Label(trusted_devices_tree, text="No trusted devices found (or error fetching).", bootstyle=INFO).pack(pady=10)
    if active_sessions_tree: # This is a Frame
        for widget in active_sessions_tree.winfo_children():
            widget.destroy()
        ttk.Label(active_sessions_tree, text="No active sessions found (or error fetching).", bootstyle=INFO).pack(pady=10)

def _forget_device_thread(token_partial, status_label_ref, root_window_ref):
    try:
        ip_address = "127.0.0.1"
        url = f"https://{ip_address}:{PORT}/api/devices/forget"
        payload = json.dumps({"token_partial": token_partial}).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        
        root_window_ref.after(0, lambda: status_label_ref.config(text=f"Forgetting {token_partial}...", bootstyle=WARNING))
        
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            if response.status == 200:
                root_window_ref.after(0, lambda: status_label_ref.config(text=f"Device {token_partial} forgotten. Refreshing list...", bootstyle=SUCCESS))
                # Refresh the list by calling _fetch_devices_from_server_thread again
                # Pass None for refresh_button_ref as there isn't one directly here, or pass the actual one if available
                root_window_ref.after(0, lambda: threading.Thread(target=_fetch_devices_from_server_thread, args=(status_label_ref, root_window_ref, None), daemon=True).start())
            else:
                # Try to get more details from the response body for non-200 status
                error_message = f"Error forgetting: {response.status}"
                try:
                    error_detail = json.loads(response.read().decode()).get("message", response.reason)
                    error_message = f"Error {response.status}: {error_detail}"
                except: # Fallback if parsing fails
                    pass
                root_window_ref.after(0, lambda msg=error_message: status_label_ref.config(text=msg, bootstyle=DANGER))
    except urllib.error.HTTPError as e_http:
        err_msg = _get_error_message_from_http_exception(e_http, "Error forgetting device")
        root_window_ref.after(0, lambda: status_label_ref.config(text=err_msg, bootstyle=DANGER))
    except Exception as e: # General errors
        root_window_ref.after(0, lambda err=str(e): status_label_ref.config(text=f"Error forgetting {token_partial} (General Error): {err}", bootstyle=DANGER))

def display_connected_devices_ui(parent_frame, root_window):
    global trusted_devices_tree, active_sessions_tree # status_label_devices is local
    clear_frame(parent_frame)
    root_window.title("Connected Devices Management")

    # Top Bar with Back and Refresh Buttons
    top_bar = ttk.Frame(parent_frame)
    top_bar.pack(side=TOP, fill=X, pady=(5, 10))
    ttk.Button(top_bar, text="⬅ Back", bootstyle=INFO, command=lambda: display_main_app_ui(parent_frame, root_window)).pack(side=LEFT, padx=10)
    
    # Local status label for this screen, passed as 'status_label_ref' to other functions
    local_status_label_devices = ttk.Label(top_bar, text="Loading device data...", bootstyle=INFO)
    local_status_label_devices.pack(side=LEFT, padx=10, expand=True, fill=X)
    
    refresh_button = ttk.Button(top_bar, text="Refresh", bootstyle=(SECONDARY, OUTLINE))
    refresh_button.config(command=lambda: threading.Thread(target=_fetch_devices_from_server_thread, args=(local_status_label_devices, root_window, refresh_button), daemon=True).start())
    refresh_button.pack(side=RIGHT, padx=10)

    # Trusted Devices Section
    trusted_frame = ttk.LabelFrame(parent_frame, text="Trusted Devices", padding=10)
    trusted_frame.pack(pady=5, padx=5, fill=BOTH, expand=True)
    trusted_devices_tree = ttk.Frame(trusted_frame)  # Use Frame for card layout
    trusted_devices_tree.pack(fill=BOTH, expand=True)

    # Active Sessions Section
    active_frame = ttk.LabelFrame(parent_frame, text="Active Sessions", padding=10)
    active_frame.pack(pady=5, padx=5, fill=BOTH, expand=True)
    active_sessions_tree = ttk.Frame(active_frame)  # Use Frame for card layout
    active_sessions_tree.pack(fill=BOTH, expand=True)

    # Status Bar at the Bottom - Simplified
    status_bar_frame = ttk.Frame(parent_frame, relief=SUNKEN, padding=(5,2))
    status_bar_frame.pack(side=BOTTOM, fill=X)
    last_updated_label = ttk.Label(status_bar_frame, text="Last Updated: --", bootstyle=SECONDARY)
    last_updated_label.pack(side=RIGHT, padx=5)

    # Update last updated time dynamically
    def update_last_updated():
        if last_updated_label and last_updated_label.winfo_exists() and root_window and root_window.winfo_exists():
            if last_updated_time:
                last_updated_label.config(text=f"Last Updated: {last_updated_time}")
            root_window.after(1000, update_last_updated)
    
    update_last_updated()
    threading.Thread(target=_fetch_devices_from_server_thread, args=(local_status_label_devices, root_window, refresh_button), daemon=True).start()

def display_main_app_ui(parent_frame, root_window):
    global server_button, server_status_label
    clear_frame(parent_frame)
    root_window.title("AkServer Dashboard (beta Version 0.1)")

    ttk.Label(parent_frame, text="AkServer", font=("Helvetica", 16, "bold")).pack(pady=(10, 20))

    # Software definition label just above the server status label, inside the main frame
    ttk.Label(
        parent_frame,
        text="We empower you to establish your very own, completely private file storage system, operating entirely on your local network \n– no internet required.",
        font=("Helvetica", 10, "italic"),
        bootstyle=SECONDARY,
        wraplength=380,
        #justify="center",
        #anchor="center"
    ).pack(pady=(0, 10))

    server_button = ttk.Button(
        parent_frame, 
        text="Start Server", 
        bootstyle=BUTTON_COLORS["start"], 
        width=15, 
        command=lambda: start_server_logic() if server_button["text"] == "Start Server" else stop_server_logic()
    )
    server_button.pack(pady=5)

    ttk.Button(parent_frame, text="Settings", bootstyle=(INFO, OUTLINE), width=15, command=lambda: display_settings_ui(parent_frame, root_window)).pack(pady=5)
    ttk.Button(parent_frame, text="Linked Devices", bootstyle=(INFO, OUTLINE), width=15, command=lambda: display_connected_devices_ui(parent_frame, root_window)).pack(pady=5)

    # Ensure UI reflects current server state if already known
    is_server_running = server_process and server_process.poll() is None
    update_server_ui_state(is_server_running)

def on_closing():
    stop_server_logic() # Attempt to stop the server
    if root:
        root.destroy()

def main():
    global root, server_status_label

    load_config()
    root = Window(themename="flatly") 
    root.title("AkServer Control")
    root.geometry("450x400")
    root.resizable(False, False)

    content_frame = ttk.Frame(root, padding=20)
    content_frame.pack(fill=BOTH, expand=True)

    # Copyright label (bottom-most)
    copyright_label = ttk.Label(
        root,
        text="© 2025 AkServer. All rights reserved.",
        font=("Helvetica", 8),
        bootstyle=SECONDARY,
        anchor="center"
    )
    copyright_label.pack(side=BOTTOM, fill=X)

    # Server status label above copyright and definition
    server_status_label = ttk.Label(root, text="Server Offline", font=("Helvetica", 10), bootstyle=DANGER, relief=SUNKEN, anchor=W, padding=5)
    server_status_label.pack(side=BOTTOM, fill=X)

    display_main_app_ui(content_frame, root)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.after(200, start_server_logic)
    root.mainloop()

if __name__ == "__main__":
    main()
