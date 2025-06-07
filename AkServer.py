import http.server
import socketserver
import ssl
import os
import sys
import logging # Keep for server_logger
import shutil # Added for file streaming in download
from urllib.parse import parse_qs, urlparse, quote, unquote
import json
import time
from werkzeug.formparser import parse_form_data
from werkzeug.wrappers import Request
from http.cookies import SimpleCookie
import hashlib # Keep for file hashing
import mimetypes
from AkServer_HTML import * # type: ignore
import AkServer_trusted_device_manager # type: ignore
import AkServer_ssl_util # type: ignore
import AkServer_auth # type: ignore
import AkServer_route_handlers # type: ignore # Import the new handlers module

# Determine application path for logs and resources
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

LOG_DIR = os.path.join(application_path, "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

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
SSL_CERT_FILE = os.path.join(application_path, "server_cert.pem")
SSL_KEY_FILE = os.path.join(application_path, "server_key.pem")
TRUSTED_DEVICES_FILE = os.path.join(application_path, "trusted_devices.json")
# DEVICE_TOKEN_COOKIE_NAME and DEVICE_TOKEN_VALIDITY_SECONDS are now in AkServer_auth
# Authentication globals (CURRENT_OTP, etc.) are now managed within AkServer_auth


class AkServerRequestHandler(http.server.SimpleHTTPRequestHandler):
    # Class variables set by the main server startup
    SAVE_DIR = DEFAULT_SAVE_DIR_SERVER
    AUTH_ENABLED = False
    server_logger = server_logger # Make server_logger accessible to handlers
    TRUSTED_DEVICES_FILE = TRUSTED_DEVICES_FILE # Make TRUSTED_DEVICES_FILE accessible

    def _send_response_data(self, data, content_type="text/html", code=200):
        self.send_response(code)
        self.send_header("Content-type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

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
        message = query_params.get('message', [''])[0]

        if path == "/request_otp":
            if not self.AUTH_ENABLED:
                self._send_response_data(json.dumps({"success": False, "message": "Authentication is disabled."}).encode(), 'application/json', 403)
                return
            new_otp = AkServer_auth.request_new_otp()
            print(f"One-Time Password (OTP): {new_otp}", flush=True) # For GUI
            # server_logger.info is already logged by AkServer_auth.request_new_otp()
            self._send_response_data(json.dumps({"success": True, "message": "OTP generated and sent to server console."}).encode(), 'application/json')
            return

        if path == "/get_otp":
            if not self.AUTH_ENABLED:
                self._send_response_data(json.dumps({"success": False, "message": "Auth disabled."}).encode(), 'application/json', 403)
                return
            otp_info = AkServer_auth.get_otp_status_for_client()
            self._send_response_data(json.dumps(otp_info).encode(), 'application/json')
            return

        if path == "/login":
            # Use the new handler function
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
            # Use the new handler function
            AkServer_route_handlers.handle_get_root(self, message)
            return

        if path == "/view_files":
            # Use the new handler function
            AkServer_route_handlers.handle_get_view_files(self)
            return

        if path.startswith("/files/"):
            if self.AUTH_ENABLED and not self._is_authenticated():
                self._redirect("/login") # Or send 403 error
                return
            try:
                # Extract filename, decode URL encoding, and normalize
                filename_to_serve_encoded = path[len("/files/"):]
                filename_to_serve = unquote(filename_to_serve_encoded)
                # Basic sanitization: prevent directory traversal by ensuring it's just a filename
                if ".." in filename_to_serve or "/" in filename_to_serve or "\\" in filename_to_serve:
                    server_logger.warning(f"Attempt to access potentially unsafe path: {filename_to_serve} from {self.client_address[0]}")
                    self.send_error(400, "Bad Request: Invalid filename.")
                    return

                requested_filepath = os.path.join(self.SAVE_DIR, filename_to_serve)
                abs_requested_filepath = os.path.abspath(requested_filepath)
                abs_savedir = os.path.abspath(self.SAVE_DIR)

                if not abs_requested_filepath.startswith(abs_savedir):
                    server_logger.warning(f"Directory traversal attempt: {filename_to_serve} from {self.client_address[0]}. Resolved path {abs_requested_filepath} is outside {abs_savedir}")
                    self.send_error(403, "Forbidden: Access denied.")
                    return

                if os.path.isfile(abs_requested_filepath):
                    mimetype, _ = mimetypes.guess_type(abs_requested_filepath)
                    if mimetype is None:
                        mimetype = 'application/octet-stream' # Default if type can't be guessed

                    self.send_response(200)
                    self.send_header("Content-type", mimetype)
                    self.send_header("Content-Length", str(os.path.getsize(abs_requested_filepath)))
                    self.send_header("Content-Disposition", f'inline; filename="{os.path.basename(filename_to_serve)}"')
                    self.send_header("Cache-Control", "public, max-age=3600") # Allow caching
                    self.end_headers()
                    with open(abs_requested_filepath, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    server_logger.warning(f"File not found or not a file: {filename_to_serve} at {abs_requested_filepath} from {self.client_address[0]}")
                    self.send_error(404, "File not found or access denied.")
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

            html_content = DEVICE_NAME_FORM_HTML.format(message_placeholder=f"<div class='message'>{message}</div>" if message else "") # type: ignore
            self._send_response_data(html_content.encode('utf-8'))
            return

        # For other paths, especially if they might be files in SAVE_DIR when /files/ isn't used
        # We need to ensure that direct access to SAVE_DIR contents is also authenticated if auth is on.
        # However, the /files/ endpoint is the primary way to serve these now.
        # The super().do_GET() below will handle other static files if any, or 404.

        if path == "/api/devices":
            is_local_admin_request = self.client_address[0] == '127.0.0.1'
            if not is_local_admin_request and not self._is_authenticated(): # Allow admin even if not authenticated via OTP/Cookie
                self._send_response_data(json.dumps({"error": "Authentication required"}).encode(), 'application/json', 401)
                server_logger.warning(f"Unauthorized API access to /api/devices from {self.client_address[0]}")
                return

            # server_logger.debug(f"API /api/devices: Current AUTHENTICATED_SESSIONS: {AUTHENTICATED_SESSIONS}") # Now handled by AkServer_auth
            
            display_trusted_tokens = []
            for device_obj in AkServer_trusted_device_manager.get_trusted_devices_list():
                display_trusted_tokens.append({ # Ensure all keys are present even if default
                    "name": device_obj.get("name", f"Device ...{device_obj['token'][-6:]}"),
                    "token_partial": f"...{device_obj['token'][-6:]}"
                })
            active_sessions_info = AkServer_auth.get_active_sessions_info()

            response_data = {
                "trusted_devices": display_trusted_tokens,
                "active_otp_sessions": active_sessions_info
            }
            self._send_response_data(json.dumps(response_data).encode(), 'application/json')
            return
        server_logger.debug(f"Unhandled GET request for {self.path} from {self.client_address[0]}.")
        # Before falling back, ensure the path isn't trying to access SAVE_DIR directly without auth
        # This is a bit tricky with SimpleHTTPRequestHandler's default behavior.
        # The /files/ endpoint is the controlled way. For now, let's assume other GETs are not for SAVE_DIR.
        # If you had other static assets outside SAVE_DIR, this would serve them.
        # If path could be within SAVE_DIR, more checks would be needed here or rely on /files/
        return super().do_GET() # This will serve files based on current working dir or specified dir for SimpleHTTPRequestHandler


    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/login":
            # Use the new handler function
            AkServer_route_handlers.handle_post_login(self)
            return
        
        if path == "/submit_device_name":
            # Use the new handler function
            AkServer_route_handlers.handle_post_submit_device_name(self)
            return

        if path == "/upload":
            # Use the new handler function
            AkServer_route_handlers.handle_post_upload(self)
            return

        if path == "/api/devices/forget":
            is_local_admin_request = self.client_address[0] == '127.0.0.1'
            if not is_local_admin_request and not self._is_authenticated(): # Allow admin even if not authenticated via OTP/Cookie
                self._send_response_data(json.dumps({"success": False, "message": "Authentication required."}).encode(), 'application/json', 401)
                server_logger.warning(f"Unauthorized API access to /api/devices/forget from {self.client_address[0]}")
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
                    if removed_device_ip: # AkServer_auth handles "unknown" check
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
            if self.AUTH_ENABLED and not self._is_authenticated():
                server_logger.warning(f"Unauthorized download attempt from {self.client_address[0]} for path {path}")
                self.send_error(403, "Forbidden: Authentication required.")
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

            filename_from_post = filename_list[0]
            # Sanitize filename: ensure it's just a name, no path components.
            filename = os.path.basename(filename_from_post)

            if not filename or ".." in filename: # Check for empty or ".." after basename
                server_logger.warning(f"Invalid or potentially malicious filename for download: '{filename_from_post}' (sanitized: '{filename}') from {self.client_address[0]}")
                self.send_error(400, "Bad Request: Invalid filename.")
                return

            # Securely join path and check if it's within SAVE_DIR
            requested_filepath = os.path.join(self.SAVE_DIR, filename)
            abs_requested_filepath = os.path.abspath(requested_filepath)
            abs_savedir = os.path.abspath(self.SAVE_DIR)

            if not abs_requested_filepath.startswith(abs_savedir):
                server_logger.warning(f"Directory traversal attempt for download: '{filename}' from {self.client_address[0]}. Resolved path {abs_requested_filepath} is outside {abs_savedir}")
                self.send_error(403, "Forbidden: Access denied.")
                return

            if os.path.isfile(abs_requested_filepath):
                try:
                    file_size = os.path.getsize(abs_requested_filepath)
                    mimetype, _ = mimetypes.guess_type(abs_requested_filepath)
                    if mimetype is None:
                        mimetype = 'application/octet-stream'

                    self.send_response(200)
                    self.send_header("Content-Type", mimetype)
                    self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(filename)}"') # os.path.basename for safety
                    self.send_header("Content-Length", str(file_size))
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate") # Good for downloads
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Expires", "0")
                    self.end_headers()

                    with open(abs_requested_filepath, 'rb') as f:
                        shutil.copyfileobj(f, self.wfile)
                    server_logger.info(f"Successfully served '{filename}' for download to {self.client_address[0]}")
                except BrokenPipeError:
                    server_logger.warning(f"Broken pipe while sending '{filename}' for download to {self.client_address[0]}. Client may have disconnected.")
                except Exception as e:
                    server_logger.error(f"Error sending file '{filename}' for download to {self.client_address[0]}: {e}", exc_info=True)
                    # Avoid sending another error if headers are already sent. Client will experience a failed download.
            else:
                server_logger.warning(f"File not found or not a file for download: '{filename}' at '{abs_requested_filepath}' from {self.client_address[0]}")
                self.send_error(404, "File not found or access denied.")
            return
        self.send_error(405, "Method Not Allowed") # Changed from 404 to 405 for unhandled POSTs

def run_server(port, save_dir, auth_enabled_str):
    AkServer_trusted_device_manager.load_trusted_devices_from_file(TRUSTED_DEVICES_FILE, server_logger)
    AkServer_auth.init_auth_module(server_logger) # Initialize the auth module
    
    AkServerRequestHandler.SAVE_DIR = save_dir
    AkServerRequestHandler.AUTH_ENABLED = auth_enabled_str.lower() == 'true'
    AkServerRequestHandler.server_logger = server_logger # Make logger available to handlers
    AkServerRequestHandler.TRUSTED_DEVICES_FILE = TRUSTED_DEVICES_FILE # Make const available
    server_logger.info(f"Server starting with Save Directory: {save_dir}, Auth Enabled: {AkServerRequestHandler.AUTH_ENABLED}")

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
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=SSL_CERT_FILE, keyfile=SSL_KEY_FILE)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        server_logger.info(f"AkServer running on https://<your-ip>:{port}")
        httpd.serve_forever()
    except Exception as e:
        server_logger.error(f"Server failed: {e}", exc_info=True)
        if isinstance(e, FileNotFoundError) and str(e).endswith(SSL_CERT_FILE):
             server_logger.error(f"Ensure '{SSL_CERT_FILE}' exists or can be generated.")
        elif isinstance(e, ssl.SSLError):
            server_logger.error(f"SSL Error. Check certificate and key files. Path used: {SSL_CERT_FILE}")
        elif isinstance(e, OSError) and "address already in use" in str(e).lower():
            server_logger.error(f"Port {port} already in use.")
        if httpd: # Ensure shutdown if httpd was initialized
            httpd.shutdown()
            httpd.server_close()
        sys.exit(1) # Exit if server fails to start properly
    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        server_logger.info("AkServer server shut down.")


if __name__ == "__main__":
    AkServer_SAVE_DIR = os.environ.get('AkServer_SAVE_DIR', DEFAULT_SAVE_DIR_SERVER)
    AkServer_AUTH_ENABLED = os.environ.get('AkServer_AUTH_ENABLED', 'true')

    if not os.path.exists(AkServer_SAVE_DIR):
        try:
            os.makedirs(AkServer_SAVE_DIR, exist_ok=True)
        except Exception as e:
            server_logger.error(f"Failed to create save directory {AkServer_SAVE_DIR}: {e}. Using default.")
            AkServer_SAVE_DIR = DEFAULT_SAVE_DIR_SERVER # Fallback to default
            if not os.path.exists(AkServer_SAVE_DIR): # Ensure default exists
                 os.makedirs(AkServer_SAVE_DIR, exist_ok=True)
    run_server(PORT, AkServer_SAVE_DIR, AkServer_AUTH_ENABLED)
