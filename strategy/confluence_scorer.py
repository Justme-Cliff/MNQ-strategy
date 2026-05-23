"""
Confluence scorer — the gatekeeper.

7-point system (up from 5). Same 4-point threshold, but smart_filter raises it
dynamically based on MSS strength, London alignment, and day-of-week rules.

Score breakdown:
  1. Asia sweep detected            (required)
  2. MSS confirmed                  (required)
  3. FVG present in entry zone
  4. VWAP aligned with direction
  5. In prime trade window (9:30-11:00 AM)
  6. PDH/PDL confluence (sweep also takes out a previous day level)  [NEW]
  7. Opening range opposed (setup goes against the 9:30-10:00 trap)  [NEW]

Stored but not counted in score (used by smart_filter to raise threshold):
  - london_aligned  : London swept the same side → +quality signal
  - mss_strong      : MSS candle shows real displacement
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
    pdh_pdl_confluence: bool
    opening_range_opposed: bool
    london_aligned: bool
    mss_strong: bool
    direction: str
    reason: str = ""

    def __post_init__(self):
        parts = []
        if self.asia_sweep:             parts.append("Sweep")
        if self.mss_confirmed:          parts.append("MSS" + ("+" if self.mss_strong else ""))
        if self.fvg_active:             parts.append("FVG")
        if self.vwap_aligned:           parts.append("VWAP")
        if self.in_time_window:         parts.append("Time")
        if self.pdh_pdl_confluence:     parts.append("PDH/PDL")
        if self.opening_range_opposed:  parts.append("OpenRng")
        if self.london_aligned:         parts.append("London")
        self.reason = " + ".join(parts) if parts else "No confluences"

    @property
    def tradeable(self) -> bool:
        from config import MIN_CONFLUENCE_SCORE
        return self.score >= MIN_CONFLUENCE_SCORE

    @property
    def max_score(self) -> int:
        return 7


def score_setup(
    asia_sweep: bool,
    mss_confirmed: bool,
    fvg_active: bool,
    price: float,
    vwap: float | None,
    direction: str,
    bar_hour: int,
    bar_minute: int,
    # New parameters — all optional with safe defaults for backwards compat
    pdh_pdl_confluence: bool = False,
    opening_range_opposed: bool = False,
    london_aligned: bool = False,
    mss_strong: bool = False,
    prev_day_high: float | None = None,
    prev_day_low: float | None = None,
    sweep_price: float | None = None,
) -> ConfluenceResult:
    """
    Score a potential setup 0-7 and return a ConfluenceResult.
    direction: "long" or "short"
    """
    vwap_aligned = False
    if vwap is not None:
        if direction == "long"  and price > vwap: vwap_aligned = True
        if direction == "short" and price < vwap: vwap_aligned = True

    # Prime time window: 9:30-11:00 AM (note: 11:00-11:30 requires 5+ via smart_filter)
    mins = bar_hour * 60 + bar_minute
    in_time_window = (9 * 60 + 30) <= mins < (11 * 60)

    # Auto-compute PDH/PDL confluence if raw levels provided but flag not set
    if not pdh_pdl_confluence and sweep_price is not None:
        if direction == "long"  and prev_day_low  is not None:
            pdh_pdl_confluence = sweep_price <= prev_day_low + 10
        if direction == "short" and prev_day_high is not None:
            pdh_pdl_confluence = sweep_price >= prev_day_high - 10

    score = sum([
        asia_sweep,
        mss_confirmed,
        fvg_active,
        vwap_aligned,
        in_time_window,
        pdh_pdl_confluence,
        opening_range_opposed,
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
        london_aligned=london_aligned,
        mss_strong=mss_strong,
        direction=direction,
    )
