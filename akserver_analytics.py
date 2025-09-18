# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Handles offline analytics logging and reporting for akserver.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025-present AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Python Standard library
import datetime, json, logging, os, platform, urllib.parse, uuid

# ------------------------------------------------------------------Third-Party
import requests
import pyautogui

# ------------------------------------------------------------------ Local modules

from akserver_trusted_device_manager import get_current_trusted_device_count

# ------------------------------------------------------------------ Subdirectory Paths

analytics_logger = logging.getLogger(__name__)
DEVICE_INFO_FILE = os.path.join(
    os.getenv("APPDATA", os.path.expanduser("~")),
    "akserver_device_info.json"
)

# ------------------------------------------------------------------ functions

def _get_persistent_device_info():
    """
    Retrieves persistent device ID and first_seen_date from a local file.
    If the file doesn't exist or is invalid, it generates new values, saves them, and returns them.
    """
    device_info = {"device_id": None, "first_seen_date": None}

    if os.path.exists(DEVICE_INFO_FILE):
        try:
            with open(DEVICE_INFO_FILE, "r") as f:
                loaded_info = json.load(f)
                if isinstance(loaded_info, dict):
                    device_info["device_id"] = loaded_info.get("device_id")
                    device_info["first_seen_date"] = loaded_info.get("first_seen_date")

                    if device_info["device_id"] and device_info["first_seen_date"]:
                        analytics_logger.info(
                            (
                                f"Using existing device ID: {device_info['device_id']} "
                                f"and First Seen: {device_info['first_seen_date']}"
                            )
                        )
                        return device_info
        except (IOError, json.JSONDecodeError) as e:
            analytics_logger.warning(
                f"Could not read/parse device info from {DEVICE_INFO_FILE}: {e}. Generating new info."
            )

    device_info["device_id"] = f"APP_DEVICE_{str(uuid.uuid4())}"
    device_info["first_seen_date"] = datetime.datetime.now().strftime("%Y-%m-%d")

    analytics_logger.info(
        (
            f"Generating new persistent device ID: {device_info['device_id']} "
            f"and First Seen Date: {device_info['first_seen_date']}"
        )
    )
    try:
        os.makedirs(os.path.dirname(DEVICE_INFO_FILE), exist_ok=True)
        with open(DEVICE_INFO_FILE, "w") as f:
            json.dump(device_info, f, indent=2)
        return device_info
    except IOError as e:
        analytics_logger.error(
            f"Failed to write device info to file {DEVICE_INFO_FILE}: {e}. Using temporary IDs."
        )

        return {
            "device_id": f"TEMP_ID_{str(uuid.uuid4())}",
            "first_seen_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        }


def send_usage_to_google_form(data):
    """
    Sends analytics data to a Google Form.
    The 'data' dictionary should contain keys matching your form entries.
    """
    try:
        form_base_url = "https://docs.google.com/forms/d/e/1FAIpQLScL2-9jzd51Zqo3XLz0bqpKPbmOMkcDC7fclGXTr_aZvCThog/formResponse"  # noqa

        form_data = {
            "entry.356598322": data.get("device_id"),
            "entry.1214268152": data.get("first_seen"),
            "entry.895800400": data.get("last_seen"),
            "entry.20115352": data.get("active_days"),
            "entry.323105311": data.get("install_age"),
            "entry.1469310377": data.get("trial_status"),
            "entry.630203470": data.get("platform"),
            "entry.1382959889": data.get("arch"),
            "entry.50322633": data.get("os_version"),
            "entry.994756180": data.get("language"),
            "entry.895293115": data.get("screen"),
            "entry.1369874886": data.get("version"),
            "entry.845866391": data.get("timezone"),
            "entry.1210005143": data.get("utc_offset"),
            "entry.465165405": data.get("device_count"),
            
        }

        encoded_data = urllib.parse.urlencode(form_data)
        full_url = f"{form_base_url}?{encoded_data}"

        analytics_logger.info(
            f"Sending GET request to Google Form URL:\n{full_url}"
        )

        response = requests.get(full_url, timeout=10)

        if response.status_code in [200, 302]:
            analytics_logger.info("Usage data sent to Google Form successfully.")
            return True
        else:
            analytics_logger.error(
                f"Failed to send usage data. Status code: {response.status_code}, Response: {response.text}"
            )
            return False

    except requests.exceptions.Timeout:
        analytics_logger.error("Error sending usage data: Request timed out.")
        return False
    except requests.exceptions.ConnectionError as e:
        analytics_logger.error(f"Error sending usage data: Connection error - {e}")
        return False
    except Exception as e:
        analytics_logger.exception(
            f"An unexpected error occurred while sending usage data: {e}"
        )
        return False


def get_and_send_analytics_data():
    """
    Generates analytics data, including persistent device info, and sends it.
    """
    current_time = datetime.datetime.now()

    device_info = _get_persistent_device_info()
    persistent_device_id = device_info["device_id"]
    first_seen_str = device_info["first_seen_date"]

    try:
        first_seen_datetime = datetime.datetime.strptime(first_seen_str, "%Y-%m-%d")
        install_age_days = (current_time - first_seen_datetime).days
        install_age_str = f"{install_age_days} days"
    except ValueError:
        install_age_str = "Unknown" 

    delta = current_time - datetime.datetime.utcnow()
    total_seconds = delta.days * 86400 + delta.seconds
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    utc_offset_str = f"{'+' if hours >= 0 else ''}{hours:02d}:{minutes:02d}"

    try:
        screen_resolution = f"{pyautogui.size().width}x{pyautogui.size().height}"
    except ImportError:
        screen_resolution = "Unknown"
        analytics_logger.warning(
            "pyautogui not found. Screen resolution will be 'Unknown'. "
            "Install with 'pip install pyautogui' for dynamic resolution."
        )
    except Exception as e:
        screen_resolution = "Error"
        analytics_logger.error(f"Error getting screen resolution: {e}")


    app_version = "1.0.0"

    TRUSTED_DEVICES_PATH = os.path.join(
        os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
        "akserver",
        "akserver_Data_Server",
        "Server",
        "trusted_devices.json",
    )
    
    device_count = get_current_trusted_device_count(
        TRUSTED_DEVICES_PATH, analytics_logger
    )

    analytics_logger.info(f"Trusted Device Count: {device_count}")

    data_payload = {
        "device_id": persistent_device_id,
        "first_seen": first_seen_str,
        "last_seen": current_time.strftime("%Y-%m-%d"),
        "active_days": 1,
        "install_age": install_age_str,
        "trial_status": "Active", 
        "platform": platform.system(),
        "arch": platform.machine(),
        "os_version": platform.version(),
        "language": "en-US",
        "screen": screen_resolution,
        "version": app_version,
        "timezone": datetime.datetime.now(datetime.timezone.utc)
        .astimezone()
        .tzname(),
        "utc_offset": utc_offset_str,
        "device_count": device_count,
    }

    analytics_logger.info(
        f"Attempting to send data: {json.dumps(data_payload, indent=2)}"
    )
    send_usage_to_google_form(data_payload)
