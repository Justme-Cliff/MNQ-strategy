"""
Gap Fill Strategy — statistical edge on tiny overnight gaps.

Research basis (2,791 NQ trading days, 2015-2025):
  Tiny gap (<0.3× ATR) fill rate:              77.8%
  Tiny gap + first-bar confirmation:            93.1%
  61% of fills complete before 10:00 AM ET
  Fills extend median 39.5 pts past target

Rules:
  1. Gap size < 0.3× 20-day ATR
  2. Gap size > 2 pts (not noise) and < 0.55% of prior close
  3. First 5-min bar moves toward the gap (confirms institutional intent)
  4. Enter at open of second bar
  5. Target: prior close (gap fill level)
  6. Stop: 2 pts beyond first bar's extreme in wrong direction
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
import pandas as pd
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")


@dataclass
class GapFillSignal:
    direction: str       # "long" (gap down → fill up) or "short" (gap up → fill down)
    entry: float
    stop: float
    target: float        # prior close = gap fill level
    gap_size: float      # points
    gap_pct: float       # fraction of prior close
    gap_ratio: float     # gap_size / ATR
    signal_bar_idx: int  # global df index of the entry bar (second 5m bar)


def detect(df: pd.DataFrame, today: date, atr: float) -> GapFillSignal | None:
    """
    Check if today has a tradeable gap fill setup.
    Returns signal or None.
    """
    est_idx = df.index.tz_convert(EST)

    # Prior day's last bar close
    prior_mask = est_idx.date < today
    prior_bars = df[prior_mask]
    if prior_bars.empty:
        return None
    prior_close = float(prior_bars["Close"].iloc[-1])

    # Today's bars in order
    today_mask = est_idx.date == today
    today_bars = df[today_mask]
    if len(today_bars) < 2:
        return None

    # First bar of the day
    first_bar = today_bars.iloc[0]
    today_open = float(first_bar["Open"])

    gap = today_open - prior_close          # positive = gap up, negative = gap down
    gap_size = abs(gap)

    # Filter 1: not noise
    if gap_size < 2.0:
        return None

    # Filter 2: tiny gap (< 0.3× ATR)
    if atr <= 0:
        return None
    gap_ratio = gap_size / atr
    if gap_ratio > 0.30:
        return None

    # Filter 3: not a news spike (< 0.55% of price)
    gap_pct = gap_size / prior_close
    if gap_pct > 0.0055:
        return None

    direction = "long" if gap < 0 else "short"

    # Filter 4: first bar must move toward the gap
    first_close = float(first_bar["Close"])
    first_open_price = float(first_bar["Open"])
    if direction == "long":
        confirms = first_close > first_open_price   # bullish bar on gap-down day
    else:
        confirms = first_close < first_open_price   # bearish bar on gap-up day
    if not confirms:
        return None

    # Entry: open of second bar
    second_bar = today_bars.iloc[1]
    entry = float(second_bar["Open"])
    signal_bar_idx = df.index.get_loc(second_bar.name)

    # Stop: 2 pts past first bar's wrong-direction extreme
    if direction == "long":
        stop = float(first_bar["Low"]) - 2.0
    else:
        stop = float(first_bar["High"]) + 2.0

    # Risk check: stop must be within 25 pts of entry
    if abs(entry - stop) > 25.0:
        return None

    # Skip if entry has already overshot the target (gap filled before entry bar)
    if direction == "long" and entry >= prior_close:
        return None
    if direction == "short" and entry <= prior_close:
        return None

    return GapFillSignal(
        direction=direction,
        entry=entry,
        stop=stop,
        target=prior_close,
        gap_size=gap_size,
        gap_pct=gap_pct,
        gap_ratio=gap_ratio,
        signal_bar_idx=signal_bar_idx,
    )
