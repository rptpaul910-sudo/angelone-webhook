"""
Instrument Lookup — Angel One SmartAPI
───────────────────────────────────────
Correct field names from OpenAPIScripMaster.json:
  token          → symbol_token  (string e.g. "37743")
  symbol         → trading_symbol (e.g. "NIFTY19JUN2523500CE")
  name           → underlying name (e.g. "NIFTY")
  expiry         → string "19JUN2025"
  strike         → strike * 100  (e.g. 23500 stored as "2350000.000000")
  lotsize        → string "75"
  instrumenttype → "OPTIDX" for index options, "OPTSTK" for stock options
  exch_seg       → "NFO"
  tick_size      → "5.000000"

Strike division: actual_strike = float(strike) / 100
Expiry format  : "19JUN2025" → parsed with %d%b%Y
"""

import json, logging, requests
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def get_nearest_tuesday_expiry() -> str:
    """
    NIFTY weekly options expire every Tuesday.
    Returns nearest upcoming Tuesday as 'DDMONYYYY' e.g. '24JUN2025'.
    If today is Tuesday and market is still open (before 3:30 PM IST), return today.
    Otherwise return next Tuesday.
    """
    now   = datetime.now(IST)
    today = now.date()

    # weekday(): Monday=0 ... Tuesday=1 ... Sunday=6
    days_to_tuesday = (1 - today.weekday()) % 7

    if days_to_tuesday == 0:
        # Today is Tuesday
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now > market_close:
            days_to_tuesday = 7   # this week's expiry passed, go to next Tuesday
    
    nearest = today + timedelta(days=days_to_tuesday)
    result  = nearest.strftime("%d%b%Y").upper()
    logger.info(f"Nearest Tuesday expiry: {result}")
    return result


def get_next_tuesday_expiries(count: int = 4) -> list:
    """Return next N Tuesday expiry dates as list of 'DDMONYYYY' strings."""
    now   = datetime.now(IST)
    today = now.date()
    days_to_tuesday = (1 - today.weekday()) % 7
    if days_to_tuesday == 0:
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now > market_close:
            days_to_tuesday = 7
    expiries = []
    for i in range(count):
        d = today + timedelta(days=days_to_tuesday + i * 7)
        expiries.append(d.strftime("%d%b%Y").upper())
    return expiries

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
_cache: list = []


def _fetch() -> list:
    global _cache
    if _cache:
        return _cache
    logger.info("Downloading Angel One instrument master...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    r = requests.get(MASTER_URL, headers=headers, timeout=30)
    r.raise_for_status()
    _cache = r.json()
    logger.info(f"Loaded {len(_cache)} instruments")
    return _cache


def _parse_expiry(expiry_str: str) -> Optional[datetime]:
    """Parse Angel One expiry string e.g. '19JUN2025' → date object."""
    if not expiry_str:
        return None
    for fmt in ("%d%b%Y", "%d%b%y"):
        try:
            return datetime.strptime(expiry_str.strip().upper(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_strike(strike_str) -> float:
    """Angel One stores strike * 100. e.g. 23500 → '2350000.000000'"""
    try:
        return float(strike_str) / 100
    except (ValueError, TypeError):
        return 0.0


def search_options(
    underlying: str = "NIFTY",
    option_type: str = "CE",
    strike: float = 0,
    limit: int = 30,
) -> list:
    """
    Search active NIFTY/BANKNIFTY options from Angel One master.
    Returns list sorted by expiry then strike.
    """
    instruments = _fetch()
    today = datetime.now(IST).date()
    option_type = option_type.upper()
    underlying  = underlying.upper()
    results = []

    for inst in instruments:
        # Filter: must be NFO + index option type
        if inst.get("exch_seg") != "NFO":
            continue
        itype = inst.get("instrumenttype", "").upper()
        if itype not in ("OPTIDX", "OPTSTK"):
            continue

        # Must match underlying name
        if inst.get("name", "").upper() != underlying:
            continue

        # Symbol must end with CE or PE
        sym = inst.get("symbol", "")
        if not sym.upper().endswith(option_type):
            continue

        # Parse and validate expiry
        expiry = _parse_expiry(inst.get("expiry", ""))
        if not expiry or expiry < today:
            continue

        actual_strike = _parse_strike(inst.get("strike", 0))

        # Filter by strike if provided
        if strike and abs(actual_strike - strike) > 0.5:
            continue

        results.append({
            "symbol_token":   str(inst.get("token", "")),
            "trading_symbol": sym,
            "name":           inst.get("name", ""),
            "expiry":         expiry.strftime("%Y-%m-%d"),
            "expiry_display": inst.get("expiry", ""),   # original e.g. "19JUN2025"
            "strike":         actual_strike,
            "lotsize":        int(inst.get("lotsize", 25)),
            "option_type":    option_type,
            "exchange":       "NFO",
        })

    results.sort(key=lambda x: (x["expiry"], x["strike"]))
    return results[:limit]


def find_option(
    underlying: str = "NIFTY",
    strike: float = 0,
    option_type: str = "CE",
    expiry_str: str = "",     # e.g. "19JUN2025" — blank = nearest Tuesday expiry
) -> Optional[dict]:
    """
    Find the best matching option contract.
    Defaults to nearest Tuesday expiry for NIFTY weekly options.
    """
    results = search_options(underlying=underlying, option_type=option_type,
                             strike=strike, limit=200)
    if not results:
        logger.warning(f"No {underlying} {option_type} options found for strike={strike}")
        return None

    # Use specified expiry or auto-detect nearest Tuesday
    target_expiry_str = expiry_str or get_nearest_tuesday_expiry()
    exp_date = _parse_expiry(target_expiry_str)

    if exp_date:
        filtered = [r for r in results if r["expiry"] == exp_date.strftime("%Y-%m-%d")]
        if filtered:
            logger.info(f"Filtered to expiry {target_expiry_str}: {len(filtered)} contracts")
            results = filtered
        else:
            logger.warning(
                f"No contracts found for expiry {target_expiry_str} — "
                f"falling back to nearest available expiry"
            )

    best = results[0]
    logger.info(
        f"Selected: {best['trading_symbol']} | token={best['symbol_token']} "
        f"| strike={best['strike']} | expiry={best['expiry_display']} | lot={best['lotsize']}"
    )
    return best


def clear_cache():
    global _cache
    _cache = []
    logger.info("Instrument cache cleared")
