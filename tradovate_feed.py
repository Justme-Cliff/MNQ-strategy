"""
Real-time NQ price feed via Tradovate WebSocket.
Replaces yfinance for live price display — zero delay.
"""
from __future__ import annotations
import asyncio
import json
import os
import threading
import time
import logging
import requests
import websockets
from datetime import datetime, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")

DEMO     = os.getenv("TRADOVATE_DEMO", "true").lower() == "true"
BASE_URL = "https://demo.tradovateapi.com/v1" if DEMO else "https://live.tradovateapi.com/v1"
MD_WS    = ("wss://md-demo.tradovateapi.com/v1/websocket" if DEMO
            else "wss://md.tradovateapi.com/v1/websocket")


def _front_month_symbol() -> str:
    today = date.today()
    d = str(today.year)[-1]
    m = today.month
    if   m <= 3:  return f"NQH{d}"
    elif m <= 6:  return f"NQM{d}"
    elif m <= 9:  return f"NQU{d}"
    else:         return f"NQZ{d}"


def get_token() -> str | None:
    # Use raw browser-extracted token if available (bypasses CID/SEC requirement)
    raw = os.getenv("TRADOVATE_MD_TOKEN", "").strip()
    if raw:
        log.info("Tradovate: using browser token from .env")
        return raw

    try:
        resp = requests.post(f"{BASE_URL}/auth/accesstokenrequest", json={
            "name":       os.getenv("TRADOVATE_USERNAME", ""),
            "password":   os.getenv("TRADOVATE_PASSWORD", ""),
            "appId":      os.getenv("TRADOVATE_APP_ID", "TJRBot"),
            "appVersion": os.getenv("TRADOVATE_APP_VERSION", "1.0"),
            "cid":        int(os.getenv("TRADOVATE_CID", "0")),
            "sec":        os.getenv("TRADOVATE_SECRET", ""),
        }, timeout=10)
        data = resp.json()
        token = data.get("mdAccessToken") or data.get("accessToken")
        if token:
            log.info("Tradovate auth OK (%s)", "demo" if DEMO else "live")
        else:
            log.warning("Tradovate auth failed: %s", data.get("errorText", data))
        return token
    except Exception as e:
        log.warning("Tradovate auth error: %s", e)
        return None


class TradovatePriceFeed:
    """Real-time NQ price via Tradovate MD WebSocket."""

    def __init__(self):
        self._price:   float | None    = None
        self._updated: datetime | None = None
        self._lock     = threading.Lock()
        self._running  = True
        self._errors   = 0
        self._token:   str | None      = None
        self.symbol    = _front_month_symbol()
        self.connected = False

        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    @property
    def price(self) -> float | None:
        with self._lock:
            return self._price

    @property
    def age_seconds(self) -> float:
        with self._lock:
            if self._updated is None:
                return 999.0
            return (datetime.now(tz=EST) - self._updated).total_seconds()

    def is_stale(self, max_age: float = 10.0) -> bool:
        return self.age_seconds > max_age

    def stop(self):
        self._running = False

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while self._running:
            try:
                loop.run_until_complete(self._ws_loop())
            except Exception as e:
                self._errors += 1
                self.connected = False
                if self._errors % 3 == 1:
                    log.warning("Tradovate WS: %s — reconnecting in 5s", e)
                time.sleep(5)

    async def _ws_loop(self):
        if not self._token:
            self._token = get_token()
        if not self._token:
            raise RuntimeError("no token")

        async with websockets.connect(
            MD_WS,
            ping_interval=20,
            ping_timeout=10,
            open_timeout=10,
        ) as ws:
            # Authorize
            await ws.send(json.dumps({
                "url":  "authorize",
                "body": {"token": self._token},
            }))

            # Subscribe to NQ quotes
            await ws.send(json.dumps({
                "url":  "md/subscribeQuote",
                "body": {"symbol": self.symbol},
            }))

            self.connected = True
            log.info("Tradovate: subscribed %s real-time quotes", self.symbol)

            async for raw in ws:
                if not self._running:
                    break
                self._parse(raw)

        self.connected = False

    def _parse(self, raw: str):
        # SockJS envelope: a["..."] wraps JSON-encoded string
        # OR plain JSON array/object
        try:
            if raw.startswith('a['):
                inner = json.loads(raw[1:])   # strip leading 'a', parse the array
                for item in inner:
                    self._parse(item)          # items are JSON strings themselves
                return

            if isinstance(raw, str):
                data = json.loads(raw)
            else:
                data = raw

            if isinstance(data, list):
                for item in data:
                    self._parse(item)
                return

            event = data.get("e", "")
            if event not in ("md", ""):
                return

            quotes = data.get("d", {}).get("quotes", [])
            for q in quotes:
                entries = q.get("entries", {})
                for field in ("Trade", "Price", "BidPrice", "AskPrice"):
                    entry = entries.get(field, {})
                    p = entry.get("price") or entry.get("Price")
                    if p and float(p) > 1000:   # sanity check for NQ range
                        with self._lock:
                            self._price   = float(p)
                            self._updated = datetime.now(tz=EST)
                            self._errors  = 0
                        return
        except Exception:
            pass
