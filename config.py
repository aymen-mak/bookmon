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
VFS_COUNTRY_CODE = _require("VFS_COUNTRY_CODE")
VFS_MISSION_CODE = _require("VFS_MISSION_CODE")
VFS_CENTER_CODE = _require("VFS_CENTER_CODE")
VFS_VISA_CATEGORY = _require("VFS_VISA_CATEGORY")
VFS_VISA_SUBCATEGORY = os.getenv("VFS_VISA_SUBCATEGORY", "").strip()

# Monitoring
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "180"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
