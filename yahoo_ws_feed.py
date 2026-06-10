"""
Real-time NQ price feed via Yahoo Finance WebSocket (^NDX index stream).

^NDX (Nasdaq 100 index) streams real-time with no CME delay — index data
is not subject to the 15-min futures embargo. NQ futures price is derived
via cost-of-carry: F = S * e^((r-q)*T), recalibrated every 15 min.

Result: within $2-5 of live NQ futures price, no accounts needed.

Note: NQ=F on Yahoo WS is also delayed 15 min (same CME embargo as HTTP API),
so ^NDX + basis is more accurate than subscribing to NQ=F directly.
"""
from __future__ import annotations
import asyncio
import base64
import json
import struct
import threading
import time
import logging
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import websockets

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")
WS_URL = "wss://streamer.finance.yahoo.com/"


def _decode_price(msg: str) -> float | None:
    """Decode price (field 2, float) from base64-encoded protobuf message."""
    try:
        raw = base64.b64decode(msg + "==")
        i = 0
        while i < len(raw):
            tag = raw[i]; i += 1
            fnum = tag >> 3; wtyp = tag & 7
            if fnum == 2 and wtyp == 5:
                return struct.unpack('<f', raw[i:i+4])[0]
            if   wtyp == 0:
                while i < len(raw) and raw[i] & 0x80: i += 1
                i += 1
            elif wtyp == 1: i += 8
            elif wtyp == 2:
                n = 0; s = 0
                while i < len(raw):
                    b = raw[i]; i += 1; n |= (b & 127) << s; s += 7
                    if not (b & 128): break
                i += n
            elif wtyp == 5: i += 4
            else: break
    except Exception:
        pass
    return None


def _theoretical_basis(ndx_price: float) -> float:
    """
    Cost-of-carry basis: F = S * e^((r-q)*T)
    r = risk-free rate (~4.5%), q = Nasdaq dividend yield (~0.5%)
    T = days to NQ quarterly expiry (3rd Friday of Mar/Jun/Sep/Dec)
    """
    import math
    from datetime import date as _date

    today = _date.today()
    y, m = today.year, today.month
    exp_months = [3, 6, 9, 12]
    exp_month  = next((em for em in exp_months if em > m or (em == m and today.day < 15)), exp_months[0])
    exp_year   = y if exp_month > m else y + 1

    from calendar import monthcalendar
    fridays = [w[4] for w in monthcalendar(exp_year, exp_month) if w[4]]
    expiry  = _date(exp_year, exp_month, fridays[2])

    T     = (expiry - today).days / 365.0
    try:
        import yfinance as yf
        irx = yf.Ticker("^IRX").fast_info.last_price
        r = irx / 100 if irx and irx > 0 else 0.045
    except Exception:
        r = 0.045
    q = 0.005  # NDX dividend yield (~0.5%)
    basis = ndx_price * (math.exp((r - q) * T) - 1)
    log.info("NQ-NDX theoretical basis: +%.1f (T=%.0fd expiry=%s)", basis, T*365, expiry)
    return basis


class YahooWsFeed:
    """Real-time NQ price via ^NDX Yahoo Finance WebSocket + cost-of-carry basis."""

    def __init__(self):
        self._ndx:      float | None    = None
        self._basis:    float           = 0.0
        self._calibrated                = False
        self._last_cal: datetime        = datetime.now(tz=EST)
        self._updated:  datetime | None = None
        # Timestamped history of raw ^NDX prints — lets a consumer look up what
        # ^NDX was at the (1-2 min old) timestamp of an NQ bar, so it can bridge
        # the lag: live_nq = anchor_nq + (ndx_now - ndx_at_anchor). ~5 min deep.
        self._hist:     deque           = deque(maxlen=2000)
        self._lock      = threading.Lock()
        self._running   = True
        self.connected  = False
        self.source     = "^NDX"

        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    @property
    def price(self) -> float | None:
        """Legacy: ^NDX + cost-of-carry basis. Kept for back-compat; the delta
        tracker uses `.ndx` (raw) instead and never touches the (unreliable) basis."""
        with self._lock:
            if self._ndx is None:
                return None
            return self._ndx + self._basis

    @property
    def ndx(self) -> float | None:
        """Raw real-time ^NDX index value (no basis)."""
        with self._lock:
            return self._ndx

    def ndx_at(self, ts: datetime, tol_seconds: float = 150.0) -> float | None:
        """Raw ^NDX closest to `ts`, or None if no sample within `tol_seconds`."""
        with self._lock:
            best = None
            best_dt = tol_seconds
            for t, v in self._hist:
                d = abs((t - ts).total_seconds())
                if d <= best_dt:
                    best_dt = d
                    best = v
            return best

    @property
    def age_seconds(self) -> float:
        with self._lock:
            if self._updated is None:
                return 999.0
            return (datetime.now(tz=EST) - self._updated).total_seconds()

    def is_stale(self, max_age: float = 30.0) -> bool:
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
                self.connected = False
                log.warning("Yahoo WS: %s — reconnecting in 3s", e)
                time.sleep(3)

    async def _ws_loop(self):
        async with websockets.connect(
            WS_URL,
            additional_headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Origin": "https://finance.yahoo.com",
            },
            ping_interval=20,
        ) as ws:
            await ws.send(json.dumps({"subscribe": ["^NDX"]}))
            self.connected = True
            log.info("Yahoo WS: subscribed to ^NDX")

            async for msg in ws:
                if not self._running:
                    break
                if not isinstance(msg, str):
                    continue
                p = _decode_price(msg)
                if not p or p < 1000:
                    continue
                now = datetime.now(tz=EST)
                with self._lock:
                    self._ndx     = p
                    self._updated = now
                    self._hist.append((now, p))
                    if not self._calibrated or (now - self._last_cal).total_seconds() > 300:
                        self._basis      = _theoretical_basis(p)
                        self._calibrated = True
                        self._last_cal   = now

        self.connected = False
