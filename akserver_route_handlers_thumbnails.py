# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================
"""
Description:    Provides utilities for generating and serving video and image thumbnails.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025-present AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""


# ------------------------------------------------------------------ Python Standard Library Imports

import os
import mimetypes
import ctypes
import threading
from urllib.parse import unquote
import queue

# ------------------------------------------------------------------ Third-party

from moviepy.editor import VideoFileClip
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

# ------------------------------------------------------------------  Local modules

from akserver_config import LOGGER as server_logger


# ------------------------------------------------------------------  Asynchronous Thumbnail Worker

_thumbnail_queue = queue.Queue()
_thumbnail_workers_started = False

def _thumbnail_worker(logger=None, time_sec=1.5):
    """Worker thread that processes the thumbnail queue."""

    while True:
        try:
            file_path, save_dir = _thumbnail_queue.get()
            if file_path is None:
                break  
            thumb_path = generate_thumbnail_for_video(file_path, save_dir, time_sec)
            if thumb_path and logger:
                logger.info(f"[Async Thumbnail] Generated: {thumb_path}")
        except Exception as e:
            if logger:
                logger.warning(f"[Async Thumbnail] Failed for {file_path}: {e}")
        finally:
            _thumbnail_queue.task_done()


def start_thumbnail_workers(worker_count=2, logger=None):
    """Start background thumbnail worker threads (only once)."""

    global _thumbnail_workers_started
    if _thumbnail_workers_started:
        return
    _thumbnail_workers_started = True

    for i in range(worker_count):
        t = threading.Thread(target=_thumbnail_worker, daemon=True, args=(logger,))
        t.name = f"ThumbnailWorker-{i+1}"
        t.start()


def enqueue_thumbnail(file_path, save_dir):
    """Add a file to the async thumbnail queue."""

    _thumbnail_queue.put((file_path, save_dir))


def stop_thumbnail_workers():
    """Send stop signals to all worker threads."""

    worker_count = threading.active_count()
    for _ in range(worker_count):
        _thumbnail_queue.put((None, None))

# ------------------------------------------------------------------ Thumbnail Generation

def generate_thumbnail_for_video(video_path, save_dir, time_sec=1.5):
    """
    Generate thumbnail for video at `video_path`, and save to hidden folder inside `save_dir`.
    Returns path to thumbnail, or None on failure.
    """

    try:
        if not os.path.exists(video_path):
            return None

        thumb_dir = os.path.join(save_dir, ".thumbnails")
        if not os.path.exists(thumb_dir):
            os.makedirs(thumb_dir)
            if os.name == "nt":
                ctypes.windll.kernel32.SetFileAttributesW(str(thumb_dir), 0x02)

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        thumb_path = os.path.join(thumb_dir, f"{base_name}_thumb.jpg")

        if os.path.exists(thumb_path):
            return thumb_path

        # Generate thumbnail
        with VideoFileClip(video_path) as clip:
            duration = clip.duration
            t = min(time_sec, max(0.1, duration - 0.1))
            frame = clip.get_frame(t)
            image = Image.fromarray(frame)
            image.thumbnail((320, 180))
            image.save(thumb_path, format="JPEG", quality=85)

        return thumb_path

    except Exception as e:
        if server_logger:
            server_logger.warning(f"[Thumbnail Error] {video_path}: {e}")
        return None


def generate_thumbnails_for_folder(video_folder, logger=None, time_sec=1.5, max_workers=4):
    """ Generate thumbnails for all video files in `video_folder` using a thread pool."""

    video_exts = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv")
    thumbs = []

    video_files = []
    for root, _, files in os.walk(video_folder):
        for fname in files:
            if fname.lower().endswith(video_exts):
                video_path = os.path.join(root, fname)
                thumbs_path = os.path.join(root, ".thumbnails", f"{os.path.splitext(fname)[0]}_thumb.jpg")
                if not os.path.exists(thumbs_path):
                    video_files.append(video_path)

    if not video_files:
        return []


    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_video = {executor.submit(generate_thumbnail_for_video, vf, video_folder, time_sec): vf
                           for vf in video_files}

        for future in as_completed(future_to_video):
            video_path = future_to_video[future]
            try:
                thumb_path = future.result()
                if thumb_path:
                    thumbs.append(thumb_path)
            except Exception as e:
                if logger:
                    logger.warning(f"Thumbnail generation failed for {video_path}: {e}")

    return thumbs


# ------------------------------------------------------------------ Serve Thumbnail 

def handle_get_thumbnail(handler):
    """
    Serves thumbnail images from the hidden .thumbnails folder inside SAVE_DIR.
    Secured with login check.
    """
    if handler.AUTH_ENABLED and not handler._is_authenticated():
        handler._redirect("/login")
        return

    thumb_name = unquote(handler.path[len("/thumbnails/") :])
    thumb_path = os.path.join(handler.SAVE_DIR, ".thumbnails", thumb_name)

    if not os.path.isfile(thumb_path):
        handler._send_response_data(b"Thumbnail not found", code=404)
        return

    try:
        with open(thumb_path, "rb") as f:
            data = f.read()
            content_type = mimetypes.guess_type(thumb_path)[0] or "image/jpeg"
            handler._send_response_data(data, content_type=content_type)
    except Exception as e:
        handler.server_logger.error(f"Error serving thumbnail {thumb_path}: {e}")
        handler._send_response_data(b"Internal Server Error", code=500)
