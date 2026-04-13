"""
Notification backends for the VFS appointment monitor.

Currently supports:
  - Telegram (recommended — instant push to your phone)
  - Console (always on — prints to terminal)
"""

import json
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    """Send notifications via a Telegram bot."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)

        if not self.enabled:
            logger.warning(
                "Telegram not configured — notifications will only print to console. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable."
            )

    def send(self, message: str) -> bool:
        """Send a message via Telegram. Returns True on success."""
        if not self.enabled:
            return False

        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                logger.info("Telegram notification sent.")
                return True
            else:
                logger.error(
                    "Telegram send failed: HTTP %d — %s",
                    resp.status_code,
                    resp.text[:300],
                )
                return False
        except requests.RequestException as exc:
            logger.error("Telegram request failed: %s", exc)
            return False

    def send_startup(self, config_summary: str) -> bool:
        """Send a startup confirmation so you know the monitor is running."""
        return self.send(f"*VFS Monitor Started*\n\n{config_summary}")


def format_slot_alert(slots: list, country_code: str, mission_code: str,
                      center_code: str, visa_category: str) -> str:
    """Format a human-readable alert message for available slots."""
    lines = [
        "*APPOINTMENT SLOTS AVAILABLE*",
        "",
        f"Route: {country_code.upper()} → {mission_code.upper()}",
        f"Center: {center_code}",
        f"Category: {visa_category}",
        "",
    ]

    for i, slot in enumerate(slots[:10], 1):  # Show up to 10 slots
        if isinstance(slot, dict):
            date = slot.get("date") or slot.get("Date") or slot.get("AppointmentDate", "")
            time_val = slot.get("time") or slot.get("Time") or slot.get("AppointmentTime", "")
            if date:
                line = f"  {i}. {date}"
                if time_val:
                    line += f" at {time_val}"
                lines.append(line)
            else:
                lines.append(f"  {i}. {json.dumps(slot)}")
        else:
            lines.append(f"  {i}. {slot}")

    if len(slots) > 10:
        lines.append(f"  ... and {len(slots) - 10} more")

    lines.extend([
        "",
        "Book NOW before they're gone!",
    ])

    return "\n".join(lines)
