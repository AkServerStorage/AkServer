# =============================================================================
# akserver - File Handling & Serving (Proprietary Edition)
# =============================================================================
"""
File:           akserver_route_handlers_files.py
Description:    Contains route handling logic for file views, uploads, and downloads.
Author:         AkshAy S (akserver Project)
Version:        1.0.0
License:        akserver Custom Freemium License (See LICENSE.txt)

This software handles core file management operations, including:
- Serving a dynamic HTML page to browse files and folders.
- Securely serving individual files with support for HTTP range requests.
- Handling secure file uploads.

Third-party components used:
- Werkzeug (BSD): Form parsing
- Pillow (PIL) (BSD): Image dimension retrieval
- akserver_route_handlers_thumbnails: Video thumbnail generation

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Python Standard Library Imports

import os
import re
import ssl
import time
import html
import json
import shutil
import socket
import mimetypes
import threading
from urllib.parse import parse_qs, quote, unquote, urlparse

# ------------------------------------------------------------------ Third-party

from werkzeug.formparser import parse_form_data
from PIL import Image

# ------------------------------------------------------------------  Local modules

from akserver_html import get_html
from akserver_config import CONFIG
from akserver_ssl_util import generate_download_token, verify_download_token, verify_upload_token
from akserver_route_handlers_thumbnails import generate_thumbnail_for_video
from akserver_route_handlers import generic_file_svg, _sanitize_relative_path, format_file_size
from akserver_trial_status import trial_required
# ------------------------------------------------------------------ File Browser

@trial_required
def handle_get_view_files(handler):

    def build_breadcrumb(path):
        parts = path.strip("/").split("/") if path else []
        breadcrumb = '<a href="/view_files" class="root-link"></a>'
        current = ""
        for part in parts:
            current += "/" + part
            encoded = quote(current.strip("/"))
            breadcrumb += f'<span class="separator"> / </span><a href="/view_files?folder={encoded}">{
                html.escape(part)}</a>'
        return breadcrumb

    # System or internal folders to exclude from UI and logic
    EXCLUDED_FOLDERS = {
        ".thumbnails",
        ".akserver_tmp",  # any future temp files
        ".akserver_logs",  # if you log into a subfolder
    }

    if handler.AUTH_ENABLED and not handler._is_authenticated():
        handler._redirect("/login")
        return

    parsed_url = urlparse(handler.path)
    query_params = parse_qs(parsed_url.query)
    folder_param = query_params.get("folder", [None])[0]
    breadcrumb_html = ""
    if folder_param:
        breadcrumb_html = f"""
        <div class="breadcrumb-bar">
        <div class="breadcrumb">
            <a href="/view_files">My Drive</a>
            {build_breadcrumb(folder_param)}
        </div>
        </div>
        """

    back_button_html = (
        '<button class="floating-icon-btn back-btn" onclick="history.back()" title="Back">'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" '
        'style="width: 24px; height: 24px;">'
        '<polyline points="15 18 9 12 15 6" />'
        "</svg>"
        "</button>"
    )

    sort_button_html = (
        '<button class="floating-icon-btn sort-btn" onclick="toggleFilterMenu()" title="Filter Files">'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" '
        'style="width: 24px; height: 24px;">'
        '<path d="M3 4h18M6 8h12M10 12h4M13 16h-2M3 20h18" />'
        "</svg>"
        "</button>"
    )

    toggle_view_button_html = (
        '<button class="floating-icon-btn toggle-btn" onclick="toggleView()" title="Switch View">'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" '
        'style="width: 24px; height: 24px;">'
        '<path d="M4 6h16M4 12h16M4 18h16" />'
        "</svg>"
        "</button>"
    )

    folder_path = os.path.abspath(
        os.path.join(handler.SAVE_DIR, folder_param)
        if folder_param
        else handler.SAVE_DIR
    )
    if not folder_path.startswith(os.path.abspath(handler.SAVE_DIR)):
        handler._send_response_data(b"Invalid folder path", code=400)
        return
    
    folder_items_html = ""
    file_items_html = ""
    message_content = ""
    files_found = False

    custom_folder_svg = """
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">
    <defs>
        <linearGradient id="folderGradient" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#f4c842"/>
        <stop offset="100%" stop-color="#f4b400"/>
        </linearGradient>
    </defs>
    <path fill="url(#folderGradient)" stroke="none"
        d="M3 4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V8
            c0-1.1-.9-2-2-2h-8l-2-2H3z"/>
    </svg>
    """

    filter_type = query_params.get("filter", ["all"])[0]

    def is_allowed_file(entry):
        ext = os.path.splitext(entry)[1].lower()

        image_exts = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"]
        video_exts = [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv"]
        doc_exts = [
            ".pdf",
            ".doc",
            ".docx",
            ".odt",
            ".xls",
            ".xlsx",
            ".csv",
            ".tsv",
            ".ods",
            ".ppt",
            ".pptx",
            ".odp",
            ".txt",
            ".rtf",
            ".md",
        ]
        audio_exts = [".mp3", ".wav", ".ogg", ".m4a", ".aac"]
        archive_exts = [".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".iso", ".bin"]

        if filter_type == "images":
            return ext in image_exts
        elif filter_type == "videos":
            return ext in video_exts
        elif filter_type == "docs":
            return ext in doc_exts
        elif filter_type == "audio":
            return ext in audio_exts
        elif filter_type == "archives":
            return ext in archive_exts
        elif filter_type == "others":
            return ext not in (
                image_exts + video_exts + doc_exts + audio_exts + archive_exts
            )

        return True  # "all"

    try:
        if not os.path.exists(folder_path):
            message_content = "Folder not found."
        else:
            entries = sorted(
                [
                    e
                    for e in os.listdir(folder_path)
                    if (
                        is_allowed_file(e)
                        or os.path.isdir(os.path.join(folder_path, e))
                    )
                    and e not in EXCLUDED_FOLDERS
                ],
                key=lambda x: os.path.getmtime(os.path.join(folder_path, x)),
                reverse=True,
            )
            for entry in entries:
                full_path = os.path.join(folder_path, entry)
                rel_path = os.path.relpath(full_path, handler.SAVE_DIR).replace(
                    os.sep, "/"
                )
                token = generate_download_token(rel_path)
                file_url_with_token = f"/get_file?path={quote(rel_path)}&token={token}"
                encoded_url = quote(rel_path)
                escaped_name = html.escape(entry)
                if os.path.isdir(full_path):
                    if entry == ".thumbnails":
                        continue  # Skip internal folders

                    folder_items_html += f"""
                    <li class="file-item folder-item">
                    <a href="/view_files?folder={encoded_url}" style="text-decoration: none; color: inherit;">
                        <div class="media-container folder">
                        {custom_folder_svg}
                        </div>
                    </a>
                    <div class="label-below">{escaped_name}</div>

                    <div class="file-info">
                        <div class="file-name">
                        <a href="/view_files?folder={encoded_url}" style="text-decoration: none; color: inherit;">
                            {escaped_name}
                        </a>
                        </div>
                        <div class="file-meta">Folder</div>
                    </div>
                    </li>
                    """

                elif os.path.isfile(full_path):
                    files_found = True
                    ext = os.path.splitext(entry)[1].lower()
                    file_type = mimetypes.guess_type(entry)[0] or "Unknown"
                    file_size = os.path.getsize(full_path)
                    human_size = format_file_size(file_size)

                    preview_block = ""
                    # --- PREVIEW BLOCK ---
                    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                        try:
                            with Image.open(full_path) as img:
                                width, height = img.size
                        except Exception as e:
                            handler.server_logger.warning(
                                f"Could not get dimensions for {full_path}: {e}"
                            )
                            width, height = 1200, 800

                        preview_block = (
                            f'<a href="{file_url_with_token}" data-pswp-width="{width}" '
                            f'data-pswp-height="{height}" data-caption="{escaped_name}">'
                            f'<img src="{file_url_with_token}" alt="{escaped_name}" loading="lazy"/>'
                            "</a>"
                        )

                    elif ext in [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv"]:
                        thumb_url = "/static/video_file_svg.svg"
                        try:
                            thumb_dir = os.path.join(handler.SAVE_DIR, ".thumbnails")
                            thumb_basename = os.path.splitext(os.path.basename(entry))[
                                0
                            ]
                            thumb_path = os.path.join(
                                thumb_dir, f"{thumb_basename}_thumb.jpg"
                            )
                            if os.path.exists(thumb_path):
                                thumb_url = (
                                    f"/thumbnails/{quote(thumb_basename)}_thumb.jpg"
                                )
                        except Exception as e:
                            handler.server_logger.warning(
                                f"Thumbnail check failed for {entry}: {e}"
                            )

                        full_path = os.path.abspath(
                            os.path.join(handler.SAVE_DIR, rel_path)
                        )
                        handler.server_logger.debug(
                            f"Video file path: {full_path}, exists: {
                                os.path.isfile(full_path)}, readable: {
                                os.access(
                                    full_path, os.R_OK)}"
                        )
                        if not os.path.isfile(full_path) or not os.access(
                            full_path, os.R_OK
                        ):
                            handler.server_logger.warning(
                                f"Skipping video for videoList due to missing or unreadable file: {full_path}"
                            )
                            continue

                        encoded_file_url = f"/get_file?path={quote(rel_path)}"

                        handler.server_logger.info(
                            f"Adding to videoList: {encoded_file_url}"
                        )
                        escaped_name = html.escape(os.path.basename(entry))

                        token = generate_download_token(
                            rel_path
                        ) 

                        preview_block = (
                            f'<div class="video-thumb-wrapper" '
                            f'style="position: relative; width: 100%; height: 100%; display: flex; align-items: center; '
                            f'justify-content: center; overflow: hidden; border-radius: 6px; background-color: #111;">'
                            f'<a href="javascript:void(0);" '
                            f"onclick=\"openVideoModal('{rel_path}', '{token}');\" "
                            f'style="display: block; width: 100%; height: 100%; position: relative;">'
                            f'<img src="{thumb_url}" alt="{escaped_name}" loading="lazy" class="video-thumb-image" '
                            f'style="width: 100%; height: 100%; object-fit: contain; display: block;" />'
                            f'<svg class="play-icon-overlay" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" '
                            f'style="position: absolute; top: 6px; right: 6px; width: 16px; height: 16px;">'
                            f'<path d="M8 5v14l11-7z"/></svg></a></div>'
                        )

                    else:
                        preview_block = generic_file_svg(ext)

                    media_extensions = [
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".gif",
                        ".webp",
                        ".mp4",
                        ".mov",
                        ".avi",
                        ".webm",
                        ".mkv",
                    ]
                    li_class = "file-item"
                    if ext not in media_extensions:
                        li_class += " compact-icon"

                    media_html = f'<div class="media-container">{preview_block}</div>'
                    if "compact-icon" in li_class:
                        media_html += f'<div class="label-below">{escaped_name}</div>'

                    download_token = generate_download_token(rel_path)
                    file_items_html += (
                        f'<li class="{li_class}">'
                        f"{media_html}"
                        f'<div class="file-info">'
                        f'<div class="file-name">{escaped_name}</div>'
                        f'<div class="file-meta">{file_type} • {human_size}</div>'
                        f"</div>"
                        f'<form method="POST" action="/download" class="download-overlay-flat">'
                        f'<input type="hidden" name="filename" value="{rel_path}">'
                        f'<input type="hidden" name="token" value="{download_token}">'
                        f'<button type="submit" class="download-text-btn-flat" title="Download">'
                        f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" '
                        f'class="bi bi-cloud-arrow-down" viewBox="0 0 16 16">'
                        f'<path fill-rule="evenodd" d="M7.646 10.854a.5.5 0 0 0 .708 0l2-2a.5.5 0 0 0-.708-.708L8.5 '
                        f'9.293V5.5a.5.5 0 0 0-1 0v3.793L6.354 8.146a.5.5 0 1 0-.708.708z"/>'
                        f'<path d="M4.406 3.342A5.53 5.53 0 0 1 8 2c2.69 0 4.923 2 5.166 4.579C14.758 6.804 16 '
                        f"8.137 16 9.773 16 11.569 14.502 13 12.687 13H3.781C1.708 13 0 11.366 0 9.318c0-1.763 "
                        f"1.266-3.223 2.942-3.593 .143-.863.698-1.723 1.464-2.383m.653.757c-.757.653-1.153 1.44-1.153 "
                        f"2.056v.448l-.445.049C2.064 6.805 1 7.952 1 9.318 1 10.785 2.23 12 3.781 12h8.906C13.98 12 "
                        f"15 10.988 15 9.773c0-1.216-1.02-2.228-2.313-2.228h-.5v-.5C12.188 4.825 10.328 3 8 3a4.53 "
                        f'4.53 0 0 0-2.941 1.1z"/>'
                        f"</svg>"
                        f"</button>"
                        f"</form>"
                        f"</li>"
                    )

            try:
                html_content = get_html(
                    "akserver_html_view_files.html",
                    message_placeholder=(
                        f"<div class='message info'>{html.escape(message_content)}</div>"
                        if message_content else ""
                    ),
                    back_button_placeholder=back_button_html,
                    sort_button_placeholder=sort_button_html,
                    toggle_view_button_placeholder=toggle_view_button_html,
                    build_breadcrumb_placeholder=breadcrumb_html,
                    folder_items=folder_items_html,
                    file_items=file_items_html,
                )
            except Exception as e:
                handler._send_response_data(f"Template error: {e}".encode(), code=500)
                return
            if not entries:
                folder_items_html = (
                    "<div class='message info'>This folder is empty.</div>"
                )
            elif not files_found:
                message_content = "No files found in this folder."

        html_content = get_html(
            "akserver_html_view_files.html",
            message_placeholder=(
                f"<div class='message info'>{html.escape(message_content)}</div>"
                if message_content else ""
            ),
            back_button_placeholder=back_button_html,
            sort_button_placeholder=sort_button_html,
            toggle_view_button_placeholder=toggle_view_button_html,
            build_breadcrumb_placeholder=breadcrumb_html,
            folder_items=folder_items_html,
            file_items=file_items_html,
        )
        handler._send_response_data(html_content.encode("utf-8"))
    except Exception as e:
        handler.server_logger.error(
            f"Error in handle_get_view_files: {e}", exc_info=True
        )
        handler._send_response_data(b"Internal Server Error", code=500)

# ------------------------------------------------------------------ File Download & Streaming
@trial_required
def handle_get_file(handler):

    try:
        parsed_url = urlparse(handler.path)
        query_params = parse_qs(parsed_url.query)

        file_path = unquote(query_params.get("path", [None])[0])
        if not file_path:
            handler.server_logger.error("Missing file path in request")
            handler._send_response_data(b"Missing file path", code=400)
            return

        token = query_params.get("token", [None])[0]

        if handler.AUTH_ENABLED:
            is_token_valid = token and verify_download_token(file_path, token)
            is_device_authenticated = getattr(
                handler, "authenticated_via_device_token", False
            )

            if not is_token_valid and not is_device_authenticated:
                handler.server_logger.warning(
                    f"Invalid or missing token for: {file_path}"
                )
                handler._send_response_data(b"Unauthorized", code=403)
                return

        full_path = os.path.abspath(os.path.join(handler.SAVE_DIR, file_path))
        handler.server_logger.info(f"[GET_FILE] full_path check: {full_path}")
        handler.server_logger.debug(
            f"[GET_FILE] Resolved file path: {full_path}, SAVE_DIR: {
                handler.SAVE_DIR}, exists: {
                os.path.isfile(full_path)}, readable: {
                os.access(
                    full_path,
                    os.R_OK)}, initial path: '{file_path}'"
        )
        if not full_path.startswith(os.path.abspath(handler.SAVE_DIR)):

            # Prevent access to internal akserver system folders
            blocked_names = [".thumbnails", ".akserver_tmp", ".akserver_logs"]
            for part in full_path.split(os.sep):
                if part in blocked_names:
                    handler.server_logger.warning(
                        f"Access to restricted internal path: {file_path}"
                    )
                    handler._send_response_data(b"Access Denied", code=403)
                    return

        if not os.path.isfile(full_path) or not os.access(full_path, os.R_OK):
            handler.server_logger.error(f"File not found or not readable: {full_path}")
            handler._send_response_data(b"File not found", code=404)
            return

        ext = os.path.splitext(full_path)[1].lower()
        mime_types = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".webm": "video/webm",
            ".mkv": "video/x-matroska",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(
            ext, mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        )

        file_size = os.path.getsize(full_path)
        range_header = handler.headers.get("Range")
        start = 0
        end = file_size - 1
        content_length = file_size

        if range_header:
            range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = (
                    int(range_match.group(2)) if range_match.group(2) else file_size - 1
                )
                if start >= file_size or end >= file_size or start > end:
                    handler.server_logger.error(
                        f"Invalid range request: bytes={start}-{end}/{file_size}"
                    )
                    handler.send_response(416)
                    handler.send_header("Content-Range", f"bytes */{file_size}")
                    handler.end_headers()
                    return
                content_length = end - start + 1
                handler.server_logger.debug(
                    f"Range request: bytes={start}-{end}/{file_size}"
                )
                handler.send_response(206)
                handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            else:
                handler.server_logger.error(f"Invalid range header: {range_header}")
                handler._send_response_data(b"Invalid range", code=416)
                return
        else:
            handler.send_response(200)

        handler.send_header("Content-Type", mime_type)
        handler.send_header("Content-Length", str(content_length))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Access-Control-Allow-Methods", "GET")
        handler.send_header("Keep-Alive", "timeout=60, max=100")
        handler.end_headers()

        if hasattr(handler, "connection") and handler.connection:
            handler.connection.settimeout(90)
            handler.connection.setsockopt(
                socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024
            )
            handler.connection.setsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024
            )
            handler.connection.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)

        try:
            with open(full_path, "rb") as f:
                retry_count = 0
                max_retries = 10
                chunk_size = 8 * 1024
                if range_header:
                    f.seek(start)
                    remaining = content_length
                    sent_bytes = 0

                    while remaining > 0:
                        chunk = f.read(min(chunk_size, remaining))
                        if not chunk:
                            handler.server_logger.warning(
                                f"Unexpected end of file: {file_path}"
                            )
                            break

                        try:
                            handler.wfile.write(chunk)
                            handler.wfile.flush()
                            remaining -= len(chunk)
                            sent_bytes += len(chunk)
                            handler.server_logger.debug(
                                f"Sent {len(chunk)} bytes, remaining: {remaining}"
                            )

                        except (
                            ConnectionResetError,
                            ConnectionAbortedError,
                            socket.error,
                            ssl.SSLError,
                            BrokenPipeError,
                        ) as e:
                            handler.server_logger.warning(
                                f"Connection error while streaming {file_path} at offset {sent_bytes}: {e}"
                            )
                            if hasattr(e, "errno") and e.errno in (10053, 10054):
                                handler.server_logger.warning(
                                    f"Fatal socket error {e.errno}, aborting stream for {file_path}"
                                )
                                return
                            if "10054" in str(e) or "10053" in str(e):
                                handler.server_logger.warning(
                                    f"Detected 10054/10053 in error string, aborting stream for {file_path}"
                                )
                                return
                            if handler.connection.fileno() == -1:
                                handler.server_logger.warning(
                                    f"Socket closed by client for {file_path}, exiting stream."
                                )
                                return
                            if (
                                retry_count < max_retries
                                and handler.connection.fileno() != -1
                            ):
                                retry_count += 1
                                time.sleep(2 * retry_count)
                                continue
                            handler.server_logger.warning(
                                f"Max retries reached for {file_path}"
                            )
                            return

                        except socket.timeout:
                            handler.server_logger.warning(
                                f"Socket timeout while streaming {file_path}"
                            )
                            return

                else:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        try:
                            handler.wfile.write(chunk)
                            handler.wfile.flush()
                            handler.server_logger.debug(f"Sent {len(chunk)} bytes")
                            retry_count = 0
                        except (
                            ConnectionResetError,
                            ConnectionAbortedError,
                            socket.error,
                            ssl.SSLError,
                            BrokenPipeError,
                        ) as e:
                            handler.server_logger.warning(
                                f"Connection error while streaming {file_path}: {e}"
                            )
                            if (
                                retry_count < max_retries
                                and handler.connection.fileno() != -1
                            ):
                                retry_count += 1
                                handler.server_logger.debug(
                                    f"Retrying ({retry_count}/{max_retries}) after error"
                                )
                                time.sleep(2 * retry_count)
                                continue
                            handler.server_logger.warning(
                                f"Max retries reached or connection closed for {file_path}"
                            )
                            return
                        except socket.timeout:
                            handler.server_logger.warning(
                                f"[Timeout] Streaming interrupted for: {file_path}"
                            )
                            return
        finally:
            if hasattr(handler, "connection") and handler.connection:
                handler.connection.settimeout(None)
                handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
                handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 0)
                handler.connection.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 0)
    except Exception as e:
        handler.server_logger.error(f"Error in handle_get_file: {e}", exc_info=True)
        handler._send_response_data(b"Internal Server Error", code=500)

# ------------------------------------------------------------------ File Upload

def handle_post_upload(handler):

    # --- Authentication Check ---
    if handler.AUTH_ENABLED and not handler._is_authenticated():
        handler.server_logger.warning(
            f"Unauthorized upload attempt from {handler.client_address[0]}"
        )
        handler._send_response_data(
            json.dumps({"success": False, "message": "Authentication required."}).encode(),
            "application/json",
            403,
        )
        return

    try:
        # --- Parse Form Data ---
        content_length = int(handler.headers.get("Content-Length", "0"))
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": handler.headers["Content-Type"],
            "CONTENT_LENGTH": str(content_length),
            "wsgi.input": handler.rfile,
        }
        _, form, files = parse_form_data(environ)

        # --- Secure Token Validation ---
        upload_token = form.get("upload_token", "")
        if isinstance(upload_token, list):
            upload_token = upload_token[0]
        if not verify_upload_token(upload_token):
            handler.server_logger.warning(
                f"Invalid or expired upload token from {handler.client_address[0]}"
            )
            handler._send_response_data(
                json.dumps({"success": False, "message": "Invalid or expired upload token."}).encode(),
                "application/json",
                403,
            )
            return

        # --- Prepare Upload ---
        uploaded_files_count = 0
        save_dir = CONFIG["save_dir"]
        os.makedirs(save_dir, exist_ok=True)

        def file_generator():
            for filestorage in files.getlist("files[]"):
                if filestorage.filename and ".trashed" not in filestorage.filename.lower():
                    yield filestorage

        thumbnail_queue = []

        for filestorage in file_generator():
            filename_sanitized = _sanitize_relative_path(filestorage.filename)
            filepath = os.path.join(save_dir, filename_sanitized)

            # Prevent directory traversal
            if not filepath.startswith(save_dir + os.sep):
                handler.server_logger.warning(f"Traversal attempt: {filepath}")
                continue

            # Skip existing files
            if os.path.exists(filepath):
                handler.server_logger.info(f"Skipped existing file: {filepath}")
                continue

            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            # Save file efficiently using buffered copy
            with open(filepath, "wb") as f:
                shutil.copyfileobj(filestorage.stream, f, length=1024*1024)  # 1MB buffer

            handler.server_logger.info(
                f"Uploaded file: '{filename_sanitized}' to '{filepath}' from {handler.client_address[0]}"
            )
            uploaded_files_count += 1

            # Queue video thumbnails
            if filename_sanitized.lower().endswith((".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv")):
                thumbnail_queue.append(filepath)

        # --- Async Thumbnail Generation (batch) ---
        if thumbnail_queue:
            def _generate_thumbnails():
                for video_path in thumbnail_queue:
                    try:
                        generate_thumbnail_for_video(video_path, save_dir, time_sec=1.5)
                        handler.server_logger.info(f"Thumbnail generated: {video_path}")
                    except Exception as e:
                        handler.server_logger.warning(f"Thumbnail failed for {video_path}: {e}")

            threading.Thread(target=_generate_thumbnails, daemon=True).start()

        # --- Response ---
        response_message = (
            {"success": True, "message": f"Sync complete. {uploaded_files_count} files uploaded."}
            if uploaded_files_count > 0
            else {"success": False, "message": "No new files uploaded."}
        )
        handler._send_response_data(json.dumps(response_message).encode(), "application/json")

    except Exception as e:
        handler.server_logger.error(f"Upload failed: {e}", exc_info=True)
        handler._send_response_data(
            json.dumps({"success": False, "message": f"Server error during upload: {e}"}).encode(),
            "application/json",
            500,
        )

@trial_required
def route_post_upload(handler):
    """
    Wrapper for POST /upload with robust error handling.
    Delegates to the improved handle_post_upload().
    """
    try:
        handle_post_upload(handler)
    except ConnectionResetError:
        handler.server_logger.warning(
            f"Upload interrupted: connection reset by {handler.client_address[0]}"
        )
    except Exception as e:
        handler.server_logger.error(
            f"Unexpected error during file upload from {handler.client_address[0]}: {e}",
            exc_info=True,
        )
        handler._send_response_data(
            json.dumps(
                {"success": False, "message": "Internal Server Error during upload."}
            ).encode(),
            "application/json",
            500,
        )

@trial_required
def handle_post_download(handler):
    """Fast, secure streaming download handler."""

    # --- Ensure authentication ---
    if not handler._ensure_authenticated():
        return

    # --- Validate Content-Length ---
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length == 0:
        handler.server_logger.warning(
            f"Content-Length zero/missing for /download POST from {handler.client_address[0]}"
        )
        handler.send_error(400, "Bad Request: Content-Length missing or zero.")
        return

    # --- Read and decode POST body ---
    try:
        post_data_bytes = handler.rfile.read(content_length)
        post_data_str = post_data_bytes.decode("utf-8")
    except UnicodeDecodeError:
        handler.server_logger.warning(
            f"Invalid POST encoding from {handler.client_address[0]}"
        )
        handler.send_error(400, "Bad Request: Invalid encoding.")
        return

    # --- Parse query string ---
    parsed_data = parse_qs(post_data_str)
    filename_list = parsed_data.get("filename", [])
    token_list = parsed_data.get("token", [])
    token = token_list[0] if token_list else None

    if not filename_list:
        handler.server_logger.warning(
            f"No filename in /download POST from {handler.client_address[0]}"
        )
        handler.send_error(400, "Bad Request: Filename missing.")
        return

    raw_filename = filename_list[0]

    # --- Token verification ---
    if handler.AUTH_ENABLED and not verify_download_token(raw_filename, token):
        handler.server_logger.warning(
            f"Unauthorized token attempt for download: {raw_filename}"
        )
        handler._send_response_data(b"Access denied", code=403)
        return

    # --- Validate filepath securely ---
    abs_filepath = handler._get_validated_filepath(raw_filename)
    if not abs_filepath:
        return

    # --- Stream file efficiently ---
    try:
        file_size = os.path.getsize(abs_filepath)
        mimetype, _ = mimetypes.guess_type(abs_filepath)
        mimetype = mimetype or "application/octet-stream"

        handler.send_response(200)
        handler.send_header("Content-Type", mimetype)
        handler.send_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(abs_filepath)}"',
        )
        handler.send_header("Content-Length", str(file_size))
        handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        handler.send_header("Pragma", "no-cache")
        handler.send_header("Expires", "0")
        handler.end_headers()

        # --- Stream in chunks: larger for faster LAN transfers ---
        chunk_size = 2 * 1024 * 1024  # 2 MB
        with open(abs_filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()

        handler.server_logger.info(
            f"File served: '{os.path.basename(abs_filepath)}' to {handler.client_address[0]}"
        )

    except BrokenPipeError:
        handler.server_logger.warning(
            f"Broken pipe sending '{os.path.basename(abs_filepath)}' to {handler.client_address[0]}"
        )
    except Exception as e:
        handler.server_logger.error(
            f"Error sending file '{os.path.basename(abs_filepath)}' to {handler.client_address[0]}: {e}",
            exc_info=True,
        )
        handler._send_response_data(
            json.dumps({"success": False, "message": "Download failed."}).encode(),
            "application/json",
            500,
        )
