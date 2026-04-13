import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        sys.exit(f"ERROR: {name} is not set. Copy .env.example to .env and fill it in.")
    return val


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# VFS credentials
VFS_EMAIL = _require("VFS_EMAIL")
VFS_PASSWORD = _require("VFS_PASSWORD")

# VFS route
VFS_COUNTRY_CODE = _require("VFS_COUNTRY_CODE")    # "dza"
VFS_MISSION_CODE = _require("VFS_MISSION_CODE")    # "ita"

# These may be empty during initial setup (before running setup_helper.py)
VFS_VAC_CODE = _optional("VFS_VAC_CODE")           # Algiers center code
VFS_VISA_CATEGORIES = [
    c.strip() for c in _optional("VFS_VISA_CATEGORIES").split(",") if c.strip()
]

# Monitoring
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "180"))

# Telegram
TELEGRAM_BOT_TOKEN = _optional("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _optional("TELEGRAM_CHAT_ID")

# Optional: 2captcha API key for reCAPTCHA
CAPTCHA_API_KEY = _optional("CAPTCHA_API_KEY")
