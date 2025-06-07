# File: c:\Users\Aksha\Desktop\AkServer_trusted_device_manager.py
import json
import os
import time
import logging # For type hinting logger parameter

# This list will store the trusted device tokens in memory.
# It will be populated by load_trusted_devices_from_file()
# and modified by add_trusted_device() and forget_device_by_partial_token().
_TRUSTED_DEVICE_TOKENS = [] # Underscore to indicate module-internal state

def load_trusted_devices_from_file(file_path: str, logger: logging.Logger):
    """Loads trusted devices from the specified file into the module's _TRUSTED_DEVICE_TOKENS list."""
    global _TRUSTED_DEVICE_TOKENS
    _TRUSTED_DEVICE_TOKENS = [] # Reset before loading
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                if not content.strip():
                    logger.info(f"{file_path} is empty. Initializing with an empty list of trusted devices.")
                    return
                data = json.loads(content)

            if isinstance(data, list):
                if not data: # Empty list in JSON file
                    _TRUSTED_DEVICE_TOKENS = []
                elif all(isinstance(item, dict) and "token" in item and "name" in item and "origin_ip" in item and "timestamp" in item for item in data):
                    _TRUSTED_DEVICE_TOKENS = data
                elif all(isinstance(item, dict) and "token" in item and "name" in item and "origin_ip" not in item for item in data):
                    logger.warning(f"Old trusted_devices.json format (missing origin_ip/timestamp) detected at {file_path}. Upgrading.")
                    _TRUSTED_DEVICE_TOKENS = [
                        {"token": item["token"], "name": item["name"], "origin_ip": "unknown", "timestamp": 0.0}
                        for item in data
                    ]
                    save_trusted_devices_to_file(file_path, logger) # Save immediately after upgrading format
                elif all(isinstance(item, str) for item in data):
                    logger.warning(f"Very old trusted_devices.json format (list of tokens) detected at {file_path}. Converting to new format.")
                    _TRUSTED_DEVICE_TOKENS = [{"token": token, "name": f"Device ...{token[-6:]}", "origin_ip": "unknown", "timestamp": 0.0} for token in data]
                    save_trusted_devices_to_file(file_path, logger) # Save immediately after upgrading format
                else:
                    logger.error(f"Content of {file_path} is a list but not in a recognized format. Initializing as empty list.")
            else:
                logger.error(f"Corrupted or unknown format (not a list) in {file_path}. Initializing as empty list.")
            
            logger.info(f"Loaded {len(_TRUSTED_DEVICE_TOKENS)} trusted devices from {file_path}.")

        except json.JSONDecodeError:
            logger.error(f"Could not decode JSON from {file_path}. It might be corrupted. Initializing as empty list.")
        except Exception as e:
            logger.error(f"Error loading trusted devices from {file_path}: {e}. Initializing as empty list.")
    else:
        logger.info(f"Trusted devices file '{file_path}' not found. Initializing with an empty list.")

def save_trusted_devices_to_file(file_path: str, logger: logging.Logger):
    """Saves the current _TRUSTED_DEVICE_TOKENS list to the specified file."""
    global _TRUSTED_DEVICE_TOKENS
    try:
        with open(file_path, 'w') as f:
            json.dump(_TRUSTED_DEVICE_TOKENS, f, indent=2)
        logger.info(f"Saved {len(_TRUSTED_DEVICE_TOKENS)} trusted devices to {file_path}.")
    except Exception as e:
        logger.error(f"Error saving trusted devices to {file_path}: {e}")

def add_trusted_device(token: str, name: str, origin_ip: str, file_path_for_saving: str, logger: logging.Logger):
    """Adds a new trusted device to the list and saves it."""
    global _TRUSTED_DEVICE_TOKENS
    if any(d["token"] == token for d in _TRUSTED_DEVICE_TOKENS):
        logger.warning(f"Attempted to add an already trusted token: ...{token[-6:]}. Name: {name}")
        return
    _TRUSTED_DEVICE_TOKENS.append({"token": token, "name": name, "origin_ip": origin_ip, "timestamp": time.time()})
    save_trusted_devices_to_file(file_path_for_saving, logger)
    logger.info(f"Added trusted device: '{name}' (token: ...{token[-6:]}) from IP: {origin_ip}")

def is_device_trusted(token: str) -> bool:
    """Checks if a given token is in the list of trusted devices."""
    global _TRUSTED_DEVICE_TOKENS
    return any(device_info["token"] == token for device_info in _TRUSTED_DEVICE_TOKENS)

def get_trusted_devices_list() -> list:
    """Returns a copy of the current trusted devices list."""
    global _TRUSTED_DEVICE_TOKENS
    return list(_TRUSTED_DEVICE_TOKENS) # Return a copy

def forget_device_by_partial_token_suffix(token_suffix: str, file_path_for_saving: str, logger: logging.Logger) -> dict | None:
    """
    Removes a device from _TRUSTED_DEVICE_TOKENS based on the suffix of its token.
    Returns the removed device object or None if not found.
    Assumes token_suffix is the part *after* '...'.
    """
    global _TRUSTED_DEVICE_TOKENS
    device_to_remove = None
    
    for device_obj in _TRUSTED_DEVICE_TOKENS: 
        if device_obj["token"].endswith(token_suffix):
            device_to_remove = device_obj
            break
    
    if device_to_remove:
        _TRUSTED_DEVICE_TOKENS.remove(device_to_remove)
        save_trusted_devices_to_file(file_path_for_saving, logger)
        logger.info(f"Forgot device: {device_to_remove.get('name', 'N/A')} (token ending with {token_suffix})")
        return device_to_remove
    else:
        logger.warning(f"Device token ending with {token_suffix} not found for forgetting.")
        return None

