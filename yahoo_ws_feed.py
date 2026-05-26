"""
Real-time NQ price feed via Yahoo Finance WebSocket (^NDX index stream).

^NDX updates every 1-5 seconds with real-time Nasdaq 100 index data.
A basis offset (NQ futures premium over index) is calibrated at startup
using a single yfinance call, then applied to every incoming tick.

Result: real-time NQ futures price approximation, no accounts needed.
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
import yfinance as yf

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


def _calibrate_basis(ndx_price: float) -> float:
    """Calculate NQ futures - NDX basis using yfinance snapshot."""
    try:
        nq = yf.Ticker("NQ=F").fast_info.last_price
        if nq and nq > 0:
            basis = nq - ndx_price
            log.info("NQ-NDX basis calibrated: +%.1f (NQ=%.1f NDX=%.1f)", basis, nq, ndx_price)
            return basis
    except Exception as e:
        log.warning("Basis calibration failed: %s — using 0", e)
    return 0.0


class YahooWsFeed:
    """Real-time NQ price via ^NDX Yahoo Finance WebSocket + basis correction."""

    def __init__(self):
        self._ndx:     float | None    = None   # raw ^NDX index price
        self._basis:   float           = 0.0    # NQ futures - NDX offset
        self._calibrated               = False
        self._updated: datetime | None = None
        self._lock     = threading.Lock()
        self._running  = True
        self.connected = False

        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    @property
    def price(self) -> float | None:
        with self._lock:
            if self._ndx is None:
                return None
            return self._ndx + self._basis

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
                with self._lock:
                    self._ndx     = p
                    self._updated = datetime.now(tz=EST)
                    if not self._calibrated:
                        self._basis      = _calibrate_basis(p)
                        self._calibrated = True

        self.connected = False
