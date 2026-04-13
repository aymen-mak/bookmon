#!/usr/bin/env python3
"""
Browser-assisted login for VFS LIFT API.

Algeria has reCAPTCHA on login. This script:
  1. First tries direct LIFT API login (no CAPTCHA — may work!)
  2. If that fails, opens a browser for you to log in manually
  3. Captures the LIFT API token specifically (not the web portal token)

The token is saved to .vfs_token for the monitor to pick up.

Requires for browser fallback:
    pip install playwright && playwright install chromium

Usage:
    python browser_login.py
"""

import json
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".vfs_token")
LIFT_API_BASE = "https://lift-api.vfsglobal.com"


def save_token(token: str, email: str, source: str):
    """Save token to file for the monitor to pick up."""
    data = {
        "token": token,
        "email": email,
        "source": source,
        "timestamp": time.time(),
        "expires": time.time() + 25 * 60,
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)
    print(f"\n  Token saved to {TOKEN_FILE} (source: {source})")
    print(f"  Expires in ~25 minutes.")


def load_token() -> dict | None:
    """Load a previously saved token if still valid."""
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        if time.time() < data.get("expires", 0):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def extract_token(data: dict) -> str | None:
    """Extract token from a login response (tries multiple field names)."""
    if not isinstance(data, dict):
        return None
    return (
        data.get("accessToken")
        or data.get("token")
        or data.get("data", {}).get("accessToken")
        or data.get("data", {}).get("token")
        or data.get("Token")
        or data.get("access_token")
    )


