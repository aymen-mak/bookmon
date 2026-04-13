import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        sys.exit(f"ERROR: {name} is not set. Copy .env.example to .env and fill it in.")
    return val


# VFS credentials
VFS_EMAIL = _require("VFS_EMAIL")
VFS_PASSWORD = _require("VFS_PASSWORD")

# VFS appointment parameters
VFS_COUNTRY_CODE = _require("VFS_COUNTRY_CODE")    # "dza"
VFS_MISSION_CODE = _require("VFS_MISSION_CODE")    # "ita"
VFS_VAC_CODE = _require("VFS_VAC_CODE")            # Algiers center code

# Comma-separated visa categories to monitor (e.g. "TOUR,BUS" or "SCH")
# Run "python setup_helper.py" to find the exact codes for your center
VFS_VISA_CATEGORIES = [
    c.strip() for c in _require("VFS_VISA_CATEGORIES").split(",") if c.strip()
]

# Monitoring
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "180"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Optional: 2captcha API key for reCAPTCHA
CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY", "").strip()
