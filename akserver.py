# =============================================================================
# akserver - Secure Local File Server (Proprietary Edition)
# =============================================================================
"""
File:          akserver.py
Description:   Core HTTPS server launcher for akserver.
Author:        AkshAy S (akserver Project)
Version:       1.0.0
License:       akserver Custom Freemium License (See LICENSE.txt)

This software provides secure local file upload/access capabilities with:
- Trial-based licensing enforcement
- Device registration and OTP authentication
- Local-only analytics logging

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Python Standard library

from __future__ import annotations

import os
import sys
import ssl
import html
import json
import time
import threading
import socketserver
import http.server
from logging import Logger
from collections import deque
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import parse_qs, unquote, urlparse

# ------------------------------------------------------------------  Local modules

from akserver_config import APP_NAME, CONFIG, DEFAULT_SAVE_DIR, LOGGER, PORT, SERVER_DATA_PATH, LOG_DIR, SSL_CERT_FILE, SSL_KEY_FILE, TRUSTED_DEVICES_FILE, load_config
from akserver_auth import AuthManager, DEVICE_TOKEN_COOKIE_NAME, DEVICE_TOKEN_VALIDITY_SECONDS
from akserver_trusted_device_manager import TrustedDeviceManager
from akserver_route_handlers import handle_get_root, handle_get_static_file
from akserver_route_handlers_auth import handle_get_login_page, handle_get_logout, handle_get_register_device_name, handle_get_request_otp, handle_post_login, handle_post_submit_device_name
from akserver_route_handlers_api import handle_get_api_status, handle_get_api_devices, handle_post_shutdown, handle_post_api_devices_forget
from akserver_route_handlers_file import handle_get_file, handle_post_download, route_post_upload, handle_get_view_files
from akserver_route_handlers_thumbnails import handle_get_thumbnail, start_thumbnail_workers, generate_thumbnails_for_folder
from akserver_ssl_util import generate_self_signed_cert, get_or_create_device_id , handle_sensitive_path_access
from akserver_analytics import get_and_send_analytics_data

# ------------------------------------------------------------------ Platform-specific imports

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# ------------------------------------------------------------------ Config values

APP_NAME = APP_NAME
PORT = PORT
DEFAULT_SAVE_DIR_SERVER = Path(DEFAULT_SAVE_DIR)
SERVER_DATA_PATH = Path(SERVER_DATA_PATH)
LOG_DIR = Path(LOG_DIR)
SSL_CERT_FILE = Path(SSL_CERT_FILE)
SSL_KEY_FILE = Path(SSL_KEY_FILE)
TRUSTED_DEVICES_FILE = Path(TRUSTED_DEVICES_FILE)

# ------------------------------------------------------------------ Determine executable location

if getattr(sys, "frozen", False):
    EXE_LOCATION_PATH = Path(sys.executable).parent
    BUNDLED_FILES_PATH = Path(getattr(sys, "_MEIPASS", EXE_LOCATION_PATH))
else:
    EXE_LOCATION_PATH = Path(__file__).resolve().parent
    BUNDLED_FILES_PATH = EXE_LOCATION_PATH

# ------------------------------------------------------------------ Application data root (platform-aware)

if sys.platform == "win32":
    PROGRAM_DATA_PATH = Path(os.getenv("PROGRAMDATA", "C:\\ProgramData"))
    APP_DATA_ROOT = PROGRAM_DATA_PATH / APP_NAME / f"{APP_NAME}_Data_Server"
else:
    APP_DATA_ROOT = EXE_LOCATION_PATH / f"{APP_NAME}_Data_Server"

# ------------------------------------------------------------------ Ensure necessary directories exist

for path in (Path(APP_DATA_ROOT), SERVER_DATA_PATH, LOG_DIR):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Not fatal here, but log via config logger later
        pass

# ------------------------------------------------------------------ Logger from config

server_logger: Logger = LOGGER

# ------------------------------------------------------------------ Simple in-memory rate limiter (thread-safe)

class RateLimiter:
    def __init__(self, max_calls: int = 10, window_seconds: int = 60) -> None:
        self.max_calls = max_calls
        self.window = float(window_seconds)
        self._map: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            dq = self._map.get(key)
            if dq is None:
                dq = deque()
                self._map[key] = dq
            # purge
            while dq and (now - dq[0]) > self.window:
                dq.popleft()
            if len(dq) >= self.max_calls:
                return False
            dq.append(now)
            return True

GLOBAL_RATE_LIMITER = RateLimiter(max_calls=12, window_seconds=60)

# ------------------------------------------------------------------ Global server instance pointer (used to trigger shutdown)

httpd_instance: Optional[socketserver.TCPServer] = None

# ------------------------------------------------------------------ akserverRequestHandler ----------------

class akserverRequestHandler(http.server.SimpleHTTPRequestHandler):
    
    # --- Class-level defaults; set by run_server() ---
    SAVE_DIR: Path = DEFAULT_SAVE_DIR_SERVER
    AUTH_ENABLED: bool = True
    auth_manager_instance: Optional[AuthManager] = None
    rate_limiter: RateLimiter = GLOBAL_RATE_LIMITER
    server_logger: Logger = server_logger

    # --- route maps (functions expect 'handler' instance as first arg) ---
    GET_ROUTES = {
        "/": handle_get_root,
        "/login": handle_get_login_page,
        "/logout": handle_get_logout,
        "/view_files": handle_get_view_files,
        "/get_file": handle_get_file,
        "/register_device_name": handle_get_register_device_name,
        "/request_otp": handle_get_request_otp,
        "/api/status": handle_get_api_status,
        "/api/devices": handle_get_api_devices,
    }

    POST_ROUTES = {
        "/login": handle_post_login,
        "/submit_device_name": handle_post_submit_device_name,
        "/upload": route_post_upload,
        "/api/shutdown": handle_post_shutdown,
        "/api/devices/forget": handle_post_api_devices_forget,
        "/download": handle_post_download,
    }

    def __init__(self, *args, **kwargs) -> None:
        self._cached_auth: Optional[bool] = None
        self._shutdown_triggered = False
        super().__init__(*args, **kwargs)

    # --- Response helpers ---
    def _send_response_data(self, data: bytes, content_type: str = "text/html", code: int = 200) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            # --- Prevent caching of sensitive content ---
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(data)
        except BrokenPipeError:
            # --- Client disconnected; normal scenario ---
            self.server_logger.debug("Client disconnected while sending response (BrokenPipe).")
        except Exception as ex:
            self.server_logger.exception("Error while sending response data: %s", ex)

    def _send_json(self, payload: dict, code: int = 200) -> None:
        # --- ensure ASCII-safe and stable order for reproducible responses ---
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._send_response_data(body, content_type="application/json; charset=utf-8", code=code)

    # --- Authentication helpers ---
    def _is_authenticated(self) -> bool:
        if not getattr(self, "AUTH_ENABLED", True):
            return True
        if self._cached_auth is not None:
            return self._cached_auth

        cookie_header = self.headers.get("Cookie", "")
        client_ip = self.client_address[0] if self.client_address else "unknown"

        if not getattr(self, "auth_manager_instance", None):
            self.server_logger.error("auth_manager_instance missing.")
            self._cached_auth = False
            return False

        try:
            is_auth, reason = self.auth_manager_instance.check_authentication(cookie_header, client_ip)
        except Exception as e:
            self.server_logger.exception("Auth check failed: %s", e)
            self._cached_auth = False
            return False

        if not is_auth:
            self.server_logger.warning("[Auth] Failed auth for %s: %s", client_ip, reason)
        self._cached_auth = is_auth
        return is_auth

    def _ensure_authenticated(self, redirect_path: str = "/login?message=Authentication required.") -> bool:
        if self.AUTH_ENABLED and not self._is_authenticated():
            self._redirect(redirect_path)
            return False
        return True

    def _redirect(self, location: str = "/", device_token_to_set: Optional[str] = None) -> None:
        # --- Use safe cookie attributes ---
        try:
            self.send_response(302)
            self.send_header("Location", location)
            if device_token_to_set:
                cookie_attrs = (
                    f"; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={DEVICE_TOKEN_VALIDITY_SECONDS}"
                )
                self.send_header(
                    "Set-Cookie", f"{DEVICE_TOKEN_COOKIE_NAME}={device_token_to_set}{cookie_attrs}"
                )
            self.end_headers()
        except Exception:
            self.server_logger.exception("Error during redirect to %s", location)

    # --- Path/file validation ---
    def _get_validated_filepath(self, raw_filename: str) -> Optional[Path]:
        client_ip = self.client_address[0] if self.client_address else "unknown"
        try:
            # --- decode and normalize; treat as relative to SAVE_DIR ---
            filename_segment = Path(unquote(raw_filename)).as_posix()
        except Exception:
            self.server_logger.warning("Invalid filename encoding from %s", client_ip)
            self.send_error(400, "Bad Request: Invalid filename encoding.")
            return None

        # --- Prevent path traversal and absolute paths ---
        if filename_segment.startswith("..") or filename_segment.startswith("/") or filename_segment.startswith("\\"):
            self.server_logger.warning("Unsafe path attempt: %s from %s", filename_segment, client_ip)
            self.send_error(400, "Bad Request: Invalid filename.")
            return None

        potential_filepath = (Path(self.SAVE_DIR) / filename_segment).resolve()
        savedir_abs = Path(self.SAVE_DIR).resolve()

        try:
            # --- Ensure potential_filepath is inside savedir_abs ---
            if not (potential_filepath == savedir_abs or potential_filepath.is_relative_to(savedir_abs)):
                self.server_logger.warning("Traversal blocked: %s", potential_filepath)
                self.send_error(403, "Forbidden")
                return None
        except AttributeError:
            # --- Python <3.9 fallback for is_relative_to ---
            if not str(potential_filepath).startswith(str(savedir_abs) + os.sep) and potential_filepath != savedir_abs:
                self.server_logger.warning("Traversal blocked: %s", potential_filepath)
                self.send_error(403, "Forbidden")
                return None

        if not potential_filepath.is_file():
            self.server_logger.warning("File not found: %s", potential_filepath)
            self.send_error(404, "File not found")
            return None

        return potential_filepath

    # --- Shutdown ---
    def _trigger_server_shutdown(self) -> None:
        if self._shutdown_triggered:
            return
        self._shutdown_triggered = True
        global httpd_instance
        if httpd_instance:
            self.server_logger.info("Shutdown requested; launching shutdown thread.")
            def actual_shutdown() -> None:
                try:
                    httpd_instance.shutdown()
                except Exception as e:
                    self.server_logger.exception("Shutdown error: %s", e)
            threading.Thread(target=actual_shutdown, daemon=True).start()

    # --- GET routing ---
    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query_params = parse_qs(parsed.query)
            message = html.escape(query_params.get("message", [""])[0])

            # --- Sensitive path check implemented in route handlers ---
            if handle_sensitive_path_access(self, path):
                return

            if path.startswith("/static/"):
                handle_get_static_file(self, path)
                return

            if path.startswith("/thumbnails/"):
                handle_get_thumbnail(self)
                return

            handler_func: Optional[Callable] = self.GET_ROUTES.get(path)
            if handler_func:
                # --- pass message for pages that expect it ---
                if path in ("/", "/login", "/logout", "/register_device_name"):
                    handler_func(self, message)
                else:
                    handler_func(self)
                return

            # --- fallback to default simple http server behaviour (serves files) ---
            self.server_logger.debug("Default fallback GET %s from %s", self.path, self.client_address[0])
            return super().do_GET()
        except Exception as e:
            self.server_logger.exception("Unhandled GET error: %s", e)
            # --- Generic error response ---
            try:
                self.send_error(500, "Internal Server Error")
            except Exception:
                pass

    # --- POST routing ---
    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            client_ip = self.client_address[0] if self.client_address else "unknown"

            # --- Rate-limit sensitive endpoints ---
            if path in ("/login", "/request_otp"):
                if not self.rate_limiter.allow(f"{path}:{client_ip}"):
                    self._send_json({"error": "Rate limit exceeded"}, code=429)
                    return

            handler_func = self.POST_ROUTES.get(path)
            if handler_func:
                handler_func(self)
                return

            self.send_error(404, "POST route not found")
        except Exception as e:
            self.server_logger.exception("Unhandled POST error: %s", e)
            try:
                self.send_error(500, "Internal Server Error")
            except Exception:
                pass

    # --- Override log_request to forward to configured logger ---
    def log_request(self, code: str = "-", size: str = "-") -> None:
        try:
            self.server_logger.info("%s %s %s", self.requestline, code, size)
        except Exception:
            pass


# ------------------------------------------------------------------ Run server ----------------

def run_server(port: int, save_dir: str | Path, auth_enabled_str: str) -> None:
    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    global httpd_instance

    # --- initialize managers ---
    trusted_devices_manager = TrustedDeviceManager(str(TRUSTED_DEVICES_FILE), server_logger)
    auth_manager = AuthManager(server_logger, trusted_devices_manager, str(TRUSTED_DEVICES_FILE))

    akserverRequestHandler.SAVE_DIR = Path(save_dir)
    akserverRequestHandler.AUTH_ENABLED = str(auth_enabled_str).lower() == "true"
    akserverRequestHandler.server_logger = server_logger
    akserverRequestHandler.auth_manager_instance = auth_manager
    akserverRequestHandler.rate_limiter = GLOBAL_RATE_LIMITER

    server_logger.info("Server starting. Save Directory: %s, Auth Enabled: %s", akserverRequestHandler.SAVE_DIR, akserverRequestHandler.AUTH_ENABLED)

    httpd: Optional[ThreadedTCPServer] = None
    try:
        # --- Ensure certs exist or generate self-signed ---
        if not SSL_CERT_FILE.exists() or not SSL_KEY_FILE.exists():
            generate_self_signed_cert(str(SSL_CERT_FILE), str(SSL_KEY_FILE), hostname="localhost", logger=server_logger)

        Handler = akserverRequestHandler
        httpd = ThreadedTCPServer(("", int(port)), Handler)
        httpd_instance = httpd

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(SSL_CERT_FILE), keyfile=str(SSL_KEY_FILE))
        # --- try setting secure cipher / options but ignore failures (platform-specific) ---
        try:
            context.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
        except Exception:
            server_logger.debug("Unable to set ciphers explicitly; continuing with default.")
        try:
            context.options |= (
                ssl.OP_NO_TLSv1
                | ssl.OP_NO_TLSv1_1
                | ssl.OP_NO_SSLv2
                | ssl.OP_NO_SSLv3
                | ssl.OP_NO_COMPRESSION
            )
        except Exception:
            pass
        try:
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            pass

        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        server_logger.info("akserver running on https://<your-ip>:%s", port)
        httpd.serve_forever()
    except KeyboardInterrupt:
        server_logger.info("Server shutting down via KeyboardInterrupt.")
    except Exception as e:
        server_logger.exception("Server failed: %s", e)
        sys.exit(1)
    finally:
        if httpd_instance:
            try:
                httpd_instance.server_close()
            except Exception:
                server_logger.debug("Error closing server socket during finalization.")
        httpd_instance = None
        server_logger.info("akserver shut down completed.")


# ------------------------------------------------------------------ Main entry ----------------

if __name__ == "__main__":
    load_config()
    PORT = int(CONFIG.get("port", PORT))
    akserver_SAVE_DIR = Path(CONFIG.get("save_dir") or DEFAULT_SAVE_DIR_SERVER)

    lock_file_path = APP_DATA_ROOT / "akserver.lock"
    lock_fd = None
    try:
        lock_fd = open(lock_file_path, "wb+")
        if sys.platform == "win32":
            try:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                server_logger.error("Another instance might be running (lock failed). Exiting.")
                sys.exit(1)
        else:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                server_logger.error("Another instance might be running (lock failed). Exiting.")
                sys.exit(1)

        # --- ensure save dir exists ---
        akserver_SAVE_DIR.mkdir(parents=True, exist_ok=True)

        # --- initialize analytics (non-blocking) ---
        try:
            device_id = get_or_create_device_id()
            server_logger.info("Starting analytics collection...")
            threading.Thread(target=get_and_send_analytics_data, daemon=True).start()
        except Exception:
            server_logger.exception("Analytics initialization failed; continuing without ")

        # --- start thumbnail workers ---
        start_thumbnail_workers(worker_count=2, logger=server_logger)
        threading.Thread(
            target=lambda: generate_thumbnails_for_folder(
                video_folder=str(akserver_SAVE_DIR), time_sec=1.5, logger=server_logger
            ),
            daemon=True,
        ).start()

        akserver_AUTH_ENABLED = "true"
        run_server(PORT, akserver_SAVE_DIR, akserver_AUTH_ENABLED)

    finally:
        if lock_fd:
            try:
                if sys.platform == "win32":
                    try:
                        msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        server_logger.debug("Error unlocking on Windows.")
                else:
                    try:
                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        server_logger.debug("Error unlocking file.")
            finally:
                lock_fd.close()
                try:
                    lock_file_path.unlink()
                except Exception:
                    server_logger.debug("Could not remove lock file -- ignoring.")
