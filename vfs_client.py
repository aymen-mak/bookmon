"""
VFS Global LIFT API client — built from decompiled APK analysis.

Endpoints are from the VFS Italy Android app (lift-api.vfsglobal.com).
Login uses form-encoded POST. Appointment checks use JSON POST.
reCAPTCHA is enabled for Algeria — handled via optional 2captcha integration
or browser-assisted login.
"""

import logging
import time
import requests

logger = logging.getLogger(__name__)

# ── API Base URLs (from remote_config_defaults.xml → app_config_prod) ──
LIFT_API_BASE = "https://lift-api.vfsglobal.com"
APP_API_BASE = "https://www.vfsglobalmobile.com/vfs-vfwhl.italy.com"

# ── Endpoints (from Retrofit interface ab.b) ──────────────────────────
ENDPOINTS = {
    # Auth (form-encoded POST)
    "login":                f"{LIFT_API_BASE}/user/login",
    "login_otp":            f"{LIFT_API_BASE}/user/login",  # same URL, adds otp field
    "register":             f"{LIFT_API_BASE}/user/registration",
    "forgot_password":      f"{LIFT_API_BASE}/user/forgetpassword",
    "generate_otp":         f"{LIFT_API_BASE}/user/generateuserotp",
    "logout":               f"{LIFT_API_BASE}/user/logout",

    # Appointment booking flow (JSON POST)
    "check_slot":           f"{LIFT_API_BASE}/appointment/CheckIsSlotAvailable",
    "calendar":             f"{LIFT_API_BASE}/appointment/calendar",
    "timeslot":             f"{LIFT_API_BASE}/appointment/timeslot",
    "schedule":             f"{LIFT_API_BASE}/appointment/schedule",
    "confirm":              f"{LIFT_API_BASE}/payments/confirmappointment",
    "applicants":           f"{LIFT_API_BASE}/appointment/applicants",
    "applicant_otp":        f"{LIFT_API_BASE}/appointment/applicantotp",
    "search_appointment":   f"{LIFT_API_BASE}/appointment/application",
    "delete_applicant":     f"{LIFT_API_BASE}/appointment/deleteapplicant",
    "reschedule":           f"{LIFT_API_BASE}/appointment/reschedule",
    "cancel":               f"{LIFT_API_BASE}/appointment/cancel",
    "fees":                 f"{LIFT_API_BASE}/appointment/fees",

    # Master data (GET)
    "centers":              f"{LIFT_API_BASE}/master/center/{{mission}}/{{country}}",
    "visa_categories":      f"{LIFT_API_BASE}/master/visacategory/{{mission}}/{{country}}/{{center}}",
    "sub_visa_categories":  f"{LIFT_API_BASE}/master/subvisacategory/{{mission}}/{{country}}/{{center}}/{{visacategorycode}}",
    "nationalities":        f"{LIFT_API_BASE}/master/nationality/{{languageCode}}",
    "payment_modes":        f"{LIFT_API_BASE}/master/paymentmode/{{mission}}/{{country}}/{{center}}",
    "configuration":        f"{LIFT_API_BASE}/configuration/fields/{{mission}}/{{country}}",
}

# Headers mimicking the Android app
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://visa.vfsglobal.com",
    "Referer": "https://visa.vfsglobal.com/",
}


