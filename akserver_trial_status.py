# =============================================================================
# akserver - Trial Status Helpers (Proprietary Edition)
# =============================================================================
"""
File:           akserver_trial_status.py
Description:    Helper functions related to trial status checking for route handlers.
Author:         AkshAy S (akserver Project)
Version:        1.0.0
License:        akserver Custom Freemium License (See LICENSE.txt)

This file contains lightweight helper functions for checking trial status
before executing route handler logic.
"""

# ------------------------------------------------------------------ Local modules
from akserver_trial import check_trial

# ------------------------------------------------------------------ Trial Helper Functions

def require_active_trial(handler) -> bool:
    """
    Checks if trial is active. If not, sends 403 JSON response via the handler.
    
    Returns:
        bool: True if trial is active, False if expired (and response sent).
    """
    trial_status = check_trial()
    if not trial_status.get("active", False):
        handler._send_json({"error": "Trial expired. Upgrade required."}, code=403)
        return False
    return True

# ----------------- Decorator -----------------

def trial_required(func):
    """Decorator to enforce trial check for route handlers."""

    def wrapper(handler, *args, **kwargs):
        if not require_active_trial(handler):
            return
        return func(handler, *args, **kwargs)
    return wrapper

