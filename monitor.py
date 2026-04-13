#!/usr/bin/env python3
"""
VFS Global Appointment Monitor

Continuously checks for available visa appointment slots on the VFS
LIFT API and sends a Telegram notification the instant one appears.

Usage:
    1. cp .env.example .env && edit .env
    2. pip install -r requirements.txt
    3. python setup_helper.py          (find your VAC code + visa category)
    4. python browser_login.py         (solve CAPTCHA once, saves token)
    5. python monitor.py               (start monitoring)
"""

import json
import logging
import os
import signal
import time

import config
from vfs_client import VFSClient
from notifier import TelegramNotifier, format_slot_alert

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Graceful shutdown ────────────────────────────────────────────────
_running = True


def _shutdown(signum, frame):
    global _running
    logger.info("Shutting down (signal %s)...", signum)
    _running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".vfs_token")


def load_saved_token() -> str | None:
    """Load a token saved by browser_login.py if still valid."""
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        if time.time() < data.get("expires", 0):
            logger.info("Loaded saved token from browser_login.py")
            return data["token"]
        else:
            logger.warning("Saved token has expired. Run browser_login.py again.")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def main():
    logger.info("=" * 60)
    logger.info("  VFS Appointment Monitor")
    logger.info("=" * 60)

    # ── Initialize VFS client ────────────────────────────────────────
    client = VFSClient(
        email=config.VFS_EMAIL,
        password=config.VFS_PASSWORD,
        country_code=config.VFS_COUNTRY_CODE,
        mission_code=config.VFS_MISSION_CODE,
        vac_code=config.VFS_VAC_CODE,
        visa_category=config.VFS_VISA_CATEGORY,
        visa_subcategory=config.VFS_VISA_SUBCATEGORY,
        captcha_api_key=config.CAPTCHA_API_KEY,
    )

    # Try loading a browser-saved token first (skips login + CAPTCHA)
    saved_token = load_saved_token()
    if saved_token:
        client.token = saved_token
        client.token_expires = time.time() + 25 * 60
        client.session.headers["Authorization"] = f"Bearer {saved_token}"

    # ── Initialize notifier ──────────────────────────────────────────
    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
    )

    config_summary = (
        f"Route: {config.VFS_COUNTRY_CODE.upper()} -> {config.VFS_MISSION_CODE.upper()}\n"
        f"Center: {config.VFS_VAC_CODE}\n"
        f"Category: {config.VFS_VISA_CATEGORY}\n"
        f"Interval: every {config.CHECK_INTERVAL_SECONDS}s"
    )
    logger.info("Config:\n%s", config_summary)
    notifier.send_startup(config_summary)

    # ── Main loop ────────────────────────────────────────────────────
    consecutive_errors = 0
    last_notified = 0
    notify_cooldown = 300  # re-notify at most every 5 minutes
    token_expired_notified = False

    while _running:
        logger.info("Checking for available appointments...")

        # Primary check: CheckIsSlotAvailable
        result = client.check_slot_available()

        if result.get("error"):
            consecutive_errors += 1
            error_msg = result["error"]
            logger.warning("Check failed (%d): %s", consecutive_errors, error_msg)

            # Detect token expiry — user needs to re-run browser_login.py
            if "401" in str(error_msg) or "auth" in str(error_msg).lower():
                if not token_expired_notified:
                    notifier.send(
                        "*VFS Monitor: Token expired*\n\n"
                        "Run `python browser_login.py` to re-authenticate.\n"
                        "The monitor will pick up the new token automatically."
                    )
                    token_expired_notified = True

                # Check for a refreshed token file
                new_token = load_saved_token()
                if new_token and new_token != client.token:
                    logger.info("New token detected from browser_login.py!")
                    client.token = new_token
                    client.token_expires = time.time() + 25 * 60
                    client.session.headers["Authorization"] = f"Bearer {new_token}"
                    token_expired_notified = False
                    consecutive_errors = 0
                    continue

            if consecutive_errors == 5:
                notifier.send(
                    f"*VFS Monitor: repeated errors*\n\n"
                    f"Last error: {error_msg}\n\n"
                    f"The monitor will keep retrying."
                )
        else:
            consecutive_errors = 0
            token_expired_notified = False

            if result["available"]:
                slots = result["slots"]
                logger.info("SLOTS FOUND! %d slot(s).", len(slots))

                now = time.time()
                if now - last_notified >= notify_cooldown:
                    alert = format_slot_alert(
                        slots,
                        config.VFS_COUNTRY_CODE,
                        config.VFS_MISSION_CODE,
                        config.VFS_VAC_CODE,
                        config.VFS_VISA_CATEGORY,
                    )
                    logger.info("\n%s", alert)
                    notifier.send(alert)
                    last_notified = now
                else:
                    logger.info("Slots still available (cooldown active).")
            else:
                logger.info("No slots available.")
                logger.debug("Raw response: %s", result.get("raw"))

        # ── Sleep ────────────────────────────────────────────────────
        if consecutive_errors > 0:
            sleep_time = min(
                config.CHECK_INTERVAL_SECONDS * (2 ** min(consecutive_errors, 3)),
                600,
            )
        else:
            sleep_time = config.CHECK_INTERVAL_SECONDS

        logger.info("Next check in %ds ...", sleep_time)

        end_time = time.time() + sleep_time
        while _running and time.time() < end_time:
            time.sleep(1)

    logger.info("Monitor stopped.")


if __name__ == "__main__":
    main()
