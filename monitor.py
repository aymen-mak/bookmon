#!/usr/bin/env python3
"""
VFS Global Appointment Monitor — Algeria → Italy

Checks for available visa appointment slots across multiple visa
categories (tourist, business, etc.) and sends Telegram alerts.

Usage:
    1. cp .env.example .env && edit .env
    2. pip install -r requirements.txt
    3. python setup_helper.py          (find your VAC code + visa categories)
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
    # Validate required config
    if not config.VFS_VAC_CODE:
        logger.error("VFS_VAC_CODE is not set. Run 'python setup_helper.py' first.")
        return
    if not config.VFS_VISA_CATEGORIES:
        logger.error("VFS_VISA_CATEGORIES is not set. Run 'python setup_helper.py' first.")
        return

    categories = config.VFS_VISA_CATEGORIES

    logger.info("=" * 60)
    logger.info("  VFS Appointment Monitor")
    logger.info("  Route: %s -> %s", config.VFS_COUNTRY_CODE.upper(), config.VFS_MISSION_CODE.upper())
    logger.info("  Center: %s", config.VFS_VAC_CODE)
    logger.info("  Categories: %s", ", ".join(categories))
    logger.info("=" * 60)

    # ── Initialize VFS client ────────────────────────────────────────
    client = VFSClient(
        email=config.VFS_EMAIL,
        password=config.VFS_PASSWORD,
        country_code=config.VFS_COUNTRY_CODE,
        mission_code=config.VFS_MISSION_CODE,
        vac_code=config.VFS_VAC_CODE,
        captcha_api_key=config.CAPTCHA_API_KEY,
    )

    # Auth strategy: try direct LIFT API login first, fall back to saved token
    if not client.login():
        logger.info("Direct login failed, trying saved token...")
        saved_token = load_saved_token()
        if saved_token:
            client.set_token(saved_token)
        else:
            logger.error(
                "No authentication available. Either:\n"
                "  1. Direct login will be retried each cycle, or\n"
                "  2. Run 'python browser_login.py' to get a token"
            )

    # ── Initialize notifier ──────────────────────────────────────────
    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
    )

    config_summary = (
        f"Route: {config.VFS_COUNTRY_CODE.upper()} -> {config.VFS_MISSION_CODE.upper()}\n"
        f"Center: {config.VFS_VAC_CODE}\n"
        f"Categories: {', '.join(categories)}\n"
        f"Interval: every {config.CHECK_INTERVAL_SECONDS}s"
    )
    logger.info("Config:\n%s", config_summary)
    notifier.send_startup(config_summary)

    # ── Main loop ────────────────────────────────────────────────────
    consecutive_errors = 0
    last_notified: dict[str, float] = {}  # per-category cooldown
    notify_cooldown = 300
    token_expired_notified = False

    while _running:
        logger.info("Checking %d category(ies)...", len(categories))

        had_error = False

        for category in categories:
            if not _running:
                break

            logger.info("[%s] Checking availability...", category)
            result = client.check_slot_available(category)

            if result.get("error"):
                had_error = True
                error_msg = result["error"]
                logger.warning("[%s] Failed: %s", category, error_msg)

                # Detect token expiry
                if "401" in str(error_msg) or "auth" in str(error_msg).lower():
                    if not token_expired_notified:
                        notifier.send(
                            "*VFS Monitor: Token expired*\n\n"
                            "Run `python browser_login.py` to re-authenticate.\n"
                            "Monitor will pick up the new token automatically."
                        )
                        token_expired_notified = True

                    new_token = load_saved_token()
                    if new_token and new_token != client.token:
                        logger.info("New token detected!")
                        client.token = new_token
                        client.token_expires = time.time() + 25 * 60
                        client.session.headers["Authorization"] = f"Bearer {new_token}"
                        token_expired_notified = False
                        consecutive_errors = 0
                        break  # restart the category loop with fresh token

            elif result["available"]:
                slots = result["slots"]
                logger.info("[%s] SLOTS FOUND! %d slot(s).", category, len(slots))

                now = time.time()
                last = last_notified.get(category, 0)
                if now - last >= notify_cooldown:
                    alert = format_slot_alert(
                        slots,
                        config.VFS_COUNTRY_CODE,
                        config.VFS_MISSION_CODE,
                        config.VFS_VAC_CODE,
                        category,
                    )
                    logger.info("\n%s", alert)
                    notifier.send(alert)
                    last_notified[category] = now
                else:
                    logger.info("[%s] Slots still available (cooldown).", category)
            else:
                logger.info("[%s] No slots.", category)

            # Small delay between category checks to avoid hammering
            if len(categories) > 1:
                time.sleep(2)

        # Track consecutive errors
        if had_error:
            consecutive_errors += 1
            if consecutive_errors == 5:
                notifier.send(
                    "*VFS Monitor: repeated errors*\n\n"
                    "5 consecutive check cycles have failed.\n"
                    "Monitor will keep retrying."
                )
        else:
            consecutive_errors = 0
            token_expired_notified = False

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
