#!/usr/bin/env python3
"""
VFS Global Appointment Monitor

Continuously checks for available visa appointment slots and sends
a Telegram notification the moment one appears.

Usage:
    1. Copy .env.example to .env and fill in your values
    2. pip install -r requirements.txt
    3. python monitor.py

For Algeria → Italy (Algiers center), your .env would look like:
    VFS_COUNTRY_CODE=dza
    VFS_MISSION_CODE=ita
    VFS_CENTER_CODE=ALG
    VFS_VISA_CATEGORY=SCH
"""

import logging
import signal
import sys
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


def main():
    logger.info("=" * 60)
    logger.info("  VFS Appointment Monitor")
    logger.info("=" * 60)

    # ── Initialize components ────────────────────────────────────────
    client = VFSClient(
        email=config.VFS_EMAIL,
        password=config.VFS_PASSWORD,
        country_code=config.VFS_COUNTRY_CODE,
        mission_code=config.VFS_MISSION_CODE,
        center_code=config.VFS_CENTER_CODE,
        visa_category=config.VFS_VISA_CATEGORY,
        visa_subcategory=config.VFS_VISA_SUBCATEGORY,
    )

    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
    )

    config_summary = (
        f"Route: {config.VFS_COUNTRY_CODE.upper()} → {config.VFS_MISSION_CODE.upper()}\n"
        f"Center: {config.VFS_CENTER_CODE}\n"
        f"Category: {config.VFS_VISA_CATEGORY}\n"
        f"Interval: every {config.CHECK_INTERVAL_SECONDS}s"
    )
    logger.info("Config:\n%s", config_summary)

    # Send a startup ping so you know it's running
    notifier.send_startup(config_summary)

    # ── Main loop ────────────────────────────────────────────────────
    consecutive_errors = 0
    last_notified = 0  # timestamp of last notification (avoid spam)
    notify_cooldown = 300  # re-notify at most every 5 minutes

    while _running:
        logger.info("Checking for available appointments...")

        result = client.check_availability()

        if result.get("error"):
            consecutive_errors += 1
            logger.warning(
                "Check failed (%d consecutive): %s",
                consecutive_errors,
                result["error"],
            )
            # After 5 consecutive errors, notify the user
            if consecutive_errors == 5:
                notifier.send(
                    f"*VFS Monitor: repeated errors*\n\n"
                    f"Last error: {result['error']}\n\n"
                    f"The monitor will keep retrying."
                )
        else:
            consecutive_errors = 0

            if result["available"]:
                logger.info(
                    "SLOTS FOUND! %d slot(s) available.",
                    len(result["slots"]),
                )

                now = time.time()
                if now - last_notified >= notify_cooldown:
                    alert = format_slot_alert(
                        result["slots"],
                        config.VFS_COUNTRY_CODE,
                        config.VFS_MISSION_CODE,
                        config.VFS_CENTER_CODE,
                        config.VFS_VISA_CATEGORY,
                    )
                    logger.info("\n%s", alert)
                    notifier.send(alert)
                    last_notified = now
                else:
                    logger.info("Slots still available (notification cooldown active).")
            else:
                logger.info("No slots available.")

        # ── Sleep with early exit support ────────────────────────────
        # Use exponential backoff on errors (max 10 min)
        if consecutive_errors > 0:
            backoff = min(config.CHECK_INTERVAL_SECONDS * (2 ** min(consecutive_errors, 3)), 600)
            sleep_time = backoff
        else:
            sleep_time = config.CHECK_INTERVAL_SECONDS

        logger.info("Next check in %ds ...", sleep_time)

        # Sleep in 1-second ticks so we can respond to SIGINT quickly
        end_time = time.time() + sleep_time
        while _running and time.time() < end_time:
            time.sleep(1)

    logger.info("Monitor stopped.")


if __name__ == "__main__":
    main()
