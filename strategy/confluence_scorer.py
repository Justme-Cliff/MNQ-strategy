"""
Confluence scorer — the gatekeeper.

9-point system (upgraded from 7). Same 4-point base threshold, raised
dynamically by smart_filter based on context, streak, and market regime.

Score breakdown:
  1. Asia sweep detected                    (required)
  2. MSS confirmed                          (required)
  3. FVG present in entry zone
  4. VWAP aligned with direction
  5. In prime trade window (9:30-11:00 AM)
  6. PDH/PDL confluence                     (sweep hits a prior day level too)
  7. Opening range opposed                  (setup reverses 9:30 trap direction)
  8. Weekly level confluence                (sweep hits a prior week H/L too)   NEW
  9. OTE zone (Optimal Trade Entry)         (price in 61.8-78.6% fib retrace)   NEW

Stored but NOT counted in score (used by smart_filter to raise threshold):
  - london_aligned : London swept the same side
  - mss_strong     : MSS candle has real institutional displacement
  - smt_confirmed  : ES confirms the NQ sweep direction
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ConfluenceResult:
    score: int
    asia_sweep: bool
    mss_confirmed: bool
    fvg_active: bool
    vwap_aligned: bool
    in_time_window: bool
    pdh_pdl_confluence: bool
    opening_range_opposed: bool
    weekly_level_confluence: bool
    ote_zone: bool
    london_aligned: bool
    mss_strong: bool
    smt_confirmed: bool
    direction: str
    reason: str = ""

    def __post_init__(self):
        parts = []
        if self.asia_sweep:               parts.append("Sweep")
        if self.mss_confirmed:            parts.append("MSS" + ("+" if self.mss_strong else ""))
        if self.fvg_active:               parts.append("FVG")
        if self.vwap_aligned:             parts.append("VWAP")
        if self.in_time_window:           parts.append("Time")
        if self.pdh_pdl_confluence:       parts.append("PDH/PDL")
        if self.opening_range_opposed:    parts.append("OpenRng")
        if self.weekly_level_confluence:  parts.append("WeeklyLvl")
        if self.ote_zone:                 parts.append("OTE")
        if self.london_aligned:           parts.append("London")
        if self.smt_confirmed:            parts.append("SMT")
        self.reason = " + ".join(parts) if parts else "No confluences"

    @property
    def tradeable(self) -> bool:
        from config import MIN_CONFLUENCE_SCORE
        return self.score >= MIN_CONFLUENCE_SCORE

    @property
    def max_score(self) -> int:
        return 9


def score_setup(
    asia_sweep: bool,
    mss_confirmed: bool,
    fvg_active: bool,
    price: float,
    vwap: float | None,
    direction: str,
    bar_hour: int,
    bar_minute: int,
    # Existing optional params (safe defaults for backward compat)
    pdh_pdl_confluence: bool = False,
    opening_range_opposed: bool = False,
    london_aligned: bool = False,
    mss_strong: bool = False,
    prev_day_high: float | None = None,
    prev_day_low: float | None = None,
    sweep_price: float | None = None,
    # New optional params
    prev_week_high: float | None = None,
    prev_week_low: float | None = None,
    ote_zone: bool = False,
    smt_confirmed: bool = True,
) -> ConfluenceResult:
    """
    Score a potential setup 0-9 and return a ConfluenceResult.
    direction: "long" or "short"
    """
    vwap_aligned = False
    if vwap is not None:
        if direction == "long"  and price > vwap: vwap_aligned = True
        if direction == "short" and price < vwap: vwap_aligned = True

    mins = bar_hour * 60 + bar_minute
    in_time_window = (9 * 60 + 30) <= mins < (11 * 60)

    # Auto-compute PDH/PDL confluence from raw levels if flag not already set
    if not pdh_pdl_confluence and sweep_price is not None:
        if direction == "long"  and prev_day_low  is not None:
            pdh_pdl_confluence = sweep_price <= prev_day_low + 10
        if direction == "short" and prev_day_high is not None:
            pdh_pdl_confluence = sweep_price >= prev_day_high - 10

    # Auto-compute weekly level confluence from raw levels if not set
    weekly_level = False
    if sweep_price is not None:
        if direction == "long"  and prev_week_low  is not None:
            weekly_level = sweep_price <= prev_week_low
        if direction == "short" and prev_week_high is not None:
            weekly_level = sweep_price >= prev_week_high

    score = sum([
        asia_sweep,
        mss_confirmed,
        fvg_active,
        vwap_aligned,
        in_time_window,
        pdh_pdl_confluence,
        opening_range_opposed,
        weekly_level,
        ote_zone,
    ])

    return ConfluenceResult(
        score=score,
        asia_sweep=asia_sweep,
        mss_confirmed=mss_confirmed,
        fvg_active=fvg_active,
        vwap_aligned=vwap_aligned,
        in_time_window=in_time_window,
        pdh_pdl_confluence=pdh_pdl_confluence,
        opening_range_opposed=opening_range_opposed,
        weekly_level_confluence=weekly_level,
        ote_zone=ote_zone,
        london_aligned=london_aligned,
        mss_strong=mss_strong,
        smt_confirmed=smt_confirmed,
        direction=direction,
    )
