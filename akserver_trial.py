'''

import os
import json
import uuid
import hmac
import hashlib
import datetime
import stat
import subprocess
from akserver_ssl_util import get_or_create_device_id

# -------------------- Config --------------------
TRIAL_DIR = os.path.expanduser("~/.akserver")
TRIAL_FILE = os.path.join(TRIAL_DIR, "trial_info.json")

# Secrets for trial and developer override
TRIAL_SECRET_KEY = b"akserver_trial_secure_v2025"
DEV_SECRET_KEY = b"akserver_dev_secret_v2025"

DEFAULT_TRIAL_DAYS = 60  # 60 days trial

# -------------------- Trial Manager --------------------
class TrialManager:
    def __init__(self):
        self.device_id = get_or_create_device_id()
        self.trial_data = {
            "device_id": self.device_id,
            "first_run_date": None,
            "last_check_date": None,
            "trial_duration_days": DEFAULT_TRIAL_DAYS,
            "verification_hash": None,
        }
        os.makedirs(TRIAL_DIR, exist_ok=True)
        self._load_or_create_trial()

    # --- HMAC hash to prevent tampering ---
    def _calculate_hash(self, first_run_date: str, duration_days: int):
        data = f"{self.device_id}|{first_run_date}|{duration_days}".encode()
        return hmac.new(TRIAL_SECRET_KEY, data, hashlib.sha256).hexdigest()

    # --- Load or initialize trial ---
    def _load_or_create_trial(self):
        if os.path.exists(TRIAL_FILE):
            try:
                with open(TRIAL_FILE, "r") as f:
                    data = json.load(f)
                    if data.get("device_id") == self.device_id:
                        self.trial_data.update(data)
            except Exception:
                pass  # fallback

        if not self.trial_data["first_run_date"]:
            today = datetime.date.today().isoformat()
            self.trial_data["first_run_date"] = today
            self.trial_data["last_check_date"] = today
            self.trial_data["trial_duration_days"] = DEFAULT_TRIAL_DAYS
            self.trial_data["verification_hash"] = self._calculate_hash(today, DEFAULT_TRIAL_DAYS)
            self._save_trial_file()

    # --- Save securely ---
    def _save_trial_file(self):
        try:
            with open(TRIAL_FILE, "w") as f:
                json.dump(self.trial_data, f, indent=2)
            os.chmod(TRIAL_FILE, stat.S_IREAD)
            if os.name == "nt":
                subprocess.call(["attrib", "+h", TRIAL_FILE])
        except Exception as e:
            print(f"[TrialManager] Warning: Failed to secure trial file: {e}")

    # --- Get trial status ---
    def get_trial_status(self):
        try:
            first_run = datetime.date.fromisoformat(self.trial_data["first_run_date"])
            duration = self.trial_data.get("trial_duration_days", DEFAULT_TRIAL_DAYS)
            expected_hash = self._calculate_hash(first_run.isoformat(), duration)
            if self.trial_data.get("verification_hash") != expected_hash:
                return False, 0, first_run + datetime.timedelta(days=duration)

            today = datetime.date.today()
            expiry_date = first_run + datetime.timedelta(days=duration)
            days_left = (expiry_date - today).days
            is_active = days_left >= 0

            # Update last check date
            self.trial_data["last_check_date"] = today.isoformat()
            self._save_trial_file()

            return is_active, max(0, days_left), expiry_date
        except Exception:
            return False, 0, None

    # -------------------- Developer Override --------------------
    # Generates OTP token valid for 1 day to unlock trial or extend days
    def generate_dev_otp(self, extend_days: int = DEFAULT_TRIAL_DAYS):
        expiry = int((datetime.datetime.now() + datetime.timedelta(days=1)).timestamp())
        data = f"{self.device_id}|{extend_days}|{expiry}".encode()
        token = hmac.new(DEV_SECRET_KEY, data, hashlib.sha256).hexdigest()
        return f"{token}:{expiry}"

    # Apply OTP to set/extend trial
    def apply_dev_otp(self, otp_str: str):
        try:
            token, expiry_str = otp_str.split(":")
            expiry = int(expiry_str)
            if datetime.datetime.now().timestamp() > expiry:
                return False

            # Brute-force test extend_days from 1 to 365 to find matching token
            for test_days in range(1, 366):
                expected_data = f"{self.device_id}|{test_days}|{expiry}".encode()
                expected_token = hmac.new(DEV_SECRET_KEY, expected_data, hashlib.sha256).hexdigest()
                if hmac.compare_digest(expected_token, token):
                    today = datetime.date.today().isoformat()
                    self.trial_data["first_run_date"] = today
                    self.trial_data["trial_duration_days"] = test_days
                    self.trial_data["verification_hash"] = self._calculate_hash(today, test_days)
                    self._save_trial_file()
                    return True
            return False
        except Exception:
            return False
        
            # --- Save securely ---
    def _save_trial_file(self):
        try:
            with open(TRIAL_FILE, "w") as f:
                json.dump(self.trial_data, f, indent=2)
            # Attempt to make read-only
            try:
                os.chmod(TRIAL_FILE, stat.S_IREAD)
            except Exception as e:
                print(f"[TrialManager] Warning: Could not set read-only: {e}")

            # Attempt to hide on Windows
            if os.name == "nt":
                try:
                    subprocess.call(["attrib", "+h", TRIAL_FILE])
                except Exception as e:
                    print(f"[TrialManager] Warning: Could not hide file: {e}")

        except Exception as e:
            print(f"[TrialManager] Warning: Failed to save trial file: {e}")
'''
