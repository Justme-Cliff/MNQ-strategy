"""
Confluence scorer — the gatekeeper.

Scores a potential setup 0-5. Trade is only taken if score >= MIN_CONFLUENCE_SCORE (4).

Score breakdown:
  1. Asia sweep detected            (required)
  2. MSS confirmed                  (required)
  3. FVG present in entry zone      (required)
  4. Price on correct side of VWAP  (required for score of 4)
  5. In trade time window           (9:30-11:00 AM = full point, 11:00-11:30 = only if 5/5)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ConfluenceResult:
    score: int
    asia_sweep: bool
    mss_confirmed: bool
    fvg_active: bool
    vwap_aligned: bool
    in_time_window: bool
    direction: str
    reason: str = ""

    def __post_init__(self):
        parts = []
        if self.asia_sweep:     parts.append("Asia Sweep")
        if self.mss_confirmed:  parts.append("MSS")
        if self.fvg_active:     parts.append("FVG")
        if self.vwap_aligned:   parts.append("VWAP")
        if self.in_time_window: parts.append("Time")
        self.reason = " + ".join(parts) if parts else "No confluences"

    @property
    def tradeable(self) -> bool:
        from config import MIN_CONFLUENCE_SCORE
        return self.score >= MIN_CONFLUENCE_SCORE


def score_setup(
    asia_sweep: bool,
    mss_confirmed: bool,
    fvg_active: bool,
    price: float,
    vwap: float | None,
    direction: str,
    bar_hour: int,
    bar_minute: int,
) -> ConfluenceResult:
    """
    Score a setup and return a ConfluenceResult.
    direction: "long" or "short"
    """
    vwap_aligned = False
    if vwap is not None:
        if direction == "long" and price > vwap:
            vwap_aligned = True
        elif direction == "short" and price < vwap:
            vwap_aligned = True

    # Time window: 9:30-11:30 AM EST
    minutes_since_midnight = bar_hour * 60 + bar_minute
    trade_start = 9 * 60 + 30    # 570
    trade_end   = 11 * 60 + 30   # 690
    in_time_window = trade_start <= minutes_since_midnight < trade_end

    score = sum([asia_sweep, mss_confirmed, fvg_active, vwap_aligned, in_time_window])

    return ConfluenceResult(
        score=score,
        asia_sweep=asia_sweep,
        mss_confirmed=mss_confirmed,
        fvg_active=fvg_active,
        vwap_aligned=vwap_aligned,
        in_time_window=in_time_window,
        direction=direction,
    )
