"""
Real-time market data directly from Tradovate WebSocket.
No extra subscription needed — uses your existing login.
Builds 1-minute bars from live ticks.
"""
import asyncio
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import websockets

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


class TradovateFeed:
    BASE_URL   = "https://live.tradovateapi.com/v1"
    MD_WS_URL  = "wss://md.tradovateapi.com/v1/websocket"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.token: str | None = None
        self._bar: dict | None = None
        self._bar_minute: datetime | None = None
        self.on_bar_close = None   # callback(bar_dict)
        self.on_tick      = None   # callback(price, timestamp)
        self.last_price: float | None = None

    async def authenticate(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/auth/accesstokenrequest",
                    json={
                        "name":       self.username,
                        "password":   self.password,
                        "appId":      "TJRBot",
                        "appVersion": "1.0",
                        "cid":        0,
                        "sec":        "",
                        "deviceId":   "tjr-live-detector",
                    }
                )
                data = resp.json()
                if "accessToken" in data:
                    self.token = data["accessToken"]
                    return True
                log.warning("Tradovate auth failed: %s", data.get("errorText", data))
                return False
        except Exception as e:
            log.error("Auth error: %s", e)
            return False

    async def stream(self, symbol: str = "MNQM6"):
        """Connect and stream real-time quotes. Calls callbacks on each tick/bar."""
        async with websockets.connect(self.MD_WS_URL, ping_interval=20) as ws:
            # Authorize
            await ws.send(json.dumps({"op": "authorize", "id": 1, "params": {"token": self.token}}))
            await ws.recv()

            # Subscribe to real-time quotes
            await ws.send(json.dumps({
                "op":     "subscribe",
                "id":     2,
                "params": ["md/subscribeQuote", {"symbol": symbol}]
            }))

            async for raw in ws:
                try:
                    self._handle(raw)
                except Exception as e:
                    log.error("Feed error: %s", e)

    def _handle(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        if not isinstance(msg, dict) or msg.get("e") != "quotes":
            return

        for quote in msg.get("d", {}).get("quotes", []):
            trade = quote.get("entries", {}).get("Trade", {})
            if not trade or "price" not in trade:
                continue

            price  = float(trade["price"])
            volume = int(trade.get("size", 1))
            now    = datetime.now(tz=EST)
            self.last_price = price

            if self.on_tick:
                self.on_tick(price, now)

            self._update_bar(price, volume, now)

    def _update_bar(self, price: float, volume: int, now: datetime):
        minute = now.replace(second=0, microsecond=0)

        if self._bar_minute != minute:
            # Close old bar
            if self._bar and self.on_bar_close:
                self.on_bar_close(self._bar)
            # Open new bar
            self._bar = {
                "time": minute, "open": price, "high": price,
                "low": price, "close": price, "volume": volume
            }
            self._bar_minute = minute
        else:
            self._bar["high"]    = max(self._bar["high"], price)
            self._bar["low"]     = min(self._bar["low"],  price)
            self._bar["close"]   = price
            self._bar["volume"] += volume
