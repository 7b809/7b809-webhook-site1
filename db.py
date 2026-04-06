from pymongo import MongoClient, errors
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# ============================================
# 🔧 Config
# ============================================
TEST_LOG = os.getenv("TEST_LOG", "false").lower() == "true"

# ============================================
# 🪵 Logger setup
# ============================================
logger = logging.getLogger("db")
logger.setLevel(logging.DEBUG if TEST_LOG else logging.ERROR)

console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
console_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(console_handler)

# ============================================
# 🔌 Mongo Connection
# ============================================
client = None
db = None
collection = None

try:
    MONGO_URI = os.getenv("MONGO_URI")
    DB_NAME = os.getenv("DB_NAME")
    COLLECTION_NAME = os.getenv("COLLECTION_NAME")

    if not MONGO_URI or not DB_NAME or not COLLECTION_NAME:
        raise ValueError("Missing MongoDB environment variables")

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

    # 🔍 Test connection (better than server_info)
    client.admin.command("ping")

    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    if TEST_LOG:
        logger.debug("✅ MongoDB connected successfully")

except Exception as e:
    logger.critical(f"🔥 MongoDB connection failed: {e}")
    collection = None  # fallback safety

# ============================================
# 📊 Indexes (safe creation)
# ============================================
try:
    if collection is not None:  # ✅ FIXED

        # 🔒 Unique index for dedup
        collection.create_index("uuid", unique=True)

        # ⚡ Performance indexes
        collection.create_index([("name", 1)])
        collection.create_index([("indicator", 1)])
        collection.create_index([("time", -1)])

        if TEST_LOG:
            logger.debug("📊 Indexes ensured (uuid, name, indicator, time)")

    else:
        logger.warning("⚠️ Skipping index creation (collection is None)")

except errors.PyMongoError as e:
    logger.error(f"❌ Index creation error: {e}")