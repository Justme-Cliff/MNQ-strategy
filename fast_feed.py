"""
Fast price feed — Yahoo Finance WebSocket (^NDX + basis) with yfinance fallback.

Strategy: both feeds run simultaneously. WS is preferred whenever it has a fresh
price (age < 30s). yfinance covers the gap while WS is connecting pre-market.
Once WS gets its first tick, it takes over automatically — no restart needed.
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


class HybridFeed:
    """
    Runs Yahoo WS and yfinance simultaneously.
    Returns WS price when fresh (age < 30s), yfinance otherwise.
    WS takes over automatically once it connects — no restart needed.
    """

    def __init__(self):
        from yahoo_ws_feed import YahooWsFeed
        self._ws       = YahooWsFeed()
        self._fallback = FastPriceFeed(interval=0.5)
        self._ws_ever_connected = False
        self.source    = "hybrid"

    @property
    def price(self) -> float | None:
        ws_price = self._ws.price
        ws_age   = self._ws.age_seconds

        if ws_price and ws_age < 30:
            self._ws_ever_connected = True
            self.source = "^NDX+basis"
            return ws_price

        # WS not ready yet — use yfinance but keep WS running in background
        fb = self._fallback.price
        if not self._ws_ever_connected:
            self.source = "yfinance(delayed)"
        else:
            # WS was working but went stale — could be a gap (lunch, etc.)
            self.source = "yfinance(WS stale)"
        return fb

    @property
    def age_seconds(self) -> float:
        ws_age = self._ws.age_seconds
        if ws_age < 30:
            return ws_age
        return self._fallback.age_seconds

    def is_stale(self, max_age: float = 30.0) -> bool:
        return self.age_seconds > max_age

    @property
    def connected(self) -> bool:
        return self._ws.connected

    def stop(self):
        self._ws.stop()
        self._fallback.stop()


# ── Feed selector ─────────────────────────────────────────────────────────────

_feed = None


def get_feed() -> HybridFeed | FastPriceFeed:
    global _feed
    if _feed is not None:
        return _feed

    try:
        _feed = HybridFeed()
        log.info("HybridFeed started: WS + yfinance running simultaneously")
    except Exception as e:
        log.warning("HybridFeed failed (%s) — using yfinance only", e)
        _feed = FastPriceFeed(interval=0.5)

    return _feed


def get_price() -> float | None:
    return get_feed().price
