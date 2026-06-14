"""
Instrument Lookup
─────────────────
Downloads Angel One's NFO instrument master CSV and finds
the correct symbol_token for any NIFTY option strike.

Angel One publishes: https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
"""

import json
import logging
import requests
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST    = ZoneInfo("Asia/Kolkata")

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
_cache: list = []


def _fetch() -> list:
    global _cache
    if _cache:
        return _cache
    logger.info("Downloading Angel One instrument master...")
    r = requests.get(MASTER_URL, timeout=30)
    r.raise_for_status()
    _cache = r.json()
    logger.info(f"Loaded {len(_cache)} instruments")
    return _cache


def find_option(
    underlying: str = "NIFTY",
    strike: float = 0,
    option_type: str = "CE",    # "CE" or "PE"
    expiry_date: str = "",       # "13JUN2024" format — blank = nearest expiry
) -> Optional[dict]:
    """
    Find NIFTY option instrument.
    Returns {symbol_token, trading_symbol, expiry, strike, lotsize}
    """
    instruments = _fetch()
    today = datetime.now(IST).date()
    option_type = option_type.upper()
    underlying  = underlying.upper()

    matches = []
    for inst in instruments:
        if inst.get("exch_seg") != "NFO":
            continue
        sym = inst.get("symbol", "").upper()
        # Must match underlying + option type
        if not sym.startswith(underlying):
            continue
        if option_type not in sym:
            continue
        # Parse expiry from symbol e.g. NIFTY13JUN2426000CE
        try:
            # Angel format: NIFTY{DDMMMYY}{STRIKE}{TYPE}
            expiry_str = sym[len(underlying):len(underlying)+7]  # e.g. 13JUN24
            expiry_full = datetime.strptime(expiry_str, "%d%b%y").date()
            if expiry_full < today:
                continue
        except Exception:
            continue

        inst_strike = float(inst.get("strike", 0)) / 100   # Angel stores strike * 100
        matches.append({
            "symbol_token":   inst["token"],
            "trading_symbol": inst["symbol"],
            "expiry":         expiry_full.isoformat(),
            "strike":         inst_strike,
            "lotsize":        int(inst.get("lotsize", 25)),
            "name":           inst.get("name", ""),
        })

    if not matches:
        logger.warning(f"No {underlying} {option_type} options found")
        return None

    # Filter by strike if provided
    if strike:
        exact = [m for m in matches if m["strike"] == strike]
        if exact:
            matches = exact

    # Filter by expiry if provided
    if expiry_date:
        try:
            exp = datetime.strptime(expiry_date, "%d%b%Y").date()
            filtered = [m for m in matches if m["expiry"] == exp.isoformat()]
            if filtered:
                matches = filtered
        except Exception:
            pass

    # Sort by expiry (nearest first), then by strike
    matches.sort(key=lambda x: (x["expiry"], x["strike"]))
    return matches[0]


def search_options(
    underlying: str = "NIFTY",
    option_type: str = "CE",
    limit: int = 20,
) -> list:
    """List all active NIFTY CE or PE options (nearest expiry first)."""
    instruments = _fetch()
    today = datetime.now(IST).date()
    option_type = option_type.upper()
    results = []

    for inst in instruments:
        if inst.get("exch_seg") != "NFO":
            continue
        sym = inst.get("symbol", "").upper()
        if not sym.startswith(underlying.upper()) or option_type not in sym:
            continue
        try:
            expiry_str  = sym[len(underlying):len(underlying)+7]
            expiry_full = datetime.strptime(expiry_str, "%d%b%y").date()
            if expiry_full < today:
                continue
        except Exception:
            continue

        results.append({
            "symbol_token":   inst["token"],
            "trading_symbol": inst["symbol"],
            "expiry":         expiry_full.isoformat(),
            "strike":         float(inst.get("strike", 0)) / 100,
            "lotsize":        int(inst.get("lotsize", 25)),
        })

    results.sort(key=lambda x: (x["expiry"], x["strike"]))
    return results[:limit]


def clear_cache():
    global _cache
    _cache = []
