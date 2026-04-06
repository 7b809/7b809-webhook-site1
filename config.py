import os
from dotenv import load_dotenv

load_dotenv()
class Config:
    NAME_MAP = {
        "1": "bitcoin",
        "2": "gift-nifty",
        "3": "nifty"
    }

    INDICATOR_MAP = {
        "1": "wavetrend",
        "2": "support-and-resistance",
        "3": "xm-indicator"
    }

    ROUTE_MAP = {
        "1": {"name": "1", "indicator": "1"},
        "2": {"name": "2", "indicator": "1"},
        "3": {"name": "3", "indicator": "1"},
        "4": {"name": "1", "indicator": "2"},
        "5": {"name": "2", "indicator": "2"},
        "6": {"name": "3", "indicator": "2"},
        "7": {"name": "1", "indicator": "3"},
        "8": {"name": "3", "indicator": "1"},
        "9": {"name": "3", "indicator": "3"},
    }

    # ✅ NEW: Bot token per name
    BOT_TOKEN_MAP = {
        "bitcoin": os.getenv("BOT_TOKEN_BITCOIN"),
        "gift-nifty": os.getenv("BOT_TOKEN_GIFT_NIFTY"),
        "nifty": os.getenv("BOT_TOKEN_NIFTY"),
    }