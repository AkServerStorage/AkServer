import os
import sys
import json
import shutil
from urllib.parse import parse_qs, quote, unquote
import html # For XSS protection
import hashlib
import mimetypes
from werkzeug.formparser import parse_form_data

from AkServer_HTML import UPLOAD_FORM_HTML, LOGIN_FORM_HTML, VIEW_FILES_HTML, DEVICE_NAME_FORM_HTML 
import AkServer_auth
import AkServer_trusted_device_manager 

def _get_trial_message_html(handler) -> str:
    """Helper function to generate trial status HTML."""
    if hasattr(handler, 'trial_manager_instance') and handler.trial_manager_instance:
        is_trial_active, days_left, expiry_dt = handler.trial_manager_instance.get_trial_status()
        if not is_trial_active and expiry_dt: # Expired
            return "<div class='trial-status trial-expired'>Trial Expired.</div>"
        if is_trial_active and days_left is not None:
            return f"<div class='trial-status trial-active'>Trial: {days_left} days remaining.</div>"
    return "<div class='trial-status trial-unavailable'>Trial status unavailable.</div>" # Fallback

def handle_get_root(handler, message):
    """Handles GET requests for the root path ('/')."""
    trial_message_html = _get_trial_message_html(handler)

    if handler.AUTH_ENABLED and not handler._is_authenticated():
        handler._redirect("/login")
        return
    
    logout_link = '<a href="/logout" class="logout-link">Logout</a>' if handler.AUTH_ENABLED else ''
    

    html_content = UPLOAD_FORM_HTML.format(
        logout_placeholder=logout_link, # Safe, server-generated
        message_placeholder=f"<div class='message'>{message}</div>" if message else "",
        trial_message_placeholder=trial_message_html
    )

    handler._send_response_data(html_content.encode('utf-8'))

def handle_get_login_page(handler, message):
    """Handles GET requests for the /login path."""
    if handler.AUTH_ENABLED:
        if handler._is_authenticated():
            handler._redirect("/")
            return
        html_content = LOGIN_FORM_HTML.format(message_placeholder=f"<div class='message'>{message}</div>" if message else "") # type: ignore
        handler._send_response_data(html_content.encode('utf-8'))
    else:
        handler._redirect("/")

def handle_get_view_files(handler):
    """Handles GET requests for /view_files."""
    trial_message_html = _get_trial_message_html(handler)

    if handler.AUTH_ENABLED and not handler._is_authenticated():
        handler._redirect("/login")
        return

    logout_link_html = '<a href="/logout" class="logout-link">Logout</a>' if handler.AUTH_ENABLED else ''
    file_list_html = ""
    files_found = False
    message_content = ""
    message_class = "info"

    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg')
    video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.webm')

    try:
        if not os.path.exists(handler.SAVE_DIR):
            message_content = "Upload directory has not been created yet. Upload a file to create it."
            handler.server_logger.info(f"Save directory {handler.SAVE_DIR} does not exist for /view_files.")
        else:
            for item_name in sorted(os.listdir(handler.SAVE_DIR)):
                item_path = os.path.join(handler.SAVE_DIR, item_name)
                if os.path.isfile(item_path):
                    files_found = True
                    filename_url_encoded = quote(item_name)
                    escaped_item_name = html.escape(item_name)
                    file_link = f'/files/{filename_url_encoded}'

                    file_list_html += f'<li class="file-item">'
                    file_list_html += '<div class="media-container">'
                    item_lower = item_name.lower()
                    if item_lower.endswith(image_extensions):
                        file_list_html += f'<a href="{file_link}" target="_blank"><img src="{file_link}" alt="Preview of {escaped_item_name}"></a>'
                    elif item_lower.endswith(video_extensions):
                        guessed_type, _ = mimetypes.guess_type(item_name)
                        video_type = guessed_type or "video/mp4"
                        file_list_html += f'<video controls><source src="{file_link}" type="{video_type}">Your browser does not support the video tag.</video>'
                    else:
                        file_list_html += f'<div class="no-preview"><span>No preview available.<br>Click name to view/download.</span></div>'
                    file_list_html += '</div>'
                    file_list_html += f'<a href="{file_link}" target="_blank" class="file-name-link" title="{escaped_item_name}">{escaped_item_name}</a>'
                    file_list_html += (
                        f'<form method="POST" action="/download" style="text-align: center; margin-top: 3px; margin-bottom: 3px;">\n' # NOSONAR
                            f'    <input type="hidden" name="filename" value="{html.escape(item_name)}">\n' # Value is data, should be original. HTML escaping for attribute context.
                        f'    <button type="submit" style="padding: 3px 7px; font-size: 0.7em; background-color: #007bff; color: white; border: none; border-radius: 3px; cursor: pointer;">Download</button>\n'
                        f'</form>\n')
                    file_list_html += f'</li>'
            if not files_found:
                message_content = "No files uploaded yet."
        html_content = VIEW_FILES_HTML.format(
            logout_placeholder=logout_link_html,
            file_list_items=file_list_html if files_found else "<li class='file-item'>No files found.</li>",
            message_placeholder=f"<div class='message {message_class}'>{html.escape(message_content)}</div>" if message_content else "",
            trial_message_placeholder=trial_message_html
        ) # type: ignore
        handler._send_response_data(html_content.encode('utf-8'))
    except Exception as e:
        handler.server_logger.error(f"Error generating file list for /view_files from {handler.client_address[0]}: {e}", exc_info=True)
        error_html = VIEW_FILES_HTML.format(
            logout_placeholder=logout_link_html,
            file_list_items="<li class='file-item'>Error loading files.</li>",
            message_placeholder=f"<div class='message error'>Server error occurred while listing files.</div>",
            trial_message_placeholder=trial_message_html
        ) # type: ignore
        handler._send_response_data(error_html.encode('utf-8'), code=500)


def handle_post_login(handler):
    """Handles POST requests for the /login path."""
    if not handler.AUTH_ENABLED:
        handler._redirect("/")
        return

    content_length = int(handler.headers['Content-Length'])
    post_data = handler.rfile.read(content_length)
    params = parse_qs(post_data.decode('utf-8'))
    submitted_otp = params.get('otp', [None])[0]
    client_ip = handler.client_address[0]

    verified, message = AkServer_auth.verify_otp_and_mark_pending(submitted_otp, client_ip)

    if verified:
        handler._redirect("/register_device_name")
    else:
        handler._redirect(f"/login?message={quote(message)}")

def handle_post_submit_device_name(handler):
    """Handles POST requests for /submit_device_name."""
    if not handler.AUTH_ENABLED:
        handler._redirect("/")
        return

    client_ip = handler.client_address[0]
    if not AkServer_auth.is_client_pending_registration(client_ip):
        handler.server_logger.warning(f"Unauthorized POST to /submit_device_name from {client_ip}. Redirecting to login.")
        handler._redirect("/login?message=Invalid session. Please login again.")
        return

    content_length = int(handler.headers['Content-Length'])
    post_data = handler.rfile.read(content_length)
    params = parse_qs(post_data.decode('utf-8'))
    submitted_device_name = params.get('device_name', [''])[0].strip()

    if not submitted_device_name:
        handler.server_logger.warning(f"Device name not provided by {client_ip} during registration.")
        handler._redirect("/register_device_name?message=Device%20name%20is%20required.")
        return

    new_device_token = AkServer_auth.complete_device_registration(
        client_ip, submitted_device_name,
        AkServer_trusted_device_manager,
        handler.TRUSTED_DEVICES_FILE
    )

    if new_device_token:
        handler._redirect("/", device_token_to_set=new_device_token)
    else:
        handler._redirect("/login?message=Device registration failed. Please try again.")

def handle_post_upload(handler):
    """Handles POST requests for /upload."""
    if handler.AUTH_ENABLED and not handler._is_authenticated():
        handler.server_logger.warning(f"Unauthorized upload attempt from {handler.client_address[0]}")
        handler._send_response_data(json.dumps({"success": False, "message": "Authentication required."}).encode(), 'application/json', 403)
        return

    try:
        if not os.path.exists(handler.SAVE_DIR):
            os.makedirs(handler.SAVE_DIR, exist_ok=True)
            handler.server_logger.info(f"Created save directory: {handler.SAVE_DIR}")
        
        environ = {
            'wsgi.input': handler.rfile,
            'wsgi.errors': sys.stderr,
            'CONTENT_LENGTH': handler.headers.get('Content-Length', '0'),
            'CONTENT_TYPE': handler.headers.get('Content-Type', ''),
            'REQUEST_METHOD': 'POST'
        }
        stream, form, files = parse_form_data(environ)

        uploaded_files_info = []
        if 'files[]' in files:
            files_to_upload = files.getlist('files[]')
            for file_storage in files_to_upload:
                rel_path = file_storage.filename.replace("\\", "/")
                if rel_path.count("/") > 1 or ".trashed" in rel_path.lower():
                    handler.server_logger.info(f"Skipped: {file_storage.filename}")
                    continue
                filename = os.path.basename(rel_path)
                filename = "".join(c for c in filename if c.isalnum() or c in ('.', '_', '-')).rstrip()
                if not filename:
                    continue
                filepath = os.path.join(handler.SAVE_DIR, filename)
                file_data = file_storage.read()
                is_duplicate = False
                if os.path.exists(filepath):
                    with open(filepath, 'rb') as existing_file:
                        if hashlib.md5(existing_file.read()).hexdigest() == hashlib.md5(file_data).hexdigest():
                            is_duplicate = True
                if is_duplicate:
                    handler.server_logger.info(f"Duplicate file skipped: {filename}")
                    continue
                with open(filepath, 'wb') as f:
                    f.write(file_data)
                uploaded_files_info.append(filename)
                handler.server_logger.info(f"Received and saved: {filename} to {filepath} from {handler.client_address[0]}")
        
        response_message = {"success": True, "message": "Files uploaded successfully.", "files": uploaded_files_info} if uploaded_files_info else {"success": False, "message": "No new files were uploaded."}
        handler._send_response_data(json.dumps(response_message).encode(), 'application/json')

    except Exception as e:
        handler.server_logger.error(f"Error processing upload from {handler.client_address[0]}: {e}", exc_info=True)
        handler._send_response_data(json.dumps({"success": False, "message": f"Server error during upload: {e}"}).encode(), 'application/json', 500)