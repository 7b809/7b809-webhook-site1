import os
import json
import time
import requests
import logging
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo  

# ============================================
# 🔧 LOAD ENV
# ============================================
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MAX_FILE_SIZE = 49 * 1024 * 1024  # 49MB
MAX_RETRIES = 3

# ============================================
# 🪵 LOGGER SETUP
# ============================================
logger = logging.getLogger("backup")
logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

# Console
ch = logging.StreamHandler()
ch.setFormatter(formatter)

# File
fh = logging.FileHandler("backup.log")
fh.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(ch)
    logger.addHandler(fh)

# ============================================
# 🔌 CONNECT DB
# ============================================
def connect_db():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        logger.info("✅ MongoDB connected")
        return client[DB_NAME]
    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")
        return None


# ============================================
# 📦 FETCH DATA
# ============================================
def fetch_all_data(db):
    try:
        all_data = {}

        collections = db.list_collection_names()

        for col_name in collections:
            col = db[col_name]
            docs = list(col.find({}, {"_id": 0}))

            all_data[col_name] = docs

            logger.info(f"📊 Loaded {col_name} ({len(docs)} docs)")

        return all_data

    except Exception as e:
        logger.error(f"❌ Fetch error: {e}")
        return {}


# ============================================
# 📦 SPLIT INTO BATCHES
# ============================================
def split_into_batches(data):
    batches = []
    current_batch = []
    current_size = 0

    for key, value in data.items():
        item_json = json.dumps({key: value})
        item_size = len(item_json.encode("utf-8"))

        if current_size + item_size > MAX_FILE_SIZE:
            batches.append(current_batch)
            current_batch = []
            current_size = 0

        current_batch.append({key: value})
        current_size += item_size

    if current_batch:
        batches.append(current_batch)

    logger.info(f"📦 Total batches: {len(batches)}")

    return batches


# ============================================
# 📤 SEND TO TELEGRAM
# ============================================
def send_to_telegram(file_path):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(file_path, "rb") as f:
                response = requests.post(
                    url,
                    data={"chat_id": CHAT_ID},
                    files={"document": f},
                    timeout=30
                )

            if response.status_code == 200:
                logger.info(f"✅ Sent: {file_path}")
                return True
            else:
                logger.warning(f"⚠️ Attempt {attempt} failed: {response.text}")

        except Exception as e:
            logger.error(f"❌ Attempt {attempt} error: {e}")

        time.sleep(2)

    logger.error(f"🔥 Failed after {MAX_RETRIES}: {file_path}")
    return False


# ============================================
# 💾 SAVE + SEND
# ============================================
def process_and_send_batches(batches):
    all_success = True

    try:
        for i, batch in enumerate(batches, start=1):

            timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"backup_batch_{i}_{timestamp}.json"


            batch_dict = {}
            for item in batch:
                batch_dict.update(item)

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(batch_dict, f, indent=2)

            logger.info(f"💾 Saved: {filename}")

            success = send_to_telegram(filename)

            if not success:
                all_success = False
                logger.warning(f"⚠️ Failed sending {filename}")

        return all_success

    except Exception as e:
        logger.error(f"❌ Batch processing error: {e}")
        return False


# ============================================
# 🧹 DELETE DATA AFTER SUCCESS
# ============================================
def clear_database(db):
    try:
        collections = db.list_collection_names()

        for col_name in collections:
            col = db[col_name]
            result = col.delete_many({})

            logger.info(f"🧹 Cleared {col_name} ({result.deleted_count} docs)")

    except Exception as e:
        logger.error(f"❌ DB cleanup error: {e}")


# ============================================
# 🚀 MAIN
# ============================================
def main():
    db = connect_db()

    if db is None:
        return

    data = fetch_all_data(db)

    if not data:
        logger.warning("⚠️ No data found")
        return

    batches = split_into_batches(data)

    success = process_and_send_batches(batches)

    # ✅ DELETE ONLY IF SUCCESS
    if success:
        logger.info("🎉 All batches sent successfully → clearing DB")
        clear_database(db)
    else:
        logger.warning("⚠️ Backup incomplete → DB NOT cleared")


if __name__ == "__main__":
    main()