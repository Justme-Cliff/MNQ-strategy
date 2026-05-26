"""
Real-time NQ price feed via Yahoo Finance WebSocket.

Subscribes to NQ=F directly — same stream that powers Yahoo Finance's website.
Falls back to ^NDX + cost-of-carry basis if NQ=F ticks are not received.
"""
from __future__ import annotations
import asyncio
import base64
import json
import struct
import threading
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import websockets

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")
WS_URL = "wss://streamer.finance.yahoo.com/"

# Subscribe to NQ=F (actual futures) first; ^NDX as fallback
_PRIMARY   = "NQ=F"
_FALLBACK  = "^NDX"
_NQ_MIN    = 15_000.0   # sanity floor for NQ futures
_NDX_MIN   = 1_000.0    # sanity floor for ^NDX index


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
    r, q  = 0.045, 0.005
    basis = ndx_price * (math.exp((r - q) * T) - 1)
    log.info("NQ-NDX theoretical basis: +%.1f (T=%.0fd expiry=%s)", basis, T*365, expiry)
    return basis


class YahooWsFeed:
    """
    Real-time NQ price via Yahoo Finance WebSocket.

    Tries NQ=F directly (exact futures price). If no tick arrives within
    15s falls back to ^NDX + cost-of-carry basis (within ~$5).
    """

    def __init__(self):
        self._price:    float | None    = None
        self._ndx:      float | None    = None
        self._basis:    float           = 0.0
        self._calibrated                = False
        self._last_cal: datetime        = datetime.now(tz=EST)
        self._updated:  datetime | None = None
        self._lock      = threading.Lock()
        self._running   = True
        self.connected  = False
        self.source     = "connecting"   # "NQ=F" | "^NDX+basis"

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
            # Subscribe to both — whichever ticks in real-time wins
            await ws.send(json.dumps({"subscribe": [_PRIMARY, _FALLBACK]}))
            self.connected = True
            log.info("Yahoo WS: subscribed to %s + %s", _PRIMARY, _FALLBACK)

            _nqf_deadline = time.monotonic() + 15  # give NQ=F 15s to prove itself
            _nqf_seen     = False

            async for msg in ws:
                if not self._running:
                    break
                if not isinstance(msg, str):
                    continue
                p = _decode_price(msg)
                if not p:
                    continue

                now = datetime.now(tz=EST)

                if p >= _NQ_MIN:
                    # High value → this is NQ=F (futures are ~20k-25k range)
                    with self._lock:
                        self._price   = p
                        self._updated = now
                        self.source   = "NQ=F"
                    if not _nqf_seen:
                        _nqf_seen = True
                        log.info("Yahoo WS: NQ=F real-time confirmed at %.1f", p)

                elif p >= _NDX_MIN and p < _NQ_MIN:
                    # Low value → this is ^NDX index
                    # Only use as price source if NQ=F never ticked
                    if not _nqf_seen and time.monotonic() > _nqf_deadline:
                        with self._lock:
                            self._ndx     = p
                            self._updated = now
                            self.source   = "^NDX+basis"
                            if not self._calibrated or (now - self._last_cal).total_seconds() > 900:
                                self._basis      = _theoretical_basis(p)
                                self._calibrated = True
                                self._last_cal   = now
                            self._price = p + self._basis
                    elif not _nqf_seen:
                        # Still in grace period — update NDX but don't set price yet
                        with self._lock:
                            self._ndx = p

        self.connected = False
