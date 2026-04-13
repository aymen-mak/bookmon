"""
VFS Global API client for checking appointment availability.

VFS Global uses different portal versions depending on the country pair.
This client supports the common API patterns used by visa.vfsglobal.com.

If the endpoints don't work for your specific country pair, you can find
the correct ones by:
  1. Opening the VFS booking page in Chrome
  2. Opening DevTools (F12) → Network tab
  3. Going through the booking flow and watching the API calls
  4. Updating the URLs in this file to match

For the Android app, use a proxy like mitmproxy or HTTP Toolkit to
intercept the API calls.
"""

import logging
import time
import requests

logger = logging.getLogger(__name__)

# VFS Global base URL pattern: visa.vfsglobal.com/{country}/en/{mission}
VFS_BASE = "https://visa.vfsglobal.com"

# Common API gateway base used by the VFS booking system
VFS_API_BASE = "https://lift-api.vfsglobal.com/appointment"

# Endpoints observed across multiple VFS country portals
ENDPOINTS = {
    "login": f"{VFS_API_BASE}/login",
    "slots": f"{VFS_API_BASE}/CheckIsSlotAvailable",
}

# Headers that mimic the VFS web app
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": VFS_BASE,
    "Referer": f"{VFS_BASE}/",
}


class VFSClient:
    """Handles authentication and appointment availability checks."""

    def __init__(self, email: str, password: str, country_code: str,
                 mission_code: str, center_code: str, visa_category: str,
                 visa_subcategory: str = ""):
        self.email = email
        self.password = password
        self.country_code = country_code.lower()
        self.mission_code = mission_code.lower()
        self.center_code = center_code
        self.visa_category = visa_category
        self.visa_subcategory = visa_subcategory

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.token: str | None = None
        self.token_expires: float = 0

    def login(self) -> bool:
        """
        Authenticate with VFS and obtain an access token.
        Returns True on success, False on failure.
        """
        payload = {
            "username": self.email,
            "password": self.password,
            "countryCode": self.country_code,
            "missionCode": self.mission_code,
        }

        logger.info("Logging in to VFS as %s ...", self.email)

        try:
            resp = self.session.post(
                ENDPOINTS["login"],
                json=payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.error("Login request failed: %s", exc)
            return False

        if resp.status_code != 200:
            logger.error(
                "Login failed: HTTP %d — %s",
                resp.status_code,
                resp.text[:500],
            )
            return False

        data = resp.json()

        # VFS returns the token in different fields depending on the portal version
        self.token = (
            data.get("accessToken")
            or data.get("token")
            or data.get("data", {}).get("accessToken")
            or data.get("data", {}).get("token")
        )

        if not self.token:
            logger.error("Login response contained no token: %s", data)
            return False

        # Refresh token every 25 minutes (tokens typically last 30 min)
        self.token_expires = time.time() + 25 * 60
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        logger.info("Login successful.")
        return True

    def ensure_authenticated(self) -> bool:
        """Re-login if token has expired or is missing."""
        if self.token and time.time() < self.token_expires:
            return True
        return self.login()

    def check_availability(self) -> dict:
        """
        Check appointment slot availability.

        Returns a dict with:
          - available: bool — whether any slots were found
          - slots: list — available slot details (dates, times, etc.)
          - raw: dict — the full API response for debugging
          - error: str | None — error message if the check failed
        """
        if not self.ensure_authenticated():
            return {"available": False, "slots": [], "raw": {}, "error": "Authentication failed"}

        payload = {
            "countryCode": self.country_code,
            "missionCode": self.mission_code,
            "centerCode": self.center_code,
            "loginUser": self.email,
            "visaCategoryCode": self.visa_category,
        }
        if self.visa_subcategory:
            payload["visaSubCategoryCode"] = self.visa_subcategory

        logger.debug("Checking availability: %s", payload)

        try:
            resp = self.session.post(
                ENDPOINTS["slots"],
                json=payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.error("Availability check failed: %s", exc)
            return {"available": False, "slots": [], "raw": {}, "error": str(exc)}

        if resp.status_code == 401:
            logger.warning("Token expired, re-authenticating...")
            self.token = None
            if not self.login():
                return {"available": False, "slots": [], "raw": {}, "error": "Re-auth failed"}
            # Retry once after re-auth
            try:
                resp = self.session.post(
                    ENDPOINTS["slots"],
                    json=payload,
                    timeout=30,
                )
            except requests.RequestException as exc:
                return {"available": False, "slots": [], "raw": {}, "error": str(exc)}

        if resp.status_code != 200:
            logger.error(
                "Slot check failed: HTTP %d — %s",
                resp.status_code,
                resp.text[:500],
            )
            return {
                "available": False,
                "slots": [],
                "raw": {},
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        data = resp.json()
        return self._parse_availability(data)

    def _parse_availability(self, data: dict) -> dict:
        """
        Parse the VFS API response to extract available slots.

        VFS responses vary, but common patterns:
          - {"IsSlotAvailable": true/false, "SlotDetails": [...]}
          - {"data": {"slots": [...]}}
          - {"earliest": "2024-03-15", "available": true}

        This method tries all known patterns.
        """
        result = {"available": False, "slots": [], "raw": data, "error": None}

        # Pattern 1: IsSlotAvailable flag
        if "IsSlotAvailable" in data:
            result["available"] = bool(data["IsSlotAvailable"])
            result["slots"] = data.get("SlotDetails", [])
            return result

        # Pattern 2: nested data.slots
        inner = data.get("data", data)
        if isinstance(inner, dict):
            slots = inner.get("slots", inner.get("SlotDetails", []))
            if isinstance(slots, list) and len(slots) > 0:
                result["available"] = True
                result["slots"] = slots
                return result

            if inner.get("available") or inner.get("isAvailable"):
                result["available"] = True
                result["slots"] = [inner]
                return result

        # Pattern 3: the response itself is a list of dates/slots
        if isinstance(data, list) and len(data) > 0:
            result["available"] = True
            result["slots"] = data
            return result

        # Pattern 4: check for an "earliest" date field
        earliest = data.get("earliest") or (inner.get("earliest") if isinstance(inner, dict) else None)
        if earliest:
            result["available"] = True
            result["slots"] = [{"date": earliest}]
            return result

        logger.debug("No slots found in response: %s", data)
        return result
