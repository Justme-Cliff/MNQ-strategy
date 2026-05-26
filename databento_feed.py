"""
Real-time NQ price feed via Databento CME Globex live stream.
Tick-level data, zero delay — replaces yfinance.
"""
from __future__ import annotations
import os
import threading
import time
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")

PRICE_SCALE = 1_000_000_000  # Databento fixed-point: divide by 1e9 for real price


def _front_month() -> str:
    today = date.today()
    y = str(today.year)[-1]
    m, d = today.month, today.day
    if   m < 3  or (m == 3  and d < 15): return f"NQH{y}"
    elif m < 6  or (m == 6  and d < 15): return f"NQM{y}"
    elif m < 9  or (m == 9  and d < 15): return f"NQU{y}"
    elif m < 12 or (m == 12 and d < 15): return f"NQZ{y}"
    else: return f"NQH{int(y)+1 if y != '9' else 0}"


class DatabentoPriceFeed:
    """Real-time NQ price via Databento GLBX.MDP3 live stream."""

    def __init__(self):
        self._price:   float | None    = None
        self._updated: datetime | None = None
        self._lock     = threading.Lock()
        self._running  = True
        self.symbol    = _front_month()
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
        import databento as db

        key = os.getenv("DATABENTO_API_KEY", "")
        if not key:
            log.error("DATABENTO_API_KEY not set in .env")
            return

        while self._running:
            try:
                client = db.Live(key=key)
                client.subscribe(
                    dataset="GLBX.MDP3",
                    schema="trades",
                    stype_in="raw_symbol",
                    symbols=[self.symbol],
                )
                self.connected = True
                log.info("Databento: streaming %s real-time trades", self.symbol)

                for record in client:
                    if not self._running:
                        client.stop()
                        break
                    try:
                        p = record.price / PRICE_SCALE
                        if p > 1000:
                            with self._lock:
                                self._price   = p
                                self._updated = datetime.now(tz=EST)
                    except AttributeError:
                        pass  # metadata/system records have no .price

            except Exception as e:
                self.connected = False
                log.warning("Databento error: %s — reconnecting in 5s", e)
                time.sleep(5)
