# =============================================================================
# akserver - Route Handlers (Proprietary Edition)
# =============================================================================
"""
File:           akserver_route_handlers.py
Description:    Contains route handling logic for file views, uploads, previews.
Author:         AkshAy S (akserver Project)
Version:        1.0.0
License:        akserver Custom Freemium License (See LICENSE.txt)

This software provides core server-side logic for the akserver application, including:
- Secure file upload and download endpoints.
- Dynamic file and directory listings.
- Image and video thumbnail generation for previews.
- Login and logout authentication handlers.


Third-party components used:
- moviepy (MIT): Video thumbnail generation
- Pillow (PIL) (BSD): Image resizing and saving
- Werkzeug (BSD): Form parsing

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Python Standard Library Imports

import mimetypes
import os
import platform
import re
import shutil
import time
import unicodedata

# ------------------------------------------------------------------ Local Module Imports

from akserver_html import get_html
from akserver_ssl_util import generate_download_token, get_or_create_device_id

# ------------------------------------------------------------------ Constants & Configuration

# Regex to strip non-alphanumeric, non-dot, non-underscore, non-hyphen characters
_filename_strip_re = re.compile(r"[^A-Za-z0-9_.-]")

# Reserved Windows Device Filenames (e.g., CON, PRN, AUX)
_windows_device_files = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}

BUNDLED_FILES_PATH = os.path.join(os.path.dirname(__file__), "static")

# Comprehensive color map for file extensions, used for dynamic SVG icons
EXT_COLOR_MAP = {
    # Document Files
    ".pdf": "#d32f2f",  # Red
    ".doc": "#1565c0",  # Blue
    ".docx": "#1565c0",
    ".odt": "#1e88e5",  # Lighter Blue
    ".xls": "#2e7d32",  # Green
    ".xlsx": "#2e7d32",
    ".csv": "#43a047",
    ".tsv": "#388e3c",
    ".ods": "#66bb6a",
    ".ppt": "#d84315",  # Orange
    ".pptx": "#d84315",
    ".odp": "#fb8c00",
    # Text & Config
    ".txt": "#607d8b",  # Gray-Blue
    ".rtf": "#78909c",
    ".md": "#546e7a",
    ".log": "#455a64",
    ".cfg": "#37474f",
    ".conf": "#37474f",
    ".ini": "#37474f",
    ".env": "#455a64",
    ".json": "#f4a261",  # Light Orange
    ".yaml": "#fbc02d",
    ".yml": "#fbc02d",
    # Audio
    ".mp3": "#00acc1",
    ".wav": "#26c6da",
    ".ogg": "#0097a7",
    ".m4a": "#00bcd4",
    ".aac": "#00bcd4",
    # Archives
    ".zip": "#ff9800",
    ".rar": "#f57c00",
    ".7z": "#ef6c00",
    ".tar": "#fb8c00",
    ".gz": "#ff7043",
    ".xz": "#f4511e",
    ".iso": "#5d4037",
    ".bin": "#3e2723",
    # Executables
    ".exe": "#673ab7",
    ".msi": "#512da8",
    ".sh": "#5e35b1",
    ".bat": "#7e57c2",
    ".app": "#9575cd",
    # Programming
    ".py": "#3776ab",
    ".js": "#f7df1e",
    ".ts": "#3178c6",
    ".html": "#e44d26",
    ".htm": "#e44d26",
    ".css": "#264de4",
    ".c": "#0277bd",
    ".cpp": "#01579b",
    ".java": "#d32f2f",
    ".cs": "#512da8",
    ".php": "#6e5494",
    ".rb": "#e91e63",
    ".go": "#00acc1",
    ".rs": "#8d6e63",
    # Misc / System
    ".bak": "#90a4ae",
    ".tmp": "#b0bec5",
    ".db": "#8e24aa",
    ".skp": "#ff7043",
    ".blend": "#ffa726",
    ".apk": "#43a047",
}

# ------------------------------------------------------------------ Path Sanitization Functions

def _sanitize_path_component(component: str) -> str:
    """Sanitizes a single path component (filename or directory name)."""

    # Normalize Unicode characters
    component = unicodedata.normalize("NFKD", component)

    # Encode to ASCII, ignoring unrepresentable characters, then decode back
    component = component.encode("ascii", "ignore").decode("ascii")

    # Replace any characters not allowed in filenames with underscores
    component = _filename_strip_re.sub("_", component).strip("._")

    # Handle Windows reserved names
    if os.name == "nt" and component.upper() in _windows_device_files:
        component = f"_{component}"  # Prepend underscore to avoid conflict

    return component


def _sanitize_relative_path(rel_path: str) -> str:
    """Sanitizes a relative path, preserving directory structure."""
    parts = rel_path.split(
        "/"
    )  # Always split by forward slash as webkitRelativePath uses it
    sanitized_parts = []
    for part in parts:
        if part == "" or part == ".":  # Skip empty parts or current directory
            continue
        if part == "..":  # Prevent directory traversal
            continue
        sanitized_parts.append(_sanitize_path_component(part))
    return os.path.join(*sanitized_parts)  # Rejoin with OS-specific separator

# ------------------------------------------------------------------ General Utility Functions


def handle_get_root(handler, message):
    """Handles GET requests for the root path ('/')."""

    if handler.AUTH_ENABLED and not handler._is_authenticated():
        handler._redirect("/login")
        return

    logout_link = (
        '<a href="/logout" class="logout-link">Logout</a>'
        if handler.AUTH_ENABLED
        else ""
    )
    trial_message_html = " "
    upload_token = generate_download_token("upload_access")
    device_id = get_or_create_device_id()
    cache_buster = int(time.time())
    device_os = platform.system() + " " + platform.release()

    html_content = get_html(
        "akserver_html_upload.html",
        logout_placeholder=logout_link,
        message_placeholder=f"<div class='message'>{message}</div>" if message else "",
        trial_message_placeholder=trial_message_html,
        upload_token=upload_token,
        device_id=device_id,
        cache_buster=cache_buster,
        os=device_os,
        version="1.0.0",
    )

    handler._send_response_data(html_content.encode("utf-8"))


def format_file_size(bytes_count):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_count < 1024:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024
    return f"{bytes_count:.1f} PB"


def generic_file_svg(extension):
    ext = extension.lower()
    base_color = EXT_COLOR_MAP.get(ext, "#9e9e9e")
    text_color = "#ffffff"
    label = ext.strip(".").upper()[:4] or "FILE"

    return f"""
    <div class="media-container">
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">
        <rect width="24" height="24" rx="4" fill="{base_color}" />
        <text x="50%" y="60%" text-anchor="middle" font-size="8" fill="{text_color}"
              font-family="Segoe UI, sans-serif" font-weight="bold">{label}</text>
      </svg>
    </div>
    """


def handle_get_static_file(handler, path):
    """Handles GET requests for static files by serving the requested path."""

    relative_path = path.replace("/static/", "", 1)
    file_path = os.path.join(BUNDLED_FILES_PATH, relative_path)
    
    # Check for directory traversal attempts
    abs_bundled_path = os.path.abspath(BUNDLED_FILES_PATH)
    abs_requested_path = os.path.abspath(file_path)
    
    if not abs_requested_path.startswith(abs_bundled_path):
        handler.server_logger.warning(
            f"Directory traversal attempt for static file: '{path}' from {handler.client_address[0]}"
        ) 
        handler.send_error(403, "Forbidden: Access denied.") 
        return 


    if os.path.exists(file_path) and os.path.isfile(file_path): 
        try: 
            mime_type, _ = mimetypes.guess_type(file_path) 
            if mime_type is None: 
                mime_type = "application/octet-stream" 
            
            handler.send_response(200)
            handler.send_header("Content-type", mime_type)
            handler.send_header("Content-Length", str(os.path.getsize(file_path)))
            handler.send_header("Cache-Control", "public, max-age=3600")
            handler.end_headers()
            
            with open(file_path, "rb") as f: 
                shutil.copyfileobj(f, handler.wfile) 

        except Exception as e: 
            handler.server_logger.error(f"Error serving static file {path}: {e}", exc_info=True) 
            handler.send_error(500, "Internal Server Error.") 
    else: 
        handler.send_error(404, "Static file not found.") 

    return
