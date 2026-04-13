#!/usr/bin/env python3
"""
Setup helper — fetches available VAC centers and visa categories
from the VFS LIFT API so you can fill in your .env file.

The master data API requires authentication, so this script:
  1. Tries to load a saved token from browser_login.py (.vfs_token)
  2. If no token, attempts direct login (may fail due to reCAPTCHA)
  3. Uses the token to fetch centers and categories

Usage:
    # First time: run browser_login.py to get a token
    python browser_login.py

    # Then run this:
    python setup_helper.py
"""

import json
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

LIFT_API_BASE = "https://lift-api.vfsglobal.com"
TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".vfs_token")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://visa.vfsglobal.com",
}


def load_token() -> str | None:
    """Load saved token from browser_login.py."""
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        if time.time() < data.get("expires", 0):
            return data["token"]
        else:
            print("  Saved token has expired.")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def try_direct_login() -> str | None:
    """Attempt direct API login (may fail with reCAPTCHA for Algeria)."""
    email = os.getenv("VFS_EMAIL", "")
    password = os.getenv("VFS_PASSWORD", "")
    country = os.getenv("VFS_COUNTRY_CODE", "dza")
    mission = os.getenv("VFS_MISSION_CODE", "ita")

    if not email or not password:
        return None

    print("  Attempting direct login...")
    try:
        resp = requests.post(
            f"{LIFT_API_BASE}/user/login",
            data={
                "username": email,
                "password": password,
                "missioncode": mission,
                "countrycode": country,
            },
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            token = (
                data.get("accessToken") or data.get("token")
                or data.get("data", {}).get("accessToken")
                or data.get("data", {}).get("token")
            )
            if token:
                print("  Direct login succeeded!")
                return token
        print(f"  Direct login failed: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as exc:
        print(f"  Direct login error: {exc}")
    return None


def get_token() -> str:
    """Get an auth token by any means available."""
    # Try saved token first
    token = load_token()
    if token:
        print("  Using saved token from browser_login.py")
        return token

    # Try direct login
    token = try_direct_login()
    if token:
        return token

    print("\n  No valid token available!")
    print("  Run browser_login.py first to authenticate:")
    print()
    print("    pip install playwright")
    print("    playwright install chromium")
    print("    python browser_login.py")
    print()
    print("  Then re-run this script.")
    sys.exit(1)


def fetch_json(url: str, token: str) -> list | dict | None:
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"  [{resp.status_code}] {url}")
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"        {resp.text[:300]}")
    except requests.RequestException as exc:
        print(f"  [ERR] {url} — {exc}")
    return None


def main():
    country = os.getenv("VFS_COUNTRY_CODE", "").strip()
    mission = os.getenv("VFS_MISSION_CODE", "").strip()

    if not country:
        country = input("Country code (e.g. dza for Algeria): ").strip().lower() or "dza"
    if not mission:
        mission = input("Mission code (e.g. ita for Italy): ").strip().lower() or "ita"

    print(f"\n{'='*60}")
    print(f"  VFS Setup Helper — {country.upper()} -> {mission.upper()}")
    print(f"{'='*60}")

    # Authenticate
    print("\n--- Authentication ---")
    token = get_token()

    # Step 1: Get centers
    print(f"\n--- VAC Centers ---")
    url = f"{LIFT_API_BASE}/master/center/{mission}/{country}"
    centers = fetch_json(url, token)

    if not centers:
        print("\n  Could not fetch centers. Token may be invalid.")
        print("  Try running browser_login.py again.")
        return

    if isinstance(centers, list):
        for c in centers:
            if isinstance(c, dict):
                code = c.get("vacCode") or c.get("code") or c.get("centerCode", "")
                name = c.get("vacName") or c.get("name") or c.get("centerName", "")
                print(f"    {code:>10} — {name}")
            else:
                print(f"    {c}")
        print(f"\n  (Full response: {json.dumps(centers[:2], indent=2)[:500]})")
    else:
        print(f"    {json.dumps(centers, indent=2)}")

    # Step 2: Get visa categories
    vac_code = input("\nEnter your VAC code from above (for Algiers): ").strip()
    if not vac_code:
        print("No VAC code entered.")
        return

    print(f"\n--- Visa Categories for {vac_code} ---")
    url = f"{LIFT_API_BASE}/master/visacategory/{mission}/{country}/{vac_code}"
    categories = fetch_json(url, token)

    if categories and isinstance(categories, list):
        for cat in categories:
            if isinstance(cat, dict):
                code = cat.get("visaCategoryCode") or cat.get("code", "")
                name = cat.get("visaCategoryName") or cat.get("name", "")
                print(f"    {code:>10} — {name}")
            else:
                print(f"    {cat}")
        print(f"\n  (Full response: {json.dumps(categories[:2], indent=2)[:500]})")
    elif categories:
        print(f"    {json.dumps(categories, indent=2)}")
    else:
        print("  Could not fetch visa categories.")

    # Step 3: Sub-categories (optional)
    cat_codes = input(
        "\nEnter visa category codes to monitor, comma-separated\n"
        "(e.g. the tourist and business codes from above): "
    ).strip()
    if not cat_codes:
        return

    for cat_code in [c.strip() for c in cat_codes.split(",") if c.strip()]:
        print(f"\n--- Sub-categories for {cat_code} ---")
        url = f"{LIFT_API_BASE}/master/subvisacategory/{mission}/{country}/{vac_code}/{cat_code}"
        subcats = fetch_json(url, token)
        if subcats and isinstance(subcats, list) and len(subcats) > 0:
            for sub in subcats:
                if isinstance(sub, dict):
                    code = sub.get("code") or sub.get("visaSubCategoryCode", "")
                    name = sub.get("name") or sub.get("visaSubCategoryName", "")
                    print(f"    {code:>10} — {name}")
                else:
                    print(f"    {sub}")
        else:
            print("  None (normal for many visa types).")

    # Summary
    print(f"\n{'='*60}")
    print("  Add these to your .env:")
    print(f"{'='*60}")
    print(f"  VFS_COUNTRY_CODE={country}")
    print(f"  VFS_MISSION_CODE={mission}")
    print(f"  VFS_VAC_CODE={vac_code}")
    print(f"  VFS_VISA_CATEGORIES={cat_codes}")
    print()


if __name__ == "__main__":
    main()