class VFSClient:
    """
    VFS Global LIFT API client.

    Handles authentication and appointment availability checking using
    the exact endpoints and payload formats from the VFS Italy APK.
    """

    def __init__(self, email: str, password: str, country_code: str,
                 mission_code: str, vac_code: str,
                 captcha_api_key: str = ""):
        self.email = email
        self.password = password
        self.country_code = country_code.lower()
        self.mission_code = mission_code.lower()
        self.vac_code = vac_code
        self.captcha_api_key = captcha_api_key

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.token: str | None = None
        self.token_expires: float = 0

    # ── Authentication ───────────────────────────────────────────────

    def login(self) -> bool:
        """
        Authenticate with VFS LIFT API.

        The APK uses @FormUrlEncoded POST to user/login with fields:
        username, password, missioncode, countrycode
        """
        form_data = {
            "username": self.email,
            "password": self.password,
            "missioncode": self.mission_code,
            "countrycode": self.country_code,
        }

        logger.info("Logging in to VFS as %s (form-encoded)...", self.email)

        try:
            resp = self.session.post(
                ENDPOINTS["login"],
                data=form_data,  # form-encoded, NOT json=
                headers={
                    **self.session.headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.error("Login request failed: %s", exc)
            return False

        logger.debug("Login response: HTTP %d — %s", resp.status_code, resp.text[:500])

        if resp.status_code != 200:
            logger.error("Login failed: HTTP %d — %s", resp.status_code, resp.text[:500])

            # Check for CAPTCHA requirement
            try:
                error_data = resp.json()
                error_msg = str(error_data.get("error", ""))
                if "captcha" in error_msg.lower() or "recaptcha" in error_msg.lower():
                    logger.error(
                        "reCAPTCHA required! Algeria has CAPTCHA enabled on login. "
                        "See the reCAPTCHA section in the README."
                    )
            except Exception:
                pass

            return False

        try:
            data = resp.json()
        except Exception:
            logger.error("Login response is not JSON: %s", resp.text[:300])
            return False

        # Extract token — try multiple known field locations
        self.token = (
            data.get("accessToken")
            or data.get("token")
            or data.get("data", {}).get("accessToken")
            or data.get("data", {}).get("token")
            or data.get("Token")
            or data.get("access_token")
        )

        if not self.token:
            logger.error("Login succeeded but no token found. Response: %s", data)
            return False

        self.token_expires = time.time() + 25 * 60  # refresh every 25 min
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        logger.info("Login successful — token acquired.")
        return True

    def ensure_authenticated(self) -> bool:
        """Re-login if token has expired or is missing."""
        if self.token and time.time() < self.token_expires:
            return True
        return self.login()

    # ── Appointment Availability ─────────────────────────────────────

    def check_slot_available(self, visa_category: str) -> dict:
        """
        POST appointment/CheckIsSlotAvailable

        Request (from CheckIsSlotAvailableRequestParams):
        {
            "countryCode": "dza",
            "missionCode": "ita",
            "vacCode": "ALG",
            "visaCategoryCode": "TOUR",
            "roleName": "Individual",
            "loginUser": "user@email.com"
        }

        Response (from CheckIsSlotAvailableResModel):
        {
            "earliestDate": "2024-03-15",
            "earliestSlotLists": [{"applicant": "...", "date": "..."}],
            "error": null
        }
        """
        if not self.ensure_authenticated():
            return {"available": False, "slots": [], "raw": {}, "error": "Authentication failed"}

        payload = {
            "countryCode": self.country_code,
            "missionCode": self.mission_code,
            "vacCode": self.vac_code,
            "visaCategoryCode": visa_category,
            "roleName": "Individual",
            "loginUser": self.email,
        }

        return self._post_appointment(ENDPOINTS["check_slot"], payload)

    def get_calendar(self, visa_category: str) -> dict:
        """POST appointment/calendar — get available calendar dates."""
        if not self.ensure_authenticated():
            return {"available": False, "slots": [], "raw": {}, "error": "Authentication failed"}

        payload = {
            "countryCode": self.country_code,
            "missionCode": self.mission_code,
            "vacCode": self.vac_code,
            "visaCategoryCode": visa_category,
            "loginUser": self.email,
        }

        return self._post_appointment(ENDPOINTS["calendar"], payload)

    def get_timeslots(self, visa_category: str, date: str) -> dict:
        """POST appointment/timeslot — get time slots for a specific date."""
        if not self.ensure_authenticated():
            return {"available": False, "slots": [], "raw": {}, "error": "Authentication failed"}

        payload = {
            "countryCode": self.country_code,
            "missionCode": self.mission_code,
            "vacCode": self.vac_code,
            "visaCategoryCode": visa_category,
            "loginUser": self.email,
            "appointmentDate": date,
        }

        return self._post_appointment(ENDPOINTS["timeslot"], payload)

    # ── Master Data ──────────────────────────────────────────────────

    def get_centers(self) -> list:
        """GET master/center/{mission}/{country} — list VAC centers."""
        url = ENDPOINTS["centers"].format(
            mission=self.mission_code, country=self.country_code
        )
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.error("Failed to fetch centers: %s", exc)
        return []

    def get_visa_categories(self) -> list:
        """GET master/visacategory/{mission}/{country}/{center}"""
        url = ENDPOINTS["visa_categories"].format(
            mission=self.mission_code, country=self.country_code,
            center=self.vac_code
        )
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.error("Failed to fetch visa categories: %s", exc)
        return []

    # ── Internal Helpers ─────────────────────────────────────────────

    def _post_appointment(self, url: str, payload: dict) -> dict:
        """Make a JSON POST to an appointment endpoint with auth retry."""
        logger.debug("POST %s — %s", url, payload)

        try:
            resp = self.session.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            logger.error("Request failed: %s", exc)
            return {"available": False, "slots": [], "raw": {}, "error": str(exc)}

        # Handle token expiry
        if resp.status_code == 401:
            logger.warning("Token expired, re-authenticating...")
            self.token = None
            if not self.login():
                return {"available": False, "slots": [], "raw": {}, "error": "Re-auth failed"}
            try:
                resp = self.session.post(url, json=payload, timeout=30)
            except requests.RequestException as exc:
                return {"available": False, "slots": [], "raw": {}, "error": str(exc)}

        if resp.status_code != 200:
            logger.error("HTTP %d — %s", resp.status_code, resp.text[:500])
            return {
                "available": False, "slots": [], "raw": {},
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        try:
            data = resp.json()
        except Exception:
            return {"available": False, "slots": [], "raw": {}, "error": f"Non-JSON response: {resp.text[:200]}"}

        return self._parse_availability(data)

    def _parse_availability(self, data: dict) -> dict:
        """
        Parse VFS response for slot availability.

        Known response format (CheckIsSlotAvailableResModel):
        {
            "earliestDate": "2024-03-15",
            "earliestSlotLists": [{"applicant": "...", "date": "..."}],
            "error": {"errorCode": "...", "errorMsg": "..."}
        }

        Calendar response: list of available dates
        Timeslot response: list of TimeSlot objects with remainingSeats
        """
        result = {"available": False, "slots": [], "raw": data, "error": None}

        if not isinstance(data, dict):
            # Could be a list (calendar dates, timeslots)
            if isinstance(data, list) and len(data) > 0:
                result["available"] = True
                result["slots"] = data
            return result

        # Check for API error
        error = data.get("error")
        if error and isinstance(error, dict):
            error_msg = error.get("errorMsg") or error.get("description") or ""
            if error_msg:
                result["error"] = error_msg
                logger.warning("API error: %s", error_msg)

        # CheckIsSlotAvailable response
        earliest_date = data.get("earliestDate")
        earliest_slots = data.get("earliestSlotLists")

        if earliest_date:
            result["available"] = True
            result["slots"] = [{"date": earliest_date}]
            if earliest_slots and isinstance(earliest_slots, list):
                result["slots"] = earliest_slots
            return result

        # Timeslot response — check remainingSeats
        if isinstance(data.get("data"), list):
            available_slots = [
                s for s in data["data"]
                if isinstance(s, dict) and s.get("remainingSeats", 0) > 0
            ]
            if available_slots:
                result["available"] = True
                result["slots"] = available_slots
            return result

        # Generic: any non-empty slot list
        for key in ("slots", "SlotDetails", "timeSlot", "data"):
            val = data.get(key)
            if isinstance(val, list) and len(val) > 0:
                result["available"] = True
                result["slots"] = val
                return result

        return result
