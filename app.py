from flask import Flask, render_template, request, jsonify
from db import collection
import os
from dotenv import load_dotenv
import logging
from telegram_msg import send_simple_telegram_message
# 🔽 NEW IMPORTS (for tunnel)
import subprocess
import shutil
import re,uuid
from threading import Thread
from datetime import datetime
import pytz

# 🌏 IST timezone
ist = pytz.timezone("Asia/Kolkata")

# ✅ NEW IMPORT
from config import Config

load_dotenv()

# 🔧 Config
TEST_LOG = os.getenv("TEST_LOG", "false").lower() == "true"
ENABLE_TUNNEL = os.getenv("ENABLE_TUNNEL", "false").lower() == "true"

# 🪵 Logger setup
logger = logging.getLogger("webhook_app")
logger.setLevel(logging.DEBUG if TEST_LOG else logging.ERROR)

console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
console_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(console_handler)

app = Flask(__name__)

# ============================================
# 🌐 Cloudflare Tunnel Helpers (UNCHANGED)
# ============================================
def install_cloudflared():
    if shutil.which("cloudflared"):
        logger.info("✅ cloudflared already installed")
        return

    env = get_environment()

    logger.info("⏳ Installing cloudflared...")

    if env == "windows":
        logger.info("❌ Skip install (manual needed for Windows)")
        return

    subprocess.run([
        "wget",
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
        "-O",
        "cloudflared"
    ], check=True)

    subprocess.run(["chmod", "+x", "cloudflared"], check=True)
    logger.info("✅ cloudflared installed")


def start_cloudflare_tunnel(local_port):
    logger.info(f"⏳ Starting tunnel on port {local_port}")

    cf_proc = subprocess.Popen(
        ["./cloudflared", "tunnel", "--url", f"http://localhost:{local_port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    public_url = None

    def read_output():
        nonlocal public_url
        for line in iter(cf_proc.stdout.readline, ""):
            if line:
                print(f"[Cloudflare] {line.strip()}")

                if "trycloudflare.com" in line and not public_url:
                    match = re.search(r"https://[0-9a-zA-Z\-]+\.trycloudflare\.com", line)
                    if match:
                        public_url = match.group(0)
                        logger.info(f"🌍 Public URL: {public_url}")

                        try:
                            msg = f"🚀 Webhook Server Live\n\n🌍 URL:\n{public_url}"
                            send_simple_telegram_message(msg)
                        except Exception as e:
                            logger.error(f"📩 Failed to send tunnel URL to Telegram: {e}")

    Thread(target=read_output, daemon=True).start()

    return cf_proc


def get_environment():
    if "COLAB_GPU" in os.environ:
        return "colab"
    elif os.name == "nt":
        return "windows"
    else:
        return "linux"


def should_enable_tunnel():
    env = get_environment()

    if env == "windows":
        logger.info("🪟 Windows → Tunnel OFF")
        return False

    if env == "colab":
        logger.info("📓 Colab → Tunnel ON (forced)")
        return True

    if ENABLE_TUNNEL:
        logger.info("🌐 Tunnel enabled via ENV")
        return True

    logger.info("🚫 Tunnel disabled")
    return False


# ============================================
# 🔥 WEBHOOK RECEIVER (CONFIG BASED)
# ============================================
@app.route("/webhook/<route_id>", methods=["POST"])
def webhook_handler(route_id):
    try:
        # ✅ RAW DATA
        raw_data = request.get_data(as_text=True)

        # ✅ SAFE JSON PARSE
        try:
            json_data = request.get_json(silent=True)
            if not isinstance(json_data, dict):
                json_data = {}
        except:
            json_data = {}

        # ✅ CONFIG
        NAME_MAP = Config.NAME_MAP
        INDICATOR_MAP = Config.INDICATOR_MAP
        route_map = Config.ROUTE_MAP

        mapping = route_map.get(route_id)

        if not mapping:
            logger.error(f"❌ Invalid route_id: {route_id}")
            return jsonify({"error": "Invalid route"}), 404

        name = NAME_MAP.get(mapping["name"], "unknown")
        indicator = INDICATOR_MAP.get(mapping["indicator"], "unknown")

        # 🌏 IST timezone
        ist = pytz.timezone("Asia/Kolkata")

        # ✅ fallback time logic
        incoming_time = json_data.get("time")

        if not incoming_time:
            incoming_time = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")

        doc = {
            "uuid": str(uuid.uuid4()),
            "name": name,
            "indicator": indicator,
            "time": incoming_time,
            "content": raw_data
        }

        # ✅ DB INSERT (SAFE)
        try:
            collection.insert_one(doc)
        except Exception as db_err:
            logger.error(f"❌ DB Insert Error: {db_err}")
            return jsonify({"error": "DB error"}), 500

        # ✅ TELEGRAM (SAFE)
        try:

            # ✅ Get bot token based on name
            bot_token = Config.BOT_TOKEN_MAP.get(name)

            if not bot_token:
                logger.error(f"❌ No bot token configured for {name}")
            else:
                msg = f"{name} | {indicator}\n{raw_data}"
                send_simple_telegram_message(msg, bot_token)
                

        except Exception as tg_err:
            logger.error(f"📩 Telegram error: {tg_err}")

        if TEST_LOG:
            logger.debug(f"✅ Webhook saved (raw): {doc}")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return jsonify({"error": "Internal error"}), 500
# ============================================
# 🔌 API Endpoint (UNCHANGED)
# ============================================
@app.route("/api/data")
def api_data():
    try:
        name = request.args.get("name")
        indicator = request.args.get("indicator")
        limit = request.args.get("limit", "100")

        try:
            limit = int(limit)
            if limit <= 0:
                limit = 100
        except:
            limit = 100

        query = {}

        if name:
            query["name"] = name

        if indicator:
            query["indicator"] = indicator

        data = list(
            collection.find(query)
            .sort("_id", -1)
            .limit(limit)
        )

        for d in data:
            d["_id"] = str(d["_id"])

        if TEST_LOG:
            logger.debug(
                f"[API] name={name}, indicator={indicator}, limit={limit}, returned={len(data)}"
            )

        return jsonify(data)

    except Exception as e:
        logger.error(f"❌ API Error: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


# ============================================
# 🌐 Dashboard Route (UNCHANGED)
# ============================================
@app.route("/")
def index():
    try:
        selected_name = request.args.get("name", "bitcoin")
        selected_indicator = request.args.get("indicator", "wavetrend")
        limit = request.args.get("limit", "100")

        try:
            limit = int(limit)
            if limit <= 0:
                limit = 100
        except:
            limit = 100

        query = {}

        if selected_name:
            query["name"] = selected_name

        if selected_indicator:
            query["indicator"] = selected_indicator

        data = list(
            collection.find(query)
            .sort("_id", -1)
            .limit(limit)
        )

    except Exception as e:
        logger.error(f"❌ UI Error: {e}")
        data = []
        selected_name = "bitcoin"
        selected_indicator = "wavetrend"
        limit = 100

    return render_template(
        "index.html",
        data=data,
        selected_name=selected_name,
        selected_indicator=selected_indicator,
        limit=limit
    )

# ============================================
# 🚀 MAIN (UPDATED - FETCHER REMOVED)
# ============================================
if __name__ == "__main__":

    try:
        # ❌ Removed fetcher (no longer needed)

        if should_enable_tunnel():
            install_cloudflared()
            start_cloudflare_tunnel(5000)

        port = int(os.environ.get("PORT", 5000))

        app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False
        )

    except Exception as e:
        logger.critical(f"🔥 Critical startup error: {e}")