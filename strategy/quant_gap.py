"""
Gap Fill Strategy — statistical edge on tiny overnight gaps.

Research basis (2,791 NQ trading days, 2015-2025):
  Tiny gap (<0.3× ATR) fill rate:              77.8%
  Tiny gap + first-bar confirmation:            93.1%
  61% of fills complete before 10:00 AM ET
  Fills extend median 39.5 pts past target

Improvements over v1:
  - Monday skip: Monday gaps have lower fill rate (weekend positioning noise)
  - Pre-market bias: last 30 min of pre-market must trend toward the gap
  - Tighter size filter: gap_ratio < 0.20 (was 0.30) — smaller gaps fill more reliably
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
import pandas as pd
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")


@dataclass
class GapFillSignal:
    direction: str
    entry: float
    stop: float
    target: float
    gap_size: float
    gap_pct: float
    gap_ratio: float
    signal_bar_idx: int


def detect(
    df: pd.DataFrame,
    today: date,
    atr: float,
    dow: int = -1,           # day of week (0=Mon … 4=Fri); -1 = skip Monday check
) -> GapFillSignal | None:
    """
    Check if today has a tradeable gap fill setup.
    dow: pass today.weekday() to enable the Monday filter.
    """
    # Improvement 1: Skip Mondays — weekend positioning noise lowers fill rate
    if dow == 0:
        return None

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

    first_bar   = today_bars.iloc[0]
    today_open  = float(first_bar["Open"])

    gap      = today_open - prior_close
    gap_size = abs(gap)

    if gap_size < 2.0:
        return None

    if atr <= 0:
        return None
    gap_ratio = gap_size / atr

    # Improvement 2: Tighter ratio — gaps below 0.20× ATR fill most reliably
    if gap_ratio > 0.20:
        return None

    gap_pct = gap_size / prior_close
    if gap_pct > 0.0055:
        return None

    direction = "long" if gap < 0 else "short"

    # Filter: first bar must move toward the gap
    first_close       = float(first_bar["Close"])
    first_open_price  = float(first_bar["Open"])
    if direction == "long":
        if first_close <= first_open_price:
            return None
    else:
        if first_close >= first_open_price:
            return None

    # Improvement 3: Pre-market bias — last 30 min of pre-market must align
    # Pre-market = bars before 9:30 AM on today's date
    premarket_mask = (est_idx.date == today) & (
        (est_idx.hour < 9) | ((est_idx.hour == 9) & (est_idx.minute < 30))
    )
    pm_bars = df[premarket_mask]
    if len(pm_bars) >= 3:
        # Use last 30 min of pre-market (last ~6 bars of 5m data)
        recent_pm = pm_bars.iloc[-6:]
        pm_open  = float(recent_pm.iloc[0]["Open"])
        pm_close = float(recent_pm.iloc[-1]["Close"])
        pm_trend = "long" if pm_close > pm_open else "short"
        # Pre-market must trend in the same direction as the gap fill
        if pm_trend != direction:
            return None

    # Entry: open of second bar
    second_bar     = today_bars.iloc[1]
    entry          = float(second_bar["Open"])
    signal_bar_idx = df.index.get_loc(second_bar.name)

    if direction == "long":
        stop = float(first_bar["Low"]) - 2.0
    else:
        stop = float(first_bar["High"]) + 2.0

    if abs(entry - stop) > 25.0:
        return None

    if direction == "long" and entry >= prior_close:
        return None
    if direction == "short" and entry <= prior_close:
        return None

    # Target: gap fill + 50% extension — research shows 40%+ of fills continue past prior_close
    if direction == "long":
        target = prior_close + gap_size * 0.5
    else:
        target = prior_close - gap_size * 0.5

    return GapFillSignal(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        gap_size=gap_size,
        gap_pct=gap_pct,
        gap_ratio=gap_ratio,
        signal_bar_idx=signal_bar_idx,
    )
