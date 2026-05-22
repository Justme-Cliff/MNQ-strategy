"""
SignalGenerator — combines all sub-detectors into a single output.

For live use: parse a webhook payload from TradingView.
For backtest use: process bar-by-bar through the full pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from strategy.confluence_scorer import ConfluenceResult

EST = ZoneInfo("America/New_York")


@dataclass
class TradeSignal:
    direction: str          # "long" or "short"
    entry: float
    stop: float
    target_tp1: float       # 1.5:1 RR
    target_tp2: float       # 3:1 RR
    score: int
    confluence: ConfluenceResult
    timestamp: datetime
    asia_high: float
    asia_low: float
    vwap: float | None

    @property
    def stop_distance(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def rr_tp2(self) -> float:
        return abs(self.target_tp2 - self.entry) / self.stop_distance if self.stop_distance else 0


def signal_from_webhook(payload: dict) -> TradeSignal | None:
    """
    Parse a TradeSignal from a TradingView webhook payload.
    Expected payload keys: direction, entry, stop, target, score, asia_high, asia_low, vwap
    """
    try:
        direction = payload["direction"]
        entry = float(payload["entry"])
        stop = float(payload["stop"])
        target_tp2 = float(payload["target"])
        stop_dist = abs(entry - stop)
        target_tp1 = entry + stop_dist * 1.5 if direction == "long" else entry - stop_dist * 1.5

        score = int(payload.get("score", 0))

        from strategy.confluence_scorer import ConfluenceResult
        confluence = ConfluenceResult(
            score=score,
            asia_sweep=bool(payload.get("asia_sweep", True)),
            mss_confirmed=bool(payload.get("mss_confirmed", True)),
            fvg_active=bool(payload.get("fvg_active", True)),
            vwap_aligned=bool(payload.get("vwap_aligned", True)),
            in_time_window=bool(payload.get("in_time_window", True)),
            direction=direction,
        )

        return TradeSignal(
            direction=direction,
            entry=entry,
            stop=stop,
            target_tp1=round(target_tp1, 2),
            target_tp2=round(target_tp2, 2),
            score=score,
            confluence=confluence,
            timestamp=datetime.now(tz=EST),
            asia_high=float(payload.get("asia_high", 0)),
            asia_low=float(payload.get("asia_low", 0)),
            vwap=float(payload["vwap"]) if payload.get("vwap") else None,
        )
    except (KeyError, ValueError, TypeError) as e:
        return None
