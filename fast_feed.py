"""
Price feed — uses the most recent NQ=F 1-minute bar close from yfinance.

Why not the WebSocket?
  The Yahoo WS streams ^NDX (the index, not futures) and applies a
  cost-of-carry basis to estimate NQ. The basis drifts badly — producing
  prices 900-1000+ points off from the actual MNQ price. Unusable.

Why 1-minute bars instead of fast_info?
  yf.Ticker("NQ=F").fast_info.last_price is 15-min delayed (CME embargo).
  yf.download("NQ=F", period="1d", interval="1m") is also delayed but
  typically only 1-2 minutes behind — good enough for display purposes.
  The last 1-min bar close is accurate and at most 1-2 minutes old.

Important: signals come from 5-min bar close data, NOT from this feed.
  This feed is cosmetic only — it keeps the status line updated between
  bar closes so the trader can see roughly where NQ is.
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
    """
    Polls the latest NQ=F 1-minute bar every 10 seconds.
    Accurate to within 1-2 minutes — far better than the broken WS.
    """

    def __init__(self, interval: float = 10.0):
        self._interval = max(interval, 5.0)
        self._price:   float | None    = None
        self._updated: datetime | None = None
        self._lock     = threading.Lock()
        self._running  = True
        self.source    = "NQ1m"

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

    def is_stale(self, max_age: float = 60.0) -> bool:
        return self.age_seconds > max_age

    def stop(self):
        self._running = False

    def _fetch_once(self) -> None:
        try:
            # 1-minute bars — last close is 1-2 min old at most
            df = yf.download("NQ=F", period="1d", interval="1m",
                             auto_adjust=True, progress=False)
            if df is not None and not df.empty:
                close_col = df["Close"]
                # yfinance returns multi-level columns — flatten if needed
                if hasattr(close_col.iloc[-1], "__len__"):
                    close_col = close_col.iloc[:, 0]
                p = float(close_col.iloc[-1])
                if p and p > 1000:
                    with self._lock:
                        self._price   = p
                        self._updated = datetime.now(tz=EST)
            else:
                # Fallback: fast_info (15-min delayed but better than nothing)
                p = yf.Ticker("NQ=F").fast_info.last_price
                if p and p > 1000:
                    with self._lock:
                        self._price   = float(p)
                        self._updated = datetime.now(tz=EST)
        except Exception as e:
            log.debug("price fetch: %s", e)

    def _loop(self):
        while self._running:
            time.sleep(self._interval)
            self._fetch_once()


# Keep HybridFeed name so monitor.py import doesn't break
HybridFeed = FastPriceFeed


def get_feed() -> FastPriceFeed:
    global _feed
    if _feed is not None:
        return _feed
    _feed = FastPriceFeed(interval=10.0)
    return _feed


_feed = None


def get_price() -> float | None:
    return get_feed().price
