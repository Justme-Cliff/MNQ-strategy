"""
Price feed — accurate NQ anchor (yfinance 1-min bar) tightened in real time with
the ^NDX index stream.

The problem it solves
  The NQ=F 1-minute bar from yfinance is the right instrument but is delivered
  1-2 minutes late, so on a fast move the displayed price lags the real market by
  20-30+ points (you saw this live on a CPI day). That lag is what makes signals
  feel "late."

The fix — anchor + real-time delta
  ^NDX (the Nasdaq-100 index) streams in real time with NO CME embargo. We do NOT
  use its absolute level (the cost-of-carry basis is unreliable, ~150pt off). We
  use only its *change* since the timestamp of the last accurate NQ bar:

      live_nq = anchor_nq + (ndx_now - ndx_at_anchor_time)

  Because only the ^NDX delta is used, the basis cancels out, and the lag in the
  NQ bar is bridged by the live index move. Residual error is a couple points of
  index-vs-future tracking — good for display + alert timing, not a substitute
  for the broker's exact fill price.

Safety
  Every layer degrades gracefully. If the WS is down, ^NDX is stale, the market is
  outside the cash session (^NDX only trades 9:30-16:00 ET), or the adjustment
  looks insane, we fall back to the raw NQ bar — i.e. exactly the old behavior.
  Disable entirely with ISOGENY_NDX_TRACK=0.

  Signals are still computed from completed 5-min bars elsewhere; this feed only
  drives the live status price and the ARMED/WATCH alert timing.
"""
from __future__ import annotations
import os
import threading
import time
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")

# Real-time ^NDX delta tracking — on by default, ISOGENY_NDX_TRACK=0 to disable.
ENABLE_NDX   = os.environ.get("ISOGENY_NDX_TRACK", "1").lower() in ("1", "true", "yes", "on")
NDX_MAX_AGE  = 10.0    # s — if the index print is older than this, don't trust the delta
ADJ_SANITY   = 150.0   # pts — reject an absurd delta (bad anchor match) and fall back to raw


def _is_cash_session(now: datetime) -> bool:
    """^NDX only updates during the RTH cash session (Mon-Fri 9:30-16:00 ET)."""
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= mins < 16 * 60


class FastPriceFeed:
    """NQ 1-min anchor, tightened in real time by the ^NDX delta when available."""

    def __init__(self, interval: float = 10.0):
        self._interval = max(interval, 5.0)
        self._anchor_nq:   float | None    = None   # last accurate NQ bar close
        self._anchor_ndx:  float | None    = None   # ^NDX at that bar's close time
        self._updated:     datetime | None = None
        self._last_synced  = False
        self._lock     = threading.Lock()
        self._running  = True
        self.source    = "NQ1m+NDX" if ENABLE_NDX else "NQ1m"

        # Real-time ^NDX stream (best-effort — degrades to raw NQ if unavailable)
        self._ndx = None
        if ENABLE_NDX:
            try:
                from yahoo_ws_feed import YahooWsFeed
                self._ndx = YahooWsFeed()
            except Exception as e:
                log.warning("ndx stream unavailable, raw NQ only: %s", e)
                self._ndx = None

        self._fetch_once()
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    # ── Public API ───────────────────────────────────────────────────────────
    @property
    def price(self) -> float | None:
        """Composite live NQ: anchor + ^NDX delta when trustworthy, else raw anchor."""
        with self._lock:
            anchor = self._anchor_nq
            a_ndx  = self._anchor_ndx
        if anchor is None:
            return None
        if self._ndx is None or a_ndx is None:
            self._last_synced = False
            return anchor
        try:
            now = datetime.now(tz=EST)
            if not _is_cash_session(now):
                self._last_synced = False
                return anchor
            ndx_now = self._ndx.ndx
            if ndx_now is None or self._ndx.age_seconds > NDX_MAX_AGE:
                self._last_synced = False
                return anchor
            adj = ndx_now - a_ndx
            if abs(adj) > ADJ_SANITY:
                self._last_synced = False
                return anchor
            self._last_synced = True
            return anchor + adj
        except Exception:
            self._last_synced = False
            return anchor

    @property
    def raw_price(self) -> float | None:
        """The unadjusted NQ 1-min anchor (what the old feed returned)."""
        with self._lock:
            return self._anchor_nq

    @property
    def synced(self) -> bool:
        """True if the last price read was tightened by a live ^NDX delta."""
        return self._last_synced

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
        if self._ndx is not None:
            try:
                self._ndx.stop()
            except Exception:
                pass

    # ── Internals ──────────────────────────────────────────────────────────────
    def _fetch_once(self) -> None:
        try:
            df = yf.download("NQ=F", period="1d", interval="1m",
                             auto_adjust=True, progress=False)
            if df is not None and not df.empty:
                close_col = df["Close"]
                if hasattr(close_col.iloc[-1], "__len__"):
                    close_col = close_col.iloc[:, 0]
                p = float(close_col.iloc[-1])
                if p and p > 1000:
                    # Timestamp of this bar's CLOSE (yfinance index = bar start)
                    bar_ts = df.index[-1]
                    try:
                        bar_ts = bar_ts.tz_convert(EST) if bar_ts.tzinfo else bar_ts.tz_localize("UTC").tz_convert(EST)
                    except Exception:
                        bar_ts = datetime.now(tz=EST)
                    close_time = bar_ts.to_pydatetime() + timedelta(seconds=60)
                    a_ndx = None
                    if self._ndx is not None:
                        try:
                            a_ndx = self._ndx.ndx_at(close_time)
                        except Exception:
                            a_ndx = None
                    with self._lock:
                        self._anchor_nq  = p
                        self._anchor_ndx = a_ndx
                        self._updated    = datetime.now(tz=EST)
            else:
                p = yf.Ticker("NQ=F").fast_info.last_price
                if p and p > 1000:
                    with self._lock:
                        self._anchor_nq  = float(p)
                        self._anchor_ndx = None
                        self._updated    = datetime.now(tz=EST)
        except Exception as e:
            log.debug("price fetch: %s", e)

    def _loop(self):
        while self._running:
            time.sleep(self._interval)
            self._fetch_once()


# Keep HybridFeed name so monitor.py import doesn't break
HybridFeed = FastPriceFeed

_feed = None


def get_feed() -> FastPriceFeed:
    global _feed
    if _feed is not None:
        return _feed
    _feed = FastPriceFeed(interval=10.0)
    return _feed


def get_price() -> float | None:
    return get_feed().price
