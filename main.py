"""
Angel One SmartAPI Webhook Server
Entry point — run with: python main.py
Railway runs this via Procfile.
"""

import os
import logging
import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")

class ISTFormatter(logging.Formatter):
    def converter(self, timestamp):
        return datetime.datetime.fromtimestamp(timestamp, tz=IST).timetuple()

os.makedirs("logs", exist_ok=True)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
fmt = ISTFormatter(
    fmt="%(asctime)s IST | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
sh = logging.StreamHandler();  sh.setFormatter(fmt)
fh = logging.FileHandler("logs/webhook.log", mode="a"); fh.setFormatter(fmt)
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), handlers=[sh, fh])

from src.app import app  # noqa: E402

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
