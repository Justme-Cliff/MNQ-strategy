"""
London session analysis (2 AM - 8 AM EST).

TJR/ICT core concept: London often sweeps one side of the Asia range before
NY opens. When London takes out the Asia Low, institutions loaded longs during
London — NY long setups have higher probability. Same logic inverted for Asia High.

This gives directional bias BEFORE the first NY bar even prints.
"""
from __future__ import annotations
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

EST = ZoneInfo("America/New_York")

LONDON_START_HOUR = 2   # 2 AM EST (conservative — catches both winter/summer overlap)
LONDON_END_HOUR   = 8   # 8 AM EST


def get_london_action(
    df: pd.DataFrame,
    trade_date: date,
    asia_high: float,
    asia_low: float,
) -> dict:
    """
    Scan London session bars for trade_date and determine directional bias.

    Returns:
        swept_high  : bool — London pushed above Asia High
        swept_low   : bool — London pushed below Asia Low
        direction   : "bullish" | "bearish" | "both" | "neutral"
        london_high : float — highest London print
        london_low  : float — lowest London print
        sweep_depth_high : float — how far above Asia High (0 if not swept)
        sweep_depth_low  : float — how far below Asia Low (0 if not swept)
    """
    est_idx = df.index.tz_convert(EST)

    swept_high = False
    swept_low  = False
    london_high = asia_high
    london_low  = asia_low
    max_above   = 0.0
    max_below   = 0.0

    for i, ts in enumerate(est_idx):
        if ts.date() != trade_date:
            continue
        if not (LONDON_START_HOUR <= ts.hour < LONDON_END_HOUR):
            continue

        bar_high = float(df["High"].iloc[i])
        bar_low  = float(df["Low"].iloc[i])

        london_high = max(london_high, bar_high)
        london_low  = min(london_low, bar_low)

        if bar_high > asia_high:
            swept_high = True
            max_above  = max(max_above, bar_high - asia_high)

        if bar_low < asia_low:
            swept_low = True
            max_below = max(max_below, asia_low - bar_low)

    if swept_low and not swept_high:
        direction = "bullish"   # London took lows → institutions loaded longs
    elif swept_high and not swept_low:
        direction = "bearish"   # London took highs → institutions loaded shorts
    elif swept_high and swept_low:
        direction = "both"      # Both sides hit — messy, lower confidence
    else:
        direction = "neutral"   # London stayed inside Asia range

    return {
        "swept_high":       swept_high,
        "swept_low":        swept_low,
        "direction":        direction,
        "london_high":      round(london_high, 2),
        "london_low":       round(london_low, 2),
        "sweep_depth_high": round(max_above, 2),
        "sweep_depth_low":  round(max_below, 2),
    }


def is_london_aligned(london: dict, signal_direction: str) -> bool:
    """
    True when London swept the same side as the NY signal direction.

    London swept Asia Low + NY LONG signal  → aligned (institutions preloaded longs)
    London swept Asia High + NY SHORT signal → aligned (institutions preloaded shorts)
    London swept neither or both             → not aligned (no bonus)
    """
    if london["direction"] == "bullish" and signal_direction == "long":
        return True
    if london["direction"] == "bearish" and signal_direction == "short":
        return True
    return False


def london_summary_line(london: dict) -> str:
    """One-line description for the morning briefing."""
    d = london["direction"]
    if d == "bullish":
        return (f"Swept Asia LOW by {london['sweep_depth_low']:.1f} pts  "
                f"→ [green]bullish bias[/green] (institutions loaded longs in London)")
    if d == "bearish":
        return (f"Swept Asia HIGH by {london['sweep_depth_high']:.1f} pts  "
                f"→ [red]bearish bias[/red] (institutions loaded shorts in London)")
    if d == "both":
        return "Swept BOTH sides — messy, no clear bias"
    return "Stayed inside Asia range — no London sweep yet"
