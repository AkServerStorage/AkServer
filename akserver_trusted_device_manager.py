# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Handles storing and managing trusted device tokens
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025 AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Python Standard library

import json, logging, os, threading, time
from typing import Any, Optional


class TrustedDeviceManager:
    """Manages loading, saving, and querying trusted device tokens."""

    def __init__(self, file_path: str, logger: logging.Logger):
        self.file_path = file_path
        self.logger = logger
        self._trusted_devices: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._load_trusted_devices()

    def _load_trusted_devices(self) -> None:
        """Loads trusted devices from the specified file into memory."""
        with self._lock:
            self._trusted_devices.clear()

            if not os.path.exists(self.file_path):
                self.logger.info(
                    f"No trusted devices file at '{self.file_path}'. Starting fresh."
                )
                return

            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        self.logger.info("Trusted devices file is empty. Starting with none.")
                        return

                    data = json.loads(content)

                if isinstance(data, list):
                    self._trusted_devices = self._upgrade_device_format(data)
                else:
                    self.logger.error(
                        f"Unrecognized format in {self.file_path}. Resetting trusted devices."
                    )
                    self._trusted_devices = []

            except json.JSONDecodeError:
                self.logger.error(
                    f"Invalid JSON in {self.file_path}. Resetting trusted devices."
                )
            except Exception as e:
                self.logger.error(
                    f"Unexpected error loading trusted devices from {self.file_path}: {e}"
                )

    def _save_trusted_devices(self) -> None:
        """Persists trusted devices list to file. Must be called inside lock."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._trusted_devices, f, indent=2)
            self.logger.info(
                f"Saved {len(self._trusted_devices)} trusted devices to {self.file_path}."
            )
        except Exception as e:
            self.logger.error(f"Error saving trusted devices to {self.file_path}: {e}")

    def _upgrade_device_format(self, data: list[Any]) -> list[dict[str, Any]]:
        """Handles backward compatibility with older file formats."""
        if not data:
            return []

        if all(isinstance(d, dict) and {"token", "name", "origin_ip", "timestamp"} <= d.keys() for d in data):
            return data

        if all(isinstance(d, dict) and {"token", "name"} <= d.keys() for d in data):
            self.logger.warning("Detected old trusted_devices format. Upgrading.")
            upgraded = [
                {
                    "token": d["token"],
                    "name": d["name"],
                    "origin_ip": "unknown",
                    "timestamp": 0.0,
                }
                for d in data
            ]
            self._trusted_devices = upgraded
            self._save_trusted_devices()
            return upgraded

        if all(isinstance(d, str) for d in data):
            self.logger.warning("Detected very old trusted_devices format. Upgrading.")
            upgraded = [
                {
                    "token": token,
                    "name": f"Device ...{token[-6:]}",
                    "origin_ip": "unknown",
                    "timestamp": 0.0,
                }
                for token in data
            ]
            self._trusted_devices = upgraded
            self._save_trusted_devices()
            return upgraded

        self.logger.error("Unrecognized trusted_devices format. Resetting list.")
        return []


    def add_trusted_device(self, token: str, name: str, origin_ip: str) -> None:
        """Adds a new trusted device to the list and saves it."""
        with self._lock:
            if any(d["token"] == token for d in self._trusted_devices):
                self.logger.warning(
                    f"Duplicate trusted token ignored: ...{token[-6:]}, name={name}"
                )
                return

            self._trusted_devices.append(
                {
                    "token": token,
                    "name": name,
                    "origin_ip": origin_ip,
                    "timestamp": time.time(),
                }
            )
            self._save_trusted_devices()

        self.logger.info(
            f"Trusted device added: {name} (token=...{token[-6:]}, ip={origin_ip})"
        )

    def is_device_trusted(self, token: str) -> bool:
        """Checks if a token exists in trusted devices."""
        with self._lock:
            return any(d["token"] == token for d in self._trusted_devices)

    def get_trusted_devices_list(self) -> list[dict[str, Any]]:
        """Returns a shallow copy of the trusted devices list."""
        with self._lock:
            return list(self._trusted_devices)

    def get_device_details(self, token: str) -> Optional[dict[str, Any]]:
        """Fetches details for a given token, or None if not found."""
        with self._lock:
            return next((d for d in self._trusted_devices if d["token"] == token), None)

    def forget_device_by_partial_token_suffix(self, token_suffix: str) -> Optional[dict[str, Any]]:
        """
        Removes a device by token suffix (after '...').
        Returns the removed device, or None if not found.
        """
        with self._lock:
            device = next((d for d in self._trusted_devices if d["token"].endswith(token_suffix)), None)

            if not device:
                self.logger.warning(f"No device found with token ending {token_suffix}.")
                return None

            self._trusted_devices.remove(device)
            self._save_trusted_devices()

        self.logger.info(
            f"Trusted device removed: {device.get('name', 'N/A')} (token=...{token_suffix})"
        )
        return device


def get_current_trusted_device_count(file_path: str, logger: logging.Logger) -> int:
    """Utility function to quickly count trusted devices in a file."""
    try:
        manager = TrustedDeviceManager(file_path, logger)
        return len(manager.get_trusted_devices_list())
    except Exception as e:
        logger.warning(f"Failed to count trusted devices from {file_path}: {e}")
        return -1
