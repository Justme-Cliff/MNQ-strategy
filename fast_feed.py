"""
Fast price feed — background thread pre-fetches NQ price every 0.5s.
Main loop reads from cache instantly (zero wait, zero blocking).

Uses ticker.fast_info.last_price — real-time, NOT the 15-min delayed bars.
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
    def __init__(self, interval: float = 0.5):
        self._interval = interval
        self._price:   float | None    = None
        self._updated: datetime | None = None
        self._lock     = threading.Lock()
        self._running  = True
        self._errors   = 0
        self._ticker   = yf.Ticker("NQ=F")   # created once, reused forever

        self._fetch_once()   # warm up before starting background thread
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
            p = float(self._ticker.fast_info.last_price)
            if p and p > 0:
                with self._lock:
                    self._price   = p
                    self._updated = datetime.now(tz=EST)
                    self._errors  = 0
        except Exception as e:
            with self._lock:
                self._errors += 1
            if self._errors % 20 == 1:
                log.warning("Price fetch error: %s", e)

    def _loop(self):
        while self._running:
            self._fetch_once()
            time.sleep(self._interval)


_feed: FastPriceFeed | None = None

def get_feed() -> FastPriceFeed:
    global _feed
    if _feed is None:
        _feed = FastPriceFeed(interval=0.5)
    return _feed

def get_price() -> float | None:
    return get_feed().price
