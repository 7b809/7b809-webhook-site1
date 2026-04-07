import requests
import os
import logging
import re
import time
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("telegram")

# ============================================
# 🔑 ENV CONFIG
# ============================================

# ✅ Default fallback bot
DEFAULT_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ✅ Same chat ID
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ✅ Bot tokens per NAME
BOT_TOKEN_MAP = {
    "bitcoin": os.getenv("BOT_TOKEN_BITCOIN"),
    "gift-nifty": os.getenv("BOT_TOKEN_GIFT_NIFTY"),
    "nifty": os.getenv("BOT_TOKEN_NIFTY"),
}

MAX_RETRIES = 3
RETRY_DELAY = 2


# ============================================
# 🧹 Clean message
# ============================================
def clean_message(text):
    try:
        if not text:
            return "N/A"

        text = re.sub(r"\s+", " ", text).strip()
        return text[:1000]

    except Exception as e:
        logger.error(f"❌ Clean error: {e}")
        return "N/A"


# ============================================
# 🔁 Get Bot Token
# ============================================
def get_bot_token(name):
    try:
        token = BOT_TOKEN_MAP.get(name)

        if token:
            return token

        logger.warning(f"⚠️ No bot for {name}, using default")
        return DEFAULT_BOT_TOKEN

    except Exception as e:
        logger.error(f"❌ Token error: {e}")
        return DEFAULT_BOT_TOKEN


# ============================================
# 🚀 Core Send Logic
# ============================================
def _send_with_token(text, bot_token):
    if not bot_token:
        logger.error("❌ Bot token missing")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = requests.post(url, json=payload, timeout=10)

            if res.status_code == 200:
                return True

            logger.error(f"❌ Telegram error (attempt {attempt}): {res.text}")

        except requests.exceptions.Timeout:
            logger.error(f"⏳ Timeout (attempt {attempt})")

        except requests.exceptions.ConnectionError:
            logger.error(f"🌐 Connection error (attempt {attempt})")

        except Exception as e:
            logger.error(f"❌ Telegram exception (attempt {attempt}): {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)

    return False


# ============================================
# 📩 MAIN SEND FUNCTION (USE THIS ONLY)
# ============================================
def send_telegram_message(text, name=None):
    if not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Chat ID missing")
        return

    # ✅ Get correct bot
    bot_token = get_bot_token(name)

    # ✅ Try primary bot
    success = _send_with_token(text, bot_token)

    if success:
        return

    # 🔥 Fallback to default bot
    if bot_token != DEFAULT_BOT_TOKEN:
        logger.warning("🔁 Fallback → DEFAULT bot")

        fallback_success = _send_with_token(text, DEFAULT_BOT_TOKEN)

        if fallback_success:
            return

    logger.error("🚫 All Telegram attempts failed")


# ============================================
# ✨ Format Message
# ============================================
def format_telegram_message(data):
    try:
        name = clean_message(data.get("name"))
        indicator = clean_message(data.get("indicator"))
        message = clean_message(data.get("content"))
        time_val = clean_message(data.get("time"))

        return (
            f"<b>📊 Trading Alert</b>\n"
            f"<b>Symbol:</b> {name}\n"
            f"<b>Indicator:</b> {indicator}\n"
            f"<b>Message:</b> {message}\n"
            f"<b>Time:</b> {time_val}"
        )

    except Exception as e:
        logger.error(f"❌ Format error: {e}")

        try:
            return f"⚠️ Alert\n{str(data)[:500]}"
        except:
            return "⚠️ New Alert Received"