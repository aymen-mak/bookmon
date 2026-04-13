#!/usr/bin/env python3
"""
VFS Endpoint Discovery Helper

VFS Global uses different API endpoints depending on the country pair.
This script probes known VFS API patterns for your specific route
and reports which ones respond.

Usage:
    python discover_endpoints.py

It reads VFS_COUNTRY_CODE and VFS_MISSION_CODE from your .env file.
"""

import requests
from dotenv import load_dotenv
import os

load_dotenv()

country = os.getenv("VFS_COUNTRY_CODE", "dza").lower()
mission = os.getenv("VFS_MISSION_CODE", "ita").lower()

KNOWN_API_BASES = [
    "https://lift-api.vfsglobal.com/appointment",
    "https://lift-api.vfsglobal.com",
    f"https://visa.vfsglobal.com/{country}/en/{mission}/api",
    f"https://visa.vfsglobal.com/one-pager/vfsgatewayservice",
    "https://app.vfrgroup.com/api",  # some VFS regions use this
]

KNOWN_LOGIN_PATHS = [
    "/login",
    "/Login",
    "/authentication/login",
    "/session/login",
    "/appointmentschedule/login",
]

KNOWN_SLOT_PATHS = [
    "/CheckIsSlotAvailable",
    "/checkIsSlotAvailable",
    "/slots/availability",
    "/appointmentAvailability",
    "/appointment/slots",
    "/calendar/available",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://visa.vfsglobal.com",
}


def probe(url: str) -> tuple[int | None, str]:
    """Send a lightweight request and return (status_code, note)."""
    try:
        # Use POST with empty body — we just want to see if the endpoint exists
        resp = requests.post(url, json={}, headers=HEADERS, timeout=10)
        code = resp.status_code
        body_preview = resp.text[:200]

        if code == 404:
            return code, "Not found"
        elif code == 405:
            # Method not allowed = endpoint exists but expects different method
            return code, "Exists (try GET)"
        elif code in (400, 401, 422):
            # Bad request / unauthorized = endpoint exists, needs proper auth
            return code, f"Exists (needs auth/params): {body_preview}"
        elif code == 200:
            return code, f"OK: {body_preview}"
        else:
            return code, body_preview
    except requests.ConnectionError:
        return None, "Connection refused"
    except requests.Timeout:
        return None, "Timeout"
    except requests.RequestException as exc:
        return None, str(exc)


def main():
    print(f"Probing VFS endpoints for {country.upper()} → {mission.upper()}")
    print("=" * 70)

    # First, check which base URLs respond
    print("\n--- Checking base URLs ---")
    responsive_bases = []
    for base in KNOWN_API_BASES:
        code, note = probe(base)
        status = f"HTTP {code}" if code else "FAIL"
        print(f"  [{status:>8}] {base}")
        print(f"            {note}")
        if code and code != 404:
            responsive_bases.append(base)

    # Then probe login endpoints on responsive bases
    print("\n--- Checking login endpoints ---")
    for base in responsive_bases:
        for path in KNOWN_LOGIN_PATHS:
            url = base + path
            code, note = probe(url)
            status = f"HTTP {code}" if code else "FAIL"
            marker = " <<<" if code and code in (200, 400, 401, 422) else ""
            print(f"  [{status:>8}] {url}{marker}")
            if marker:
                print(f"            {note}")

    # Probe slot-check endpoints
    print("\n--- Checking slot-availability endpoints ---")
    for base in responsive_bases:
        for path in KNOWN_SLOT_PATHS:
            url = base + path
            code, note = probe(url)
            status = f"HTTP {code}" if code else "FAIL"
            marker = " <<<" if code and code in (200, 400, 401, 422) else ""
            print(f"  [{status:>8}] {url}{marker}")
            if marker:
                print(f"            {note}")

    # Also check the web portal itself
    print("\n--- Checking web portal ---")
    portal_url = f"https://visa.vfsglobal.com/{country}/en/{mission}"
    try:
        resp = requests.get(portal_url, headers=HEADERS, timeout=10, allow_redirects=True)
        print(f"  [HTTP {resp.status_code:>3}] {portal_url}")
        print(f"            Final URL: {resp.url}")
        if resp.status_code == 200:
            # Look for API base URL hints in the page
            text = resp.text
            for hint in ["apiBase", "API_URL", "baseUrl", "GATEWAY", "lift-api"]:
                idx = text.find(hint)
                if idx != -1:
                    snippet = text[max(0, idx - 20):idx + 100].replace("\n", " ")
                    print(f"            Found '{hint}': ...{snippet}...")
    except requests.RequestException as exc:
        print(f"  [FAIL    ] {portal_url} — {exc}")

    print("\n" + "=" * 70)
    print("Endpoints marked with <<< are likely valid.")
    print("Update ENDPOINTS in vfs_client.py with the correct URLs.")
    print()
    print("TIP: For the most accurate results, intercept the Android app's")
    print("traffic using HTTP Toolkit (https://httptoolkit.com/) — it's free")
    print("and works without rooting your phone.")


if __name__ == "__main__":
    main()
