"""
Angel One SmartAPI Client
─────────────────────────
Handles:
  - Daily JWT token generation using TOTP (no manual login needed)
  - Auto-renewal when token expires at midnight
  - Order placement for NSE F&O (NIFTY options)
  - Position fetch, order book, funds

SmartAPI Docs: https://smartapi.angelbroking.com/docs
TOTP: Angel One → My Profile → Enable TOTP → save the secret key
"""

import os
import time
import hmac
import struct
import hashlib
import base64
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://apiconnect.angelbroking.com"


# ── Pure-Python TOTP (no pyotp dependency) ───────────────────────────────────
def _totp(secret: str) -> str:
    """Generate current 6-digit TOTP from base32 secret."""
    if not secret:
        raise ValueError("ANGEL_TOTP_SECRET is empty — set it in Railway Variables")

    # Clean secret — remove spaces, dashes, equals, quotes
    secret = secret.upper().strip().replace(" ", "").replace("-", "").replace("=", "").replace("'","").replace('"',"")

    # Validate characters (Base32 uses A-Z and 2-7 only)
    invalid = set(secret) - set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    if invalid:
        raise ValueError(
            f"ANGEL_TOTP_SECRET contains invalid Base32 characters: {invalid}. "
            f"Valid chars are A-Z and 2-7 only. Got: {secret!r}"
        )

    # Base32 valid unpadded lengths per group: 2, 4, 5, 7, 0(=8)
    pad_map = {0:0, 2:6, 4:4, 5:3, 7:1}
    remainder = len(secret) % 8
    if remainder not in pad_map:
        secret = secret[:-1]   # trim 1 char to reach valid length
        remainder = len(secret) % 8
    secret = secret + "=" * pad_map.get(remainder, 0)

    try:
        key = base64.b32decode(secret)
    except Exception as e:
        raise ValueError(
            f"ANGEL_TOTP_SECRET decode failed: {e}. "
            f"Check Railway Variables — the secret must be the Base32 string "
            f"shown under 'Can\'t scan QR? Enter manually' in Angel One TOTP setup."
        )
    counter  = struct.pack(">Q", int(time.time()) // 30)
    mac      = hmac.new(key, counter, hashlib.sha1).digest()
    offset   = mac[-1] & 0x0F
    code     = struct.unpack(">I", mac[offset:offset+4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


class AngelClient:

    def __init__(self):
        self.client_id   = os.environ["ANGEL_CLIENT_ID"]    # Angel One login ID
        self.password    = os.environ["ANGEL_PASSWORD"]      # Angel One password
        self.totp_secret = os.environ["ANGEL_TOTP_SECRET"]  # Base32 TOTP secret
        self.api_key     = os.environ["ANGEL_API_KEY"]       # SmartAPI key

        self.jwt_token   = ""
        self.refresh_token = ""
        self.token_date  = ""   # date string when token was generated (IST)

        self.session     = requests.Session()
        self.session.headers.update({
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "X-UserType":    "USER",
            "X-SourceID":    "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress":  "00:00:00:00:00:00",
            "X-PrivateKey":  self.api_key,
        })

        # Auto-login on startup — catch errors so server still boots
        try:
            self.ensure_token()
        except Exception as e:
            logger.error(f"Startup login failed: {e}")
            logger.warning("Server will start without a token — fix credentials and call /refresh_token")

    # ── Token management ──────────────────────────────────────────────────────

    def ensure_token(self):
        """
        Generate a fresh JWT if:
        - No token yet, OR
        - Token was generated on a previous IST date (expired at midnight)
        """
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        if self.jwt_token and self.token_date == today_ist:
            return   # token is fresh

        logger.info(f"Generating new SmartAPI token for {today_ist}")
        self._login()

    def _login(self):
        """Login with clientcode + password + TOTP → get JWT."""
        totp_code = _totp(self.totp_secret)
        logger.info(f"TOTP generated: {totp_code}")

        payload = {
            "clientcode": self.client_id,
            "password":   self.password,
            "totp":       totp_code,
        }
        r = self.session.post(f"{BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword",
                              json=payload)
        logger.info(f"Login response [{r.status_code}]: {r.text[:200]}")
        r.raise_for_status()
        data = r.json()

        if not data.get("status"):
            raise RuntimeError(f"Login failed: {data.get('message', data)}")

        self.jwt_token     = data["data"]["jwtToken"]
        self.refresh_token = data["data"]["refreshToken"]
        self.token_date    = datetime.now(IST).strftime("%Y-%m-%d")
        self.session.headers["Authorization"] = f"Bearer {self.jwt_token}"
        logger.info("SmartAPI login successful ✅")

    def _refresh(self):
        """Try refreshing token before falling back to full re-login."""
        try:
            r = self.session.post(
                f"{BASE_URL}/rest/auth/angelbroking/jwt/v1/generateTokens",
                json={"refreshToken": self.refresh_token}
            )
            if r.ok and r.json().get("status"):
                self.jwt_token = r.json()["data"]["jwtToken"]
                self.session.headers["Authorization"] = f"Bearer {self.jwt_token}"
                self.token_date = datetime.now(IST).strftime("%Y-%m-%d")
                logger.info("Token refreshed ✅")
                return True
        except Exception as e:
            logger.warning(f"Refresh failed: {e}")
        return False

    def _call(self, method: str, url: str, **kwargs):
        """Make API call, auto-renew token on 401."""
        self.ensure_token()
        r = getattr(self.session, method)(url, **kwargs)
        if r.status_code == 401:
            logger.warning("401 received — attempting token refresh")
            if not self._refresh():
                self._login()
            r = getattr(self.session, method)(url, **kwargs)
        return r

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol_token: str,     # e.g. "35003"  from instrument master
        trading_symbol: str,   # e.g. "NIFTY13JUN2426000CE"
        transaction_type: str, # "BUY" or "SELL"
        quantity: int,
        exchange: str = "NFO",
        order_type: str = "MARKET",
        product_type: str = "INTRADAY",
        price: float = 0,
        trigger_price: float = 0,
    ) -> dict:
        payload = {
            "variety":          "NORMAL",
            "tradingsymbol":    trading_symbol,
            "symboltoken":      symbol_token,
            "transactiontype":  transaction_type,
            "exchange":         exchange,
            "ordertype":        order_type,
            "producttype":      product_type,
            "duration":         "DAY",
            "price":            str(price),
            "squareoff":        "0",
            "stoploss":         "0",
            "quantity":         str(quantity),
            "triggerprice":     str(trigger_price),
        }
        logger.info(f"Placing {transaction_type} {quantity} x {trading_symbol}")
        r = self._call("post",
                       f"{BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                       json=payload)
        logger.info(f"Order response [{r.status_code}]: {r.text}")
        r.raise_for_status()
        return r.json()

    def get_ltp(self, exchange: str, trading_symbol: str, symbol_token: str) -> float:
        """Get last traded price for an instrument."""
        payload = {
            "exchange":      exchange,
            "tradingsymbol": trading_symbol,
            "symboltoken":   symbol_token,
        }
        r = self._call("post",
                       f"{BASE_URL}/rest/secure/angelbroking/order/v1/getLtpData",
                       json=payload)
        r.raise_for_status()
        data = r.json()
        return float(data["data"]["ltp"])

    def get_positions(self) -> list:
        r = self._call("get",
                       f"{BASE_URL}/rest/secure/angelbroking/order/v1/getPosition")
        r.raise_for_status()
        return r.json().get("data", []) or []

    def get_order_book(self) -> list:
        r = self._call("get",
                       f"{BASE_URL}/rest/secure/angelbroking/order/v1/getOrderBook")
        r.raise_for_status()
        return r.json().get("data", []) or []

    def get_funds(self) -> dict:
        r = self._call("get",
                       f"{BASE_URL}/rest/secure/angelbroking/user/v1/getRMS")
        r.raise_for_status()
        return r.json().get("data", {}) or {}

    def search_scrip(self, exchange: str, query: str) -> list:
        """Search for instrument by name."""
        r = self._call("post",
                       f"{BASE_URL}/rest/secure/angelbroking/order/v1/searchScrip",
                       json={"exchange": exchange, "searchscrip": query})
        r.raise_for_status()
        return r.json().get("data", []) or []
