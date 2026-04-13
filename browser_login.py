#!/usr/bin/env python3
"""
Browser-assisted login for VFS.

Algeria has reCAPTCHA on both login and appointment endpoints.
This script opens a real browser, lets you solve the CAPTCHA manually,
then extracts the auth token for the monitor to use.

The token is saved to .vfs_token and loaded by the monitor automatically.
You only need to re-run this when the token expires (~30 min, the monitor
will notify you).

Requires: pip install playwright && playwright install chromium

Usage:
    python browser_login.py
"""

import json
import os
import re
import sys
import time

TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".vfs_token")

LIFT_API_BASE = "https://lift-api.vfsglobal.com"


def save_token(token: str, email: str):
    """Save token to file for the monitor to pick up."""
    data = {
        "token": token,
        "email": email,
        "timestamp": time.time(),
        "expires": time.time() + 25 * 60,
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)
    print(f"\nToken saved to {TOKEN_FILE}")


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


def browser_login():
    """Open browser to VFS login, intercept the auth token."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is required for browser login.")
        print("Install it:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()

    country = os.getenv("VFS_COUNTRY_CODE", "dza").lower()
    mission = os.getenv("VFS_MISSION_CODE", "ita").lower()
    email = os.getenv("VFS_EMAIL", "")

    login_url = f"https://visa.vfsglobal.com/{country}/en/{mission}/login"
    captured_token = {"value": None}

    print(f"Opening VFS login page: {login_url}")
    print("Solve the CAPTCHA and log in. The token will be captured automatically.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Intercept API responses to capture the auth token
        def handle_response(response):
            url = response.url
            if "/user/login" in url or "/login" in url:
                try:
                    body = response.json()
                    token = (
                        body.get("accessToken")
                        or body.get("token")
                        or body.get("data", {}).get("accessToken")
                        or body.get("data", {}).get("token")
                        or body.get("Token")
                        or body.get("access_token")
                    )
                    if token:
                        captured_token["value"] = token
                        print(f"\nToken captured! ({token[:20]}...)")
                except Exception:
                    pass

            # Also check for tokens in Authorization headers of subsequent requests
            if LIFT_API_BASE in url and response.status == 200:
                try:
                    body = response.json()
                    for key in ("accessToken", "token", "Token"):
                        if key in body and body[key]:
                            captured_token["value"] = body[key]
                except Exception:
                    pass

        page.on("response", handle_response)

        # Also intercept requests to capture Authorization header
        def handle_request(request):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and len(auth) > 20:
                token = auth[7:]
                if not captured_token["value"]:
                    captured_token["value"] = token
                    print(f"\nToken captured from request header! ({token[:20]}...)")

        page.on("request", handle_request)

        page.goto(login_url, wait_until="domcontentloaded")

        # Pre-fill email if available
        if email:
            try:
                page.wait_for_selector('input[type="email"], input[name="username"], input[name="email"]', timeout=5000)
                email_input = page.query_selector('input[type="email"], input[name="username"], input[name="email"]')
                if email_input:
                    email_input.fill(email)
                    print(f"Pre-filled email: {email}")
            except Exception:
                pass

        # Wait for user to complete login
        print("Waiting for you to log in...")
        print("(The browser will close automatically once the token is captured)")
        print("(Or close the browser manually to abort)\n")

        # Poll until token captured or browser closed
        try:
            while not captured_token["value"]:
                if page.is_closed():
                    break
                page.wait_for_timeout(1000)

                # Also try to grab token from localStorage/sessionStorage
                try:
                    for storage_fn in [
                        "localStorage.getItem('token')",
                        "localStorage.getItem('accessToken')",
                        "sessionStorage.getItem('token')",
                        "sessionStorage.getItem('accessToken')",
                    ]:
                        val = page.evaluate(storage_fn)
                        if val and len(val) > 20:
                            captured_token["value"] = val
                            print(f"\nToken found in browser storage! ({val[:20]}...)")
                            break
                except Exception:
                    pass

        except Exception:
            pass

        browser.close()

    if captured_token["value"]:
        save_token(captured_token["value"], email)
        print("\nDone! Start the monitor with: python monitor.py")
        print("The monitor will use this token automatically.")
    else:
        print("\nNo token captured. Try again.")
        sys.exit(1)


if __name__ == "__main__":
    browser_login()