def try_direct_login(email: str, password: str, country: str, mission: str) -> str | None:
    """
    Attempt direct login to the LIFT API.
    The reCAPTCHA might only be enforced on the frontend.
    """
    print("\n--- Attempt 1: Direct LIFT API login ---")
    print(f"  POST {LIFT_API_BASE}/user/login")

    try:
        resp = requests.post(
            f"{LIFT_API_BASE}/user/login",
            data={
                "username": email,
                "password": password,
                "missioncode": mission,
                "countrycode": country,
            },
            headers={
                "User-Agent": "okhttp/4.12.0",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )
        print(f"  Response: HTTP {resp.status_code}")
        print(f"  Body: {resp.text[:300]}")

        if resp.status_code == 200:
            data = resp.json()
            token = extract_token(data)
            if token:
                print(f"\n  Direct login WORKED! Token: {token[:30]}...")
                return token
            else:
                print(f"  Got 200 but no token in response.")

        elif resp.status_code == 403:
            print("  403 Forbidden — likely needs CAPTCHA or additional headers.")

    except Exception as exc:
        print(f"  Error: {exc}")

    return None


def try_browser_login(email: str, country: str, mission: str) -> str | None:
    """
    Open browser to the VFS website. Intercept LIFT API calls to capture
    the token. If the website doesn't call LIFT API directly, inject a
    LIFT API login call using the web session.
    """
    print("\n--- Attempt 2: Browser-assisted login ---")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright is required for browser login.")
        print("  Install:")
        print("    pip install playwright")
        print("    playwright install chromium")
        return None

    login_url = f"https://visa.vfsglobal.com/{country}/en/{mission}/login"
    captured = {"lift_token": None, "web_token": None}

    print(f"  Opening: {login_url}")
    print(f"  Log in and solve the CAPTCHA. Token will be captured automatically.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        def handle_response(response):
            url = response.url

            # Priority: capture tokens from LIFT API calls
            if "lift-api.vfsglobal.com" in url:
                try:
                    body = response.json()
                    token = extract_token(body)
                    if token:
                        captured["lift_token"] = token
                        print(f"  LIFT API token captured from {url}")
                except Exception:
                    pass

            # Also capture web portal tokens as fallback
            if "/login" in url.lower() and response.status == 200:
                try:
                    body = response.json()
                    token = extract_token(body)
                    if token and not captured["lift_token"]:
                        captured["web_token"] = token
                        print(f"  Web token captured from {url}")
                except Exception:
                    pass

        def handle_request(request):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and "lift-api.vfsglobal.com" in request.url:
                token = auth[7:]
                if not captured["lift_token"]:
                    captured["lift_token"] = token
                    print(f"  LIFT token captured from request header!")

        page.on("response", handle_response)
        page.on("request", handle_request)

        page.goto(login_url, wait_until="domcontentloaded")

        # Pre-fill email
        if email:
            try:
                page.wait_for_selector(
                    'input[type="email"], input[name="username"], input[name="email"]',
                    timeout=5000,
                )
                el = page.query_selector('input[type="email"], input[name="username"], input[name="email"]')
                if el:
                    el.fill(email)
            except Exception:
                pass

        print("  Waiting for login... (close browser to abort)\n")

        try:
            while not captured["lift_token"]:
                if page.is_closed():
                    break
                page.wait_for_timeout(1000)

                # Check browser storage for tokens
                try:
                    for key in ["token", "accessToken", "lift_token", "auth_token"]:
                        for store in ["localStorage", "sessionStorage"]:
                            val = page.evaluate(f"{store}.getItem('{key}')")
                            if val and len(val) > 20 and not captured["lift_token"]:
                                captured["lift_token"] = val
                                print(f"  Token found in {store}['{key}']!")
                                break
                except Exception:
                    pass

                # If we got a web token, check if it also works on LIFT API
                if captured["web_token"] and not captured["lift_token"]:
                    # Test the web token against a LIFT API endpoint
                    try:
                        test_resp = requests.get(
                            f"{LIFT_API_BASE}/master/center/{mission}/{country}",
                            headers={
                                "Authorization": f"Bearer {captured['web_token']}",
                                "User-Agent": "okhttp/4.12.0",
                                "Accept": "application/json",
                            },
                            timeout=5,
                        )
                        if test_resp.status_code == 200:
                            print("  Web token works on LIFT API too!")
                            captured["lift_token"] = captured["web_token"]
                    except Exception:
                        pass

        except Exception:
            pass

        browser.close()

    return captured["lift_token"] or captured["web_token"]


def main():
    email = os.getenv("VFS_EMAIL", "")
    password = os.getenv("VFS_PASSWORD", "")
    country = os.getenv("VFS_COUNTRY_CODE", "dza").lower()
    mission = os.getenv("VFS_MISSION_CODE", "ita").lower()

    if not email or not password:
        print("ERROR: Set VFS_EMAIL and VFS_PASSWORD in .env first.")
        sys.exit(1)

    print("=" * 60)
    print("  VFS LIFT API Login")
    print(f"  User: {email}")
    print(f"  Route: {country.upper()} -> {mission.upper()}")
    print("=" * 60)

    # Check for existing valid token
    existing = load_token()
    if existing:
        remaining = int(existing["expires"] - time.time())
        print(f"\n  Existing token found ({remaining}s remaining, source: {existing.get('source', '?')})")
        choice = input("  Use existing token? [Y/n]: ").strip().lower()
        if choice != "n":
            print("  Keeping existing token.")
            return

    # Attempt 1: Direct API login (no browser needed)
    token = try_direct_login(email, password, country, mission)

    if token:
        save_token(token, email, "direct_lift_api")
        print("\nDone! Run: python monitor.py")
        return

    # Attempt 2: Browser-assisted login
    print("\n  Direct login didn't work. Trying browser login...")
    token = try_browser_login(email, country, mission)

    if token:
        save_token(token, email, "browser_lift_api")
        print("\nDone! Run: python monitor.py")
    else:
        print("\nNo token captured.")
        print("Tips:")
        print("  1. Make sure you completed the login + CAPTCHA in the browser")
        print("  2. Navigate to the appointment booking page after logging in")
        print("     (this triggers LIFT API calls where we can capture the token)")
        print("  3. Try again: python browser_login.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
