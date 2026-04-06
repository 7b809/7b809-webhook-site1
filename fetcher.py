import requests
import time
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from db import collection
from dotenv import load_dotenv
from telegram_msg import send_telegram_message, format_telegram_message
from pymongo.errors import DuplicateKeyError  # ✅ NEW

load_dotenv()

# 🔧 Config
FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL", 5))
MAX_RETRIES = 3
RETRY_DELAY = 2
TEST_LOG = os.getenv("TEST_LOG", "false").lower() == "true"

# 🪵 Logger setup
logger = logging.getLogger("fetcher")
logger.setLevel(logging.DEBUG if TEST_LOG else logging.ERROR)

console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
console_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(console_handler)


# 🔹 Logging helpers
def log_debug(msg):
    if TEST_LOG:
        logger.debug(msg)

def log_info(msg):
    if TEST_LOG:
        logger.info(msg)

def log_error(msg):
    logger.error(msg)


# =========================================================
# ✅ MAPPING SYSTEM (UNCHANGED)
# =========================================================

NAME_MAP = {
    "1": "bitcoin",
    "2": "gift-nifty",
    "3": "nifty"
}

INDICATOR_MAP = {
    "1": "wavetrend",
    "2": "s-and-r",
    "3": "xm-indicator"
}

BASE_URL = "https://webhook.site/token/"

WEBHOOKS = [
    {"name": "1", "indicator": "1", "id": "3aa04588-004b-4c88-8a33-cbe3785e3335"},
    {"name": "2", "indicator": "1", "id": "c68c9b2c-fc6e-4d03-8a80-8fcfa8aae9c2"},
    {"name": "3", "indicator": "1", "id": "cc3189d3-d121-4ccc-8000-f662803cb358"},

    {"name": "1", "indicator": "2", "id": "fd403d6f-e2d3-4b71-b9b9-d3f7b9420b9c"},
    {"name": "2", "indicator": "2", "id": "d87c8bfa-47f2-4250-91ac-8739a982c450"},
    {"name": "3", "indicator": "2", "id": "ad552b8a-4fe5-4f0c-8563-4b8ab89c912e"},

    {"name": "1", "indicator": "3", "id": "e015514f-7c59-4915-968a-c3830c908b67"},
    {"name": "3", "indicator": "3", "id": "39bacb93-e32c-4960-8f5e-515f1d98af04"},
]

PARAMS = {
    "page": 1,
    "per_page": 50,
    "sorting": "newest"
}


# =========================================================
# ✅ PROCESS FUNCTION (ONLY SAFE CHANGE)
# =========================================================

def process_webhook(webhook):
    try:
        name = NAME_MAP.get(webhook["name"], "unknown")
        indicator = INDICATOR_MAP.get(webhook["indicator"], "unknown")

        if name == "unknown" or indicator == "unknown":
            log_error(f"❌ Invalid mapping: {webhook}")
            return

        url = f"{BASE_URL}{webhook['id']}/requests"

    except Exception as e:
        log_error(f"❌ Mapping error: {e} | webhook={webhook}")
        return

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=PARAMS, timeout=10)
            response.raise_for_status()

            try:
                data = response.json()
            except Exception:
                log_error(
                    f"❌ Invalid JSON ({name}) [{indicator}] | Status: {response.status_code}"
                )
                return

            inserted_count = 0

            for item in data.get("data", []):
                doc = {
                    "uuid": item.get("uuid"),  # 🔑 KEY FIELD
                    "name": name,
                    "indicator": indicator,
                    "time": item.get("created_at"),
                    "content": item.get("content")
                }

                try:
                    collection.insert_one(doc)
                    inserted_count += 1

                    # 📩 Telegram
                    try:
                        msg = format_telegram_message(doc)
                        send_telegram_message(msg)
                    except Exception as tg_err:
                        log_error(f"📩 Telegram failed: {tg_err}")

                except DuplicateKeyError:
                    # ✅ NEW: skip duplicates silently
                    continue

                except Exception as e:
                    log_error(f"❌ Insert error: {e}")

            log_info(f"✅ {name} [{indicator}]: Inserted {inserted_count}")
            return

        except requests.exceptions.Timeout:
            log_error(f"⏳ Timeout ({name}) [{indicator}] attempt {attempt}/{MAX_RETRIES}")

        except requests.exceptions.ConnectionError:
            log_error(f"🌐 Connection error ({name}) [{indicator}] attempt {attempt}/{MAX_RETRIES}")

        except requests.exceptions.HTTPError as e:
            log_error(f"⚠️ HTTP error ({name}) [{indicator}]: {e}")
            break

        except Exception as e:
            log_error(f"❌ Unexpected error ({name}) [{indicator}]: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)

    log_error(f"🚫 Failed after {MAX_RETRIES} retries: {name} [{indicator}]")


# =========================================================
# ✅ MAIN LOOP (UNCHANGED)
# =========================================================

def run_fetcher():
    while True:
        try:
            log_debug("🔁 Starting fetch cycle...")

            with ThreadPoolExecutor(max_workers=len(WEBHOOKS)) as executor:
                executor.map(process_webhook, WEBHOOKS)

            log_debug("✅ Fetch cycle completed")

        except Exception as e:
            log_error(f"🔥 Critical error in fetch loop: {e}")

        time.sleep(FETCH_INTERVAL)