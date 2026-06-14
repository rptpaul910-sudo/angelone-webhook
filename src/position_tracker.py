"""
Position Tracker
────────────────
Tracks the current open option position in memory and JSON log.
Prevents duplicate orders and computes PnL on close.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST    = ZoneInfo("Asia/Kolkata")
LOG    = Path("logs/trades.json")
LOG.parent.mkdir(parents=True, exist_ok=True)


class PositionTracker:

    def __init__(self):
        self.position      = "FLAT"   # "FLAT" | "LONG"
        self.entry_price   = 0.0
        self.entry_time    = ""
        self.symbol        = ""
        self.symbol_token  = ""
        self.quantity      = 0
        self.today_pnl     = 0.0
        self.dry_run       = os.environ.get("DRY_RUN", "true").lower() == "true"

    def on_buy(self, symbol: str, token: str, price: float, qty: int):
        self.position     = "LONG"
        self.entry_price  = price
        self.entry_time   = datetime.now(IST).isoformat()
        self.symbol       = symbol
        self.symbol_token = token
        self.quantity     = qty
        self._log("BUY", price, qty, 0)
        logger.info(f"Position opened: LONG {qty} x {symbol} @ {price}")

    def on_sell(self, price: float) -> float:
        pnl = round((price - self.entry_price) * self.quantity, 2)
        self.today_pnl += pnl
        self._log("SELL", price, self.quantity, pnl)
        logger.info(
            f"Position closed: {self.symbol} @ {price} | "
            f"entry={self.entry_price} PnL=₹{pnl} | Today=₹{self.today_pnl}"
        )
        self.position    = "FLAT"
        self.entry_price = 0.0
        self.quantity    = 0
        return pnl

    def _log(self, side: str, price: float, qty: int, pnl: float):
        record = {
            "time":     datetime.now(IST).isoformat(),
            "side":     side,
            "symbol":   self.symbol,
            "token":    self.symbol_token,
            "price":    price,
            "quantity": qty,
            "pnl":      pnl,
            "dry_run":  self.dry_run,
        }
        try:
            trades = json.loads(LOG.read_text()) if LOG.exists() else []
            trades.append(record)
            LOG.write_text(json.dumps(trades, indent=2))
        except Exception as e:
            logger.error(f"Trade log error: {e}")

    def status(self) -> dict:
        return {
            "position":    self.position,
            "symbol":      self.symbol,
            "token":       self.symbol_token,
            "entry_price": self.entry_price,
            "entry_time":  self.entry_time,
            "quantity":    self.quantity,
            "today_pnl":   self.today_pnl,
            "dry_run":     self.dry_run,
        }

    def today_trades(self) -> list:
        try:
            if not LOG.exists():
                return []
            today = datetime.now(IST).strftime("%Y-%m-%d")
            return [t for t in json.loads(LOG.read_text())
                    if t["time"].startswith(today)]
        except Exception:
            return []
