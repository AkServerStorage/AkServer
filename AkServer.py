import http.server
import socketserver
import ssl
import os
import sys
import logging
import shutil
from urllib.parse import parse_qs, urlparse, quote, unquote # type: ignore
import datetime # For TrialManager
import html # For XSS protection
import threading # For server shutdown
import json
import mimetypes
from AkServer_HTML import * # type: ignore
import AkServer_trusted_device_manager # type: ignore
import AkServer_ssl_util # type: ignore
import AkServer_auth # type: ignore
import AkServer_route_handlers # type: ignore # Import the new handlers module

# Determine application path for logs and resources
if getattr(sys, 'frozen', False): # Running as a PyInstaller bundle
    EXE_LOCATION_PATH = os.path.dirname(sys.executable)
    # BUNDLED_FILES_PATH is for assets bundled with the executable (e.g., logo.png)
    BUNDLED_FILES_PATH = getattr(sys, '_MEIPASS', EXE_LOCATION_PATH)
else: # Running as a script
    EXE_LOCATION_PATH = os.path.dirname(os.path.abspath(__file__))
    BUNDLED_FILES_PATH = EXE_LOCATION_PATH

# Define base directory for persistent server files.
# For a server application, ProgramData is a suitable location for system-wide data.
if sys.platform == "win32":
    PROGRAM_DATA_PATH = os.getenv('PROGRAMDATA', 'C:\\ProgramData') # Default if env var not found
    APP_DATA_ROOT = os.path.join(PROGRAM_DATA_PATH, "AkServer", "AkServer_Data_Server") # Added "Server" to distinguish from GUI's LocalAppData
else:
    # For non-Windows, use a path relative to the executable or a standard Unix path.
    # This example keeps it relative for simplicity on other platforms for now.
    APP_DATA_ROOT = os.path.join(EXE_LOCATION_PATH, "AkServer_Data_Server")

SERVER_DATA_PATH = os.path.join(APP_DATA_ROOT, 'Server')
TRIAL_DATA_PATH_SERVER = os.path.join(APP_DATA_ROOT, 'Trial') # For server's trial check

LOG_DIR = os.path.join(SERVER_DATA_PATH, "logs") 
# Ensure directories exist (installer should create them, server can try too)
# Create APP_DATA_ROOT first if it might not exist, then subdirectories
try:
    os.makedirs(APP_DATA_ROOT, exist_ok=True)
    os.makedirs(SERVER_DATA_PATH, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(TRIAL_DATA_PATH_SERVER, exist_ok=True)
except OSError as e:
    # This is a critical failure if directories in ProgramData cannot be created.
    print(f"CRITICAL ERROR: Could not create required server data directories in {APP_DATA_ROOT}. Error: {e}. Exiting.")
    sys.exit(1)

# --- Debugging: Write LOG_DIR to a file ---
try:
    # Ensure the base debug directory exists (C:\ProgramData\AkServer is created by Inno Setup)
    debug_log_dir_base = os.path.join(os.getenv('PROGRAMDATA', 'C:\\ProgramData'), "AkServer")
    os.makedirs(debug_log_dir_base, exist_ok=True)
    debug_file_path = os.path.join(debug_log_dir_base, "AkServer_resolved_log_dir.txt")
    with open(debug_file_path, "w") as df:
        df.write(f"Attempting to use LOG_DIR: {LOG_DIR}\n")
except Exception as e_debug:
    print(f"DEBUG: Failed to write debug log_dir file: {e_debug}") # This print might not be visible

# Logging Setup for Server
server_logger = logging.getLogger("AkServer")
server_logger.setLevel(logging.DEBUG)
log_file_handler = logging.FileHandler(os.path.join(LOG_DIR, 'AkServer_server.log'))
log_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
stream_handler = logging.StreamHandler(sys.stdout) # Output to stdout for GUI to capture
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
server_logger.addHandler(log_file_handler)
server_logger.addHandler(stream_handler)


PORT = 8443
DEFAULT_SAVE_DIR_SERVER = os.path.join(os.path.expanduser("~"), "AkServerUploads")
SSL_CERT_FILE = os.path.join(SERVER_DATA_PATH, "server_cert.pem")
SSL_KEY_FILE = os.path.join(SERVER_DATA_PATH, "server_key.pem")
TRUSTED_DEVICES_FILE = os.path.join(SERVER_DATA_PATH, "trusted_devices.json")

TRIAL_DURATION_DAYS = 60 # Should match GUI
APP_NAME_FOR_TRIAL = "AkServer" # Should match GUI for shared trial

# DEVICE_TOKEN_COOKIE_NAME and DEVICE_TOKEN_VALIDITY_SECONDS are now in AkServer_auth
# Global variable to hold the server instance for shutdown purposes
httpd_instance = None


# --- TrialManager Class (Integrated) ---
class TrialManager:
    """
    Manages a trial period for an application.
    Stores the first run date in a file in the user's local app data directory.
    """
    def __init__(self, app_name: str, trial_duration_days: int = 15, logger_instance=None):
        """
        Initializes the TrialManager.

        Args:
            app_name (str): The name of the application. Used to create a unique storage folder.
            trial_duration_days (int): The duration of the trial period in days.
            logger_instance: Optional logger for server-side logging.
        """
        self.app_name = app_name
        self.trial_duration_days = trial_duration_days
        self.logger = logger_instance
        # For server, trial info should be system-wide or installation-wide
        self._storage_dir = TRIAL_DATA_PATH_SERVER
        self._trial_file_path = os.path.join(self._storage_dir, "trial_info.json")
        
        if not os.path.exists(self._storage_dir):
            try:
                os.makedirs(self._storage_dir, exist_ok=True)
            except OSError as e:
                self._log(logging.CRITICAL, f"CRITICAL: Error creating primary trial storage directory {self._storage_dir}: {e}. Trial functionality will be impaired.")
                # Fallback to EXE_LOCATION_PATH removed. If ProgramData is not writable for trial info,
                # the server should log this critical issue. Subsequent file operations for trial
                # will likely fail, which is preferable to writing to a restricted/incorrect location.
                # The _read_first_run_date and _write_first_run_date methods will handle IOErrors
                # if self._trial_file_path (still pointing to the intended ProgramData) is not writable.

    def _log(self, level, message):
        if self.logger:
            self.logger.log(level, f"[TrialManager] {message}")
        else:
            print(f"[TrialManager Fallback] {logging.getLevelName(level)}: {message}")

    def _get_storage_directory(self) -> str:
        # This method is effectively overridden for the server by direct assignment of self._storage_dir
        """Determines the appropriate directory for storing trial information."""
        if sys.platform == "win32":
            base_path = os.getenv('LOCALAPPDATA')
        elif sys.platform == "darwin":
            base_path = os.path.expanduser('~/Library/Application Support')
        else:
            base_path = os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        
        if not base_path:
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
            self._log(logging.ERROR, f"Error reading trial file: {e}")
        return None

    def _write_first_run_date(self, date_to_write: datetime.date) -> None:
        """Writes the first run date to the trial file."""
        try:
            with open(self._trial_file_path, 'w') as f:
                json.dump({"first_run_date": date_to_write.isoformat()}, f)
        except IOError as e:
            self._log(logging.ERROR, f"Error writing trial file: {e}")

    def start_trial_if_not_started(self) -> None:
        """If the trial hasn't started, records today as the first run date."""
        if self._read_first_run_date() is None:
            today = datetime.date.today()
            self._write_first_run_date(today)
            self._log(logging.INFO, f"Trial started on: {today.isoformat()}")

    def get_trial_status(self) -> tuple[bool, int | None, datetime.date | None]:
        """
        Checks the status of the trial period.
        Returns: (is_active, days_remaining, expiry_date)
        """
        first_run_date = self._read_first_run_date()
        if first_run_date is None:
            return False, None, None

        today = datetime.date.today()
        expiry_date = first_run_date + datetime.timedelta(days=self.trial_duration_days)
        
        if today >= expiry_date:
            return False, 0, expiry_date

        days_remaining = (expiry_date - today).days
        return True, days_remaining, expiry_date

class AkServerRequestHandler(http.server.SimpleHTTPRequestHandler):
    
    def _send_response_data(self, data, content_type="text/html", code=200):
        self.send_response(code)
        self.send_header("Content-type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    def _trigger_server_shutdown(self):
        global httpd_instance
        if httpd_instance:
            self.server_logger.info("Shutdown request received by handler. Initiating server shutdown via separate thread...")
            
            def actual_shutdown(): # sourcery skip: extract-method
                try:
                    self.server_logger.info("Thread: Calling httpd_instance.shutdown()...")
                    httpd_instance.shutdown()
                    self.server_logger.info("Thread: httpd_instance.shutdown() called successfully.")
                except Exception as e:
                    self.server_logger.error(f"Exception during httpd_instance.shutdown(): {e}", exc_info=True)
            threading.Thread(target=actual_shutdown, daemon=True, name="ServerShutdownThread").start()
        else:
            self.server_logger.warning("Shutdown trigger called, but httpd_instance is None.")

    def _ensure_authenticated(self, redirect_path="/login?message=Authentication required."):
        """
        Ensures the current request is authenticated if AUTH_ENABLED.
        Redirects to login if not authenticated.
        Returns True if authenticated (or auth disabled), False otherwise (and redirect is sent).
        """
        if self.AUTH_ENABLED and not self._is_authenticated():
            self._redirect(redirect_path)
            return False
        return True

    def _check_api_access(self):
        """
        Checks if the API request is authorized (local admin or authenticated user).
        Sends a 401 error and returns False if not authorized.
        Returns True if authorized.
        """
        is_local_admin_request = self.client_address[0] == '127.0.0.1'
        if not is_local_admin_request and not self._is_authenticated():
            self.server_logger.warning(f"Unauthorized API access to {self.path} from {self.client_address[0]}")
            self._send_response_data(json.dumps({"error": "Authentication required"}).encode(), 'application/json', 401)
            return False
        return True

    def _get_validated_filepath(self, raw_filename_from_path_or_form, is_for_download_post=False):
        """
        Sanitizes a filename and validates it's a file within the SAVE_DIR.
        Sends an error response and returns None if invalid or not found.
        Otherwise, returns the absolute, validated filepath.
        """
        if is_for_download_post: # Stricter sanitization for POSTed filenames
            filename = os.path.basename(raw_filename_from_path_or_form)
            if not filename or ".." in filename or "/" in filename or "\\" in filename:
                self.server_logger.warning(f"Invalid filename for download: '{raw_filename_from_path_or_form}' (sanitized: '{filename}') from {self.client_address[0]}")
                self.send_error(400, "Bad Request: Invalid filename.")
                return None
        else: # For URL paths like /files/
            filename_segment = unquote(raw_filename_from_path_or_form)
            if ".." in filename_segment or "/" in filename_segment or "\\" in filename_segment:
                self.server_logger.warning(f"Attempt to access potentially unsafe path: {filename_segment} from {self.client_address[0]}")
                self.send_error(400, "Bad Request: Invalid filename.")
                return None
            filename = filename_segment
        # Common validation for both cases
        potential_filepath = os.path.join(self.SAVE_DIR, filename)
        abs_validated_filepath = os.path.abspath(potential_filepath)
        abs_savedir = os.path.abspath(self.SAVE_DIR)

        if not abs_validated_filepath.startswith(abs_savedir):
            self.server_logger.warning(f"Directory traversal attempt: '{filename}' from {self.client_address[0]}. Path {abs_validated_filepath} outside {abs_savedir}")
            self.send_error(403, "Forbidden: Access denied.")
            return None

        if not os.path.isfile(abs_validated_filepath):
            self.server_logger.warning(f"File not found or not a file: {filename} at {abs_validated_filepath} from {self.client_address[0]}")
            self.send_error(404, "File not found or access denied.")
            return None
        return abs_validated_filepath

    def _redirect(self, location="/", device_token_to_set=None):
        self.send_response(302)
        self.send_header("Location", location)
        if device_token_to_set and self.AUTH_ENABLED:
            cookie_attrs = f"; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={AkServer_auth.DEVICE_TOKEN_VALIDITY_SECONDS}"
            self.send_header("Set-Cookie", f"{AkServer_auth.DEVICE_TOKEN_COOKIE_NAME}={device_token_to_set}{cookie_attrs}")
            server_logger.info(f"Setting device token cookie for {self.client_address[0]} (token ending: ...{device_token_to_set[-6:]})")
        self.end_headers()

    def _is_authenticated(self):
        if not self.AUTH_ENABLED:
            return True

        cookie_header = self.headers.get('Cookie')
        client_ip = self.client_address[0]
        
        is_auth, _ = AkServer_auth.check_authentication(
            cookie_header,
            client_ip,
            AkServer_trusted_device_manager # Pass the module itself
        )
        return is_auth

    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query_params = parse_qs(parsed_path.query)
        message = html.escape(query_params.get('message', [''])[0]) # Escape message for XSS protection

        if path == "/logo.png":
            logo_file_path = os.path.join(BUNDLED_FILES_PATH, "logo.png")
            if os.path.exists(logo_file_path):
                try:
                    with open(logo_file_path, 'rb') as f:
                        logo_data = f.read()
                    self.send_response(200)
                    self.send_header("Content-type", "image/png")
                    self.send_header("Content-Length", str(len(logo_data)))
                    self.send_header("Cache-Control", "public, max-age=3600") # Cache for 1 hour
                    self.end_headers()
                    self.wfile.write(logo_data)
                except Exception as e:
                    self.server_logger.error(f"Error serving logo.png: {e}", exc_info=True)
                    self.send_error(500, "Server error serving logo.")
            else:
                self.server_logger.warning(f"logo.png not found at {logo_file_path}")
                self.send_error(404, "Logo not found.")
            return

        if path == "/request_otp":
            if not self.AUTH_ENABLED:
                self._send_response_data(json.dumps({"success": False, "message": "Authentication is disabled."}).encode(), 'application/json', 403)
                return
            
            new_otp = AkServer_auth.request_new_otp()
            response_payload = {"success": True, "message": "OTP generated."}

            if self.client_address[0] == '127.0.0.1': # GUI will be local
                response_payload["otp"] = new_otp
                response_payload["message"] = "OTP generated and provided for local client."
                self.server_logger.info(f"OTP generated and provided in response to local client {self.client_address[0]}.") # OTP value removed from log
            else:
                self.server_logger.info(f"OTP generated (but not sent in response) for remote client {self.client_address[0]}.") # OTP value removed from log
            # The GUI captures OTP from stdout if server is run as subprocess,
            # but this API endpoint is also available for direct OTP request by GUI.
            print(f"One-Time Password (OTP): {new_otp}", flush=True) # For GUI to capture if needed
            self._send_response_data(json.dumps(response_payload).encode(), 'application/json')
            return

        if path == "/login":
            AkServer_route_handlers.handle_get_login_page(self, message)
            return

        if path == "/logout":
            if self.AUTH_ENABLED:
                AkServer_auth.logout_client_session(self.client_address[0])
                # Also clear the device token cookie on logout
                cookie_attrs = f"; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0" 
                self.send_response(302)
                self.send_header("Location", "/login?message=Logged out successfully.")
                self.send_header("Set-Cookie", f"{AkServer_auth.DEVICE_TOKEN_COOKIE_NAME}=''{cookie_attrs}")
                self.end_headers()
            else:
                self._redirect("/")
            return

        if path == "/":
            AkServer_route_handlers.handle_get_root(self, message)
            return

        if path == "/view_files":
            AkServer_route_handlers.handle_get_view_files(self)
            return

        if path.startswith("/files/"):
            if not self._ensure_authenticated():
                return
            try:
                filename_to_serve_encoded = path[len("/files/"):]
                abs_requested_filepath = self._get_validated_filepath(filename_to_serve_encoded)
                if not abs_requested_filepath:
                    return

                mimetype, _ = mimetypes.guess_type(abs_requested_filepath)
                if mimetype is None:
                    mimetype = 'application/octet-stream'
                self.send_response(200)
                self.send_header("Content-type", mimetype)
                self.send_header("Content-Length", str(os.path.getsize(abs_requested_filepath)))
                # Use os.path.basename on the original unquoted name for Content-Disposition
                self.send_header("Content-Disposition", f'inline; filename="{os.path.basename(unquote(filename_to_serve_encoded))}"')
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                with open(abs_requested_filepath, 'rb') as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                server_logger.warning(f"File not found (FileNotFoundError): {path} for {self.client_address[0]}")
                self.send_error(404, "File not found.")
            except Exception as e:
                server_logger.error(f"Error preparing to serve file {path} for {self.client_address[0]}: {e}", exc_info=True)
                self.send_error(500, "Server error.")
            return
        
        if path == "/register_device_name":
            if not self.AUTH_ENABLED:
                self._redirect("/")
                return

            client_ip = self.client_address[0]
            if not AkServer_auth.is_client_pending_registration(client_ip):
                server_logger.warning(f"Unauthorized access to /register_device_name from {client_ip}. Redirecting to login.")
                self._redirect("/login?message=Please login first.")
                return

            html_content = DEVICE_NAME_FORM_HTML.format(message_placeholder=f"<div class='message'>{message}</div>" if message and message.strip() else "") # type: ignore
            self._send_response_data(html_content.encode('utf-8'))
            return

        if path == "/api/status": # No authentication needed for a simple status ping.
            self._send_response_data(json.dumps({"status": "ok", "auth_enabled": self.AUTH_ENABLED}).encode(), 'application/json')
            return
        # For other paths, especially if they might be files in SAVE_DIR when /files/ isn't used
        # We need to ensure that direct access to SAVE_DIR contents is also authenticated if auth is on.
        # However, the /files/ endpoint is the primary way to serve these now.
        # The super().do_GET() below will handle other static files if any, or 404.

        if path == "/api/devices":
            is_local_admin_request = self.client_address[0] == '127.0.0.1'
            if not is_local_admin_request and not self._is_authenticated(): # Allow local admin even if not authenticated via OTP/Cookie
                self._send_response_data(json.dumps({"error": "Authentication required"}).encode(), 'application/json', 401)
                server_logger.warning(f"Unauthorized API access to /api/devices from {self.client_address[0]}")
                return

            display_trusted_tokens = [
                {
                    "name": device_obj.get("name", f"Device ...{device_obj['token'][-6:]}"),
                    "token_partial": f"...{device_obj['token'][-6:]}"
                }
                for device_obj in AkServer_trusted_device_manager.get_trusted_devices_list()
            ]
            active_sessions_info = AkServer_auth.get_active_sessions_info()

            response_data = {
                "trusted_devices": display_trusted_tokens,
                "active_otp_sessions": active_sessions_info
            }
            self._send_response_data(json.dumps(response_data).encode(), 'application/json')
            return

        # --- Fallback GET handling for files in CWD (application_path) ---
        server_logger.debug(f"GET request for {self.path} (path component: {path}) from {self.client_address[0]} not handled by explicit routes.")
        potential_fs_path = self.translate_path(path) # translate_path uses os.getcwd() or directory from --directory
        abs_app_path = os.path.abspath(BUNDLED_FILES_PATH) # Check against where bundled files are expected

        # Check if the target path is within the application directory
        if os.path.abspath(potential_fs_path).startswith(abs_app_path):
            relative_to_app_path = os.path.relpath(potential_fs_path, abs_app_path)

            sensitive_filenames_in_app_root = [
                os.path.basename(SSL_CERT_FILE),
                os.path.basename(SSL_KEY_FILE),
                os.path.basename(TRUSTED_DEVICES_FILE)
            ]
            sensitive_dirs_relative_to_app = ["logs"]
            sensitive_extensions = [".py", ".pyc", ".pyd", ".db", ".sqlite", ".sqlite3", ".env"] # Add other sensitive extensions as needed

            path_parts = relative_to_app_path.split(os.sep)
            filename_component = path_parts[-1]

            is_sensitive = False
            if len(path_parts) > 0 and path_parts[0] in sensitive_dirs_relative_to_app:
                is_sensitive = True
            elif filename_component in sensitive_filenames_in_app_root and (len(path_parts) == 1 or (len(path_parts) > 1 and path_parts[0] == ".")): # Check if it's in app root
                is_sensitive = True
            elif any(filename_component.endswith(ext) for ext in sensitive_extensions):
                is_sensitive = True

            if is_sensitive:
                server_logger.warning(f"Blocked attempt to access sensitive application resource: {path} (resolved to {potential_fs_path}) from {self.client_address[0]}")
                self.send_error(403, "Forbidden")
                return

        if self.AUTH_ENABLED and not path.startswith("/files/") and not self._is_authenticated():
            server_logger.warning(f"Unauthenticated GET attempt for unhandled path: {path} from {self.client_address[0]}. Auth enabled.")
            self.send_error(403, "Forbidden: Authentication required.")
            return

        server_logger.debug(f"Falling back to SimpleHTTPRequestHandler for GET {self.path} from {self.client_address[0]}.")
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/login":
            AkServer_route_handlers.handle_post_login(self)
            return
        
        if path == "/submit_device_name":
            AkServer_route_handlers.handle_post_submit_device_name(self)
            return

        if path == "/upload":
            AkServer_route_handlers.handle_post_upload(self)
            return

        if path == "/api/shutdown":
            if self.client_address[0] == '127.0.0.1': # Only allow local client (GUI) to shut down
                # The check for 127.0.0.1 is sufficient for this local administrative action.
                self.server_logger.info(f"Received /api/shutdown request from local client {self.client_address[0]}.")
                self._send_response_data(json.dumps({"success": True, "message": "Server shutdown initiated."}).encode(), 'application/json')
                self._trigger_server_shutdown()
            else:
                self.server_logger.warning(f"Unauthorized /api/shutdown attempt from {self.client_address[0]}.")
                self._send_response_data(json.dumps({"success": False, "message": "Forbidden."}).encode(), 'application/json', 403)
            return

        if path == "/api/devices/forget":
            if not self._check_api_access():
                return
            
            content_length = int(self.headers['Content-Length'])
            post_data_raw = self.rfile.read(content_length)
            try:
                post_data = json.loads(post_data_raw.decode('utf-8'))
                token_partial_to_forget = post_data.get('token_partial')

                if not token_partial_to_forget or not token_partial_to_forget.startswith("..."):
                    self._send_response_data(json.dumps({"success": False, "message": "Invalid token format."}).encode(), 'application/json', 400)
                    return

                suffix_to_find = token_partial_to_forget[3:]
                removed_device_info = AkServer_trusted_device_manager.forget_device_by_partial_token_suffix(suffix_to_find, TRUSTED_DEVICES_FILE, server_logger)
                
                if removed_device_info:
                    removed_device_ip = removed_device_info.get("origin_ip")
                    message = "Device token forgotten."
                    if removed_device_ip:
                        AkServer_auth.clear_ip_session_on_token_forget(removed_device_ip)
                        server_logger.info(f"Cleared active IP-based session for {removed_device_ip} as its associated token was forgotten.")
                        message += " Associated IP session cleared."
                    self._send_response_data(json.dumps({"success": True, "message": message}).encode(), 'application/json')
                else:
                    self._send_response_data(json.dumps({"success": False, "message": "Device token not found."}).encode(), 'application/json', 404)
            except Exception as e:
                server_logger.error(f"Error in /api/devices/forget: {e}", exc_info=True)
                self._send_response_data(json.dumps({"success": False, "message": "Server error."}).encode(), 'application/json', 500)
            return

        elif path == "/download":
            if not self._ensure_authenticated():
                return

            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                server_logger.warning(f"Content-Length is zero or missing for /download POST from {self.client_address[0]}")
                self.send_error(400, "Bad Request: Content-Length is zero or missing.")
                return

            post_data_bytes = self.rfile.read(content_length)
            try:
                post_data_str = post_data_bytes.decode('utf-8')
            except UnicodeDecodeError:
                server_logger.warning(f"Failed to decode POST data as UTF-8 from {self.client_address[0]} for /download")
                self.send_error(400, "Bad Request: Invalid POST data encoding.")
                return

            parsed_data = parse_qs(post_data_str)
            filename_list = parsed_data.get('filename', [])

            if not filename_list:
                server_logger.warning(f"Filename not provided in /download POST from {self.client_address[0]}")
                self.send_error(400, "Bad Request: Filename not provided.")
                return

            raw_filename_from_post = filename_list[0]
            abs_validated_filepath = self._get_validated_filepath(raw_filename_from_post, is_for_download_post=True)

            if not abs_validated_filepath:
                # Error already sent by _get_validated_filepath
                return

            try:
                file_size = os.path.getsize(abs_validated_filepath)
                mimetype, _ = mimetypes.guess_type(abs_validated_filepath)
                if mimetype is None:
                    mimetype = 'application/octet-stream'

                self.send_response(200)
                self.send_header("Content-Type", mimetype)
                self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(abs_validated_filepath)}"')
                self.send_header("Content-Length", str(file_size))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()

                with open(abs_validated_filepath, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
                server_logger.info(f"Successfully served '{os.path.basename(abs_validated_filepath)}' for download to {self.client_address[0]}")
            except BrokenPipeError:
                server_logger.warning(f"Broken pipe while sending '{os.path.basename(abs_validated_filepath)}' for download to {self.client_address[0]}. Client may have disconnected.")
            except Exception as e:
                server_logger.error(f"Error sending file '{os.path.basename(abs_validated_filepath)}' for download to {self.client_address[0]}: {e}", exc_info=True)
            return
        self.send_error(405, "Method Not Allowed")

def run_server(port, save_dir, auth_enabled_str):
    global httpd_instance

    # --- Initialize and Check Trial Period for Server ---
    trial_manager = TrialManager(app_name=APP_NAME_FOR_TRIAL, 
                                 trial_duration_days=TRIAL_DURATION_DAYS, 
                                 logger_instance=server_logger)
    trial_manager.start_trial_if_not_started()
    is_trial_active, days_remaining, trial_expiry_date = trial_manager.get_trial_status()

    if not is_trial_active and trial_expiry_date: # Trial has started and expired
        server_logger.error(f"TRIAL EXPIRED: AkServer trial period expired on {trial_expiry_date.isoformat()}. Server will not start.")
        sys.exit(1) # Prevent server from starting
    elif is_trial_active and days_remaining is not None:
        server_logger.info(f"TRIAL ACTIVE: {days_remaining} days remaining in the trial period.")

    AkServer_trusted_device_manager.load_trusted_devices_from_file(TRUSTED_DEVICES_FILE, server_logger)
    AkServer_auth.init_auth_module(server_logger)
    
    AkServerRequestHandler.SAVE_DIR = save_dir
    AkServerRequestHandler.AUTH_ENABLED = auth_enabled_str.lower() == 'true'
    AkServerRequestHandler.server_logger = server_logger
    AkServerRequestHandler.TRUSTED_DEVICES_FILE = TRUSTED_DEVICES_FILE
    AkServerRequestHandler.trial_manager_instance = trial_manager # Make trial manager accessible to handlers
    server_logger.info(f"Server starting. Save Directory: {save_dir}, Auth Enabled: {AkServerRequestHandler.AUTH_ENABLED}")

    httpd = None
    try:
        if not os.path.exists(SSL_CERT_FILE) or not os.path.exists(SSL_KEY_FILE):
            server_logger.warning(f"SSL cert/key files not found. Generating new...")
            AkServer_ssl_util.generate_self_signed_cert(SSL_CERT_FILE, SSL_KEY_FILE, hostname="localhost", logger=server_logger)
        else:
            server_logger.info(f"Using existing SSL cert: {SSL_CERT_FILE} and key: {SSL_KEY_FILE}")

        if not os.path.exists(SSL_CERT_FILE) or not os.path.exists(SSL_KEY_FILE):
            server_logger.error(f"Critical: SSL cert/key files missing. Server cannot start.")
            sys.exit(1)

        Handler = AkServerRequestHandler
        httpd = socketserver.TCPServer(("", port), Handler)
        httpd_instance = httpd # Store for shutdown

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=SSL_CERT_FILE, keyfile=SSL_KEY_FILE)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        server_logger.info(f"AkServer running on https://<your-ip>:{port}")
        httpd.serve_forever()
    except KeyboardInterrupt:
        server_logger.info("Server shutting down via KeyboardInterrupt.")
    except Exception as e:
        server_logger.error(f"Server failed: {e}", exc_info=True)
        if isinstance(e, FileNotFoundError) and str(e).endswith(SSL_CERT_FILE):
             server_logger.error(f"Ensure '{SSL_CERT_FILE}' exists or can be generated.")
        elif isinstance(e, ssl.SSLError):
            server_logger.error(f"SSL Error. Check certificate and key files. Path used: {SSL_CERT_FILE}")
        elif isinstance(e, OSError) and "address already in use" in str(e).lower():
            server_logger.error(f"Port {port} already in use.")
        sys.exit(1) # Exit if server fails to start properly
    finally:
        server_logger.info("run_server: Entered finally block.")
        if httpd_instance: # Use the global instance for cleanup
            server_logger.info("run_server: httpd_instance is set, calling server_close().")
            httpd_instance.server_close() # Releases the port
            server_logger.info("run_server: server_close() called.")
        else:
            server_logger.info("run_server: httpd_instance is None in finally block.")
        httpd_instance = None
        server_logger.info("AkServer server shut down process completed in finally block.")


if __name__ == "__main__":
    AkServer_SAVE_DIR = os.environ.get('AkServer_SAVE_DIR', DEFAULT_SAVE_DIR_SERVER)
    AkServer_AUTH_ENABLED = os.environ.get('AkServer_AUTH_ENABLED', 'true')

    if not os.path.exists(AkServer_SAVE_DIR):
        try:
            os.makedirs(AkServer_SAVE_DIR, exist_ok=True)
        except Exception as e:
            server_logger.error(f"Failed to create save directory {AkServer_SAVE_DIR}: {e}. Using fallback.")
            AkServer_SAVE_DIR = DEFAULT_SAVE_DIR_SERVER
            if not os.path.exists(AkServer_SAVE_DIR):
                 os.makedirs(AkServer_SAVE_DIR, exist_ok=True)
    server_logger.info(f"Starting server with Save Dir: {AkServer_SAVE_DIR}, Auth: {AkServer_AUTH_ENABLED}")
    run_server(PORT, AkServer_SAVE_DIR, AkServer_AUTH_ENABLED)
    server_logger.info("AkServer.py: run_server function has completed. Script should now exit.")
    sys.exit(0) # Explicitly exit the script
