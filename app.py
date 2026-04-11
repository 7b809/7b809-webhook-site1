from flask import Flask, render_template, request, jsonify
from db import collection
import os
from dotenv import load_dotenv
import logging
from telegram_msg import send_telegram_message, format_telegram_message

import subprocess
import shutil
import re, uuid
from threading import Thread
from datetime import datetime
import pytz

ist = pytz.timezone("Asia/Kolkata")

from config import Config

load_dotenv()

TEST_LOG = os.getenv("TEST_LOG", "false").lower() == "true"
ENABLE_TUNNEL = os.getenv("ENABLE_TUNNEL", "false").lower() == "true"

logger = logging.getLogger("webhook_app")
logger.setLevel(logging.DEBUG if TEST_LOG else logging.ERROR)

console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
console_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(console_handler)

app = Flask(__name__)

# ===================== 🆕 PnL TRACKING =====================
last_trade = {}

def parse_wavetrend_message(message):
    try:
        parts = message.split("_")

        if len(parts) < 6:
            return None

        return {
            "old_type": parts[0],
            "old_action": parts[1],
            "new_type": parts[2],
            "new_action": parts[3],
            "price": float(parts[5])
        }

    except Exception as e:
        logger.error(f"❌ Parse error: {e}")
        return None


def calculate_pnl(name, parsed_data):
    try:
        global last_trade

        price = parsed_data["price"]

        if name in last_trade:
            entry_price = last_trade[name]["price"]

            if parsed_data["old_type"] == "pe":
                pnl = entry_price - price
            else:
                pnl = price - entry_price

            result = {
                "entry": entry_price,
                "exit": price,
                "pnl": round(pnl, 2)
            }

            last_trade[name] = parsed_data
            return result

        last_trade[name] = parsed_data
        return None

    except Exception as e:
        logger.error(f"❌ PnL error: {e}")
        return None

# ============================================
# 🆕 WEEKEND CHECK HELPER (ADDED)
# ============================================
def is_weekend_allowed():
    try:
        TEST_DAYS = os.getenv("TEST_DAYS", "false").lower() == "true"

        now_ist = datetime.now(ist)
        weekday = now_ist.weekday()  # Monday=0, Sunday=6

        if weekday in [5, 6]:
            return TEST_DAYS

        return True

    except Exception as e:
        logger.error(f"📅 Weekend check error: {e}")
        return True

# ============================================
# 🌐 Cloudflare Tunnel Helpers
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
                            send_telegram_message(msg)
                        except Exception as e:
                            logger.error(f"📩 Failed to send tunnel URL: {e}")

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
        return False

    if env == "colab":
        return True

    if ENABLE_TUNNEL:
        return True

    return False

# ============================================
# ⏱️ Time Check Helper
# ============================================
def is_within_time(route_id):
    try:
        config = Config.ALERT_TIME_CONFIG.get(route_id)

        if not config or not config.get("enabled"):
            return True

        now_ist = datetime.now(ist)

        start_dt = ist.localize(
            datetime.strptime(config["start"], "%H:%M").replace(
                year=now_ist.year,
                month=now_ist.month,
                day=now_ist.day
            )
        )

        end_dt = ist.localize(
            datetime.strptime(config["end"], "%H:%M").replace(
                year=now_ist.year,
                month=now_ist.month,
                day=now_ist.day
            )
        )

        return start_dt <= now_ist <= end_dt

    except Exception as e:
        logger.error(f"⏱️ Time check error: {e}")
        return True

# ============================================
# 🔥 WEBHOOK RECEIVER
# ============================================
@app.route("/webhook/<route_id>", methods=["POST"])
def webhook_handler(route_id):
    try:
        raw_data = request.get_data(as_text=True)

        try:
            json_data = request.get_json(silent=True)
            if not isinstance(json_data, dict):
                json_data = {}
        except:
            json_data = {}

        NAME_MAP = Config.NAME_MAP
        INDICATOR_MAP = Config.INDICATOR_MAP
        route_map = Config.ROUTE_MAP

        mapping = route_map.get(route_id)

        if not mapping:
            logger.error(f"❌ Invalid route_id: {route_id}")
            return jsonify({"error": "Invalid route"}), 404

        name = NAME_MAP.get(mapping["name"], "unknown")
        indicator = INDICATOR_MAP.get(mapping["indicator"], "unknown")

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

        try:
            collection.insert_one(doc)
        except Exception as db_err:
            logger.error(f"❌ DB Insert Error: {db_err}")
            return jsonify({"error": "DB error"}), 500

        try:
            doc_data = {
                "name": name,
                "indicator": indicator,
                "content": raw_data,
                "time": incoming_time
            }

            formatted_msg = format_telegram_message(doc_data)

            if not formatted_msg:
                return jsonify({"status": "skipped"}), 200

            if indicator == "wavetrend":
                parsed = parse_wavetrend_message(raw_data)

                if parsed:
                    pnl_data = calculate_pnl(name, parsed)

                    if pnl_data:
                        formatted_msg += (
                            f"\n\n💰 PnL Update\n"
                            f"Entry: {pnl_data['entry']}\n"
                            f"Exit: {pnl_data['exit']}\n"
                            f"P&L: {pnl_data['pnl']}"
                        )

            # 🆕 WEEKEND CHECK
            if not is_weekend_allowed():
                logger.info("📅 Skipped (Weekend Blocked)")
                return jsonify({"status": "skipped_weekend"}), 200

            # ✅ TIME FILTER
            if is_within_time(route_id):
                send_telegram_message(formatted_msg, name=name)
            else:
                logger.info(f"⏳ Skipped Telegram → route {route_id}")

        except Exception as tg_err:
            logger.error(f"📩 Telegram error: {tg_err}")

        if TEST_LOG:
            logger.debug(f"✅ Webhook saved (raw): {doc}")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return jsonify({"error": "Internal error"}), 500


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

        return jsonify(data)

    except Exception as e:
        logger.error(f"❌ API Error: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@app.route("/")
def index():
    name = request.args.get("name", "bitcoin")
    indicator = request.args.get("indicator", "wavetrend")
    limit = request.args.get("limit", 100)

    return render_template(
        "index.html",
        selected_name=name,
        selected_indicator=indicator,
        limit=limit
    )


if __name__ == "__main__":
    if should_enable_tunnel():
        install_cloudflared()
        start_cloudflare_tunnel(5000)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))