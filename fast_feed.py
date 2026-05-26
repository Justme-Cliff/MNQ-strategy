"""
Fast price feed — tries Tradovate WebSocket (real-time) first,
falls back to yfinance (15-min delayed) if Tradovate is unavailable.
"""
from __future__ import annotations
import threading
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


class FastPriceFeed:
    """yfinance fallback feed — polled every 0.5s."""

    def __init__(self, interval: float = 0.5):
        self._interval = max(interval, 0.5)
        self._price:   float | None    = None
        self._updated: datetime | None = None
        self._lock     = threading.Lock()
        self._running  = True
        self._errors   = 0

        self._fetch_once()
        t = threading.Thread(target=self._loop, daemon=True)
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

    def _fetch_once(self) -> None:
        try:
            p = yf.Ticker("NQ=F").fast_info.last_price
            if p and p > 0:
                with self._lock:
                    self._price   = float(p)
                    self._updated = datetime.now(tz=EST)
                    self._errors  = 0
        except Exception as e:
            with self._lock:
                self._errors += 1
            if self._errors % 20 == 1:
                log.warning("yfinance price error: %s", e)

    def _loop(self):
        while self._running:
            self._fetch_once()
            time.sleep(self._interval)


# ── Feed selector ─────────────────────────────────────────────────────────────

_feed = None


def get_feed():
    """Return Tradovate feed if credentials available, else yfinance."""
    global _feed
    if _feed is not None:
        return _feed

    # Try Yahoo Finance WebSocket (real-time ^NDX + basis = NQ price)
    try:
        from yahoo_ws_feed import YahooWsFeed
        yws = YahooWsFeed()
        for _ in range(20):          # wait up to 10s for first tick
            if yws.price:
                _feed = yws
                return _feed
            time.sleep(0.5)
        log.warning("Yahoo WS: no tick in 10s — falling back to yfinance")
        yws.stop()
    except Exception as e:
        log.warning("Yahoo WS unavailable (%s) — using yfinance", e)

    log.info("Using yfinance feed (15-min delayed)")
    _feed = FastPriceFeed(interval=0.5)
    return _feed


def get_price() -> float | None:
    return get_feed().price
