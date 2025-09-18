# =============================================================================
# AkServer – Proprietary Software Module
# =============================================================================

"""
Description:    Helper functions related to trial status checking.
Author:         Akshay Shinde
Version:        1.0.0
License:        AkServer Custom Freemium License (See LICENSE.txt)

Copyright © 2025-present AkServer. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

# ------------------------------------------------------------------ Local modules

from akserver_trial import check_trial

# ------------------------------------------------------------------ Trial Helper Functions

def require_active_trial(handler) -> bool:
    trial_status = check_trial()
    if not trial_status.get("active", False):
        handler._send_json({"error": "Trial expired. Upgrade required."}, code=403)
        return False
    return True

# ----------------- Decorator -----------------

def trial_required(func):
    def wrapper(handler, *args, **kwargs):
        if not require_active_trial(handler):
            return
        return func(handler, *args, **kwargs)
    return wrapper

