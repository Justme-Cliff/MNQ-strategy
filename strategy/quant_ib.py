"""
Initial Balance (IB) Breakout with C-period confirmation.

Research basis (2,686 ES sessions / 2,833 NQ sessions, 2015-2025):
  Any IB breakout:                         97% (ES/NQ)
  Single-direction break (NQ):             84%
  Shallow retracement (<25%) → continue:  93.8% (ES) / 92.4% (NQ)
  Trend days travel to:                    2–3× IB range
  NQ outperforms ES on IB strategies.

Definitions:
  IB: first 30 minutes of RTH (9:30–10:00 ET), captured via six 5-min bars
  C-period: 10:00–10:30 ET (first 30 min after IB closes)

ATR-normalized filters:
  IB range: between 0.05× ATR (meaningful) and 0.65× ATR (not chaotic)
  In high-vol (ATR=250): allows 12–162 pt IB ranges
  In normal-vol (ATR=150): allows 8–98 pt IB ranges

Target: 1.5× IB range extension (conservative — research says 2–3× on trend days).
Stop: back inside IB + 1 pt, hard-capped at MAX_RISK_PTS from entry.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional
import pandas as pd
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

MAX_RISK_PTS = 25.0


@dataclass
class IBSignal:
    direction: str
    entry: float
    stop: float
    target: float
    ib_high: float
    ib_low: float
    ib_range: float
    ib_bias: str           # "bullish" (low first) or "bearish" (high first)
    breakout_pts: float
    retracement_pct: float
    signal_bar_idx: int
    atr_ratio: float       # ib_range / atr


def detect(
    df: pd.DataFrame,
    today: date,
    atr: float,
) -> Optional[IBSignal]:
    """
    Detect IB breakout signal for today.
    atr should be the adaptive ATR (max of 5-day and 20-day).
    """
    est_idx = df.index.tz_convert(EST)
    today_mask = est_idx.date == today
    today_df = df[today_mask].copy()

    if len(today_df) < 8:
        return None

    if atr <= 0:
        return None

    # ── Build the IB (9:30–9:55 ET) ─────────────────────────────────────────
    ib_bars = []
    ib_high_ts = None
    ib_low_ts  = None
    ib_high    = None
    ib_low     = None

    for ts, row in today_df.iterrows():
        dt = ts.astimezone(EST)
        mins = dt.hour * 60 + dt.minute
        if 9 * 60 + 30 <= mins <= 9 * 60 + 55:
            ib_bars.append(row)
            h = float(row["High"])
            l = float(row["Low"])
            if ib_high is None or h > ib_high:
                ib_high = h
                ib_high_ts = ts
            if ib_low is None or l < ib_low:
                ib_low = l
                ib_low_ts = ts

    if ib_high is None or ib_low is None or len(ib_bars) < 4:
        return None

    ib_range = ib_high - ib_low
    atr_ratio = ib_range / atr

    # ATR-normalized range filter
    # Minimum: 0.05× ATR — must be a real balance, not noise
    # Maximum: 0.65× ATR — if IB covers 65%+ of typical daily range, it's chaotic
    min_range = max(5.0, atr * 0.05)
    max_range = atr * 0.65

    if ib_range < min_range:
        return None
    if ib_range > max_range:
        return None

    # IB directional bias: which extreme formed first?
    if ib_high_ts <= ib_low_ts:
        ib_bias = "bearish"   # high first → downside lean
    else:
        ib_bias = "bullish"   # low first → upside lean

    # ── C-period scan: breakout + shallow retracement entry ─────────────────
    in_c_period     = False
    breakout_dir    = None
    breakout_extreme = None
    max_extension   = 0.0

    for pos, (ts, row) in enumerate(today_df.iterrows()):
        dt = ts.astimezone(EST)
        mins = dt.hour * 60 + dt.minute

        if mins >= 10 * 60:
            in_c_period = True
        if not in_c_period:
            continue
        if mins >= 11 * 60 + 30:
            break

        close = float(row["Close"])
        high  = float(row["High"])
        low   = float(row["Low"])

        # Phase 1: find initial breakout
        if breakout_dir is None:
            if close > ib_high:
                breakout_dir     = "long"
                breakout_extreme = high
                max_extension    = close - ib_high
                continue
            elif close < ib_low:
                breakout_dir     = "short"
                breakout_extreme = low
                max_extension    = ib_low - close
                continue

        # Phase 2: shallow retracement entry
        else:
            if breakout_dir == "long":
                if high > breakout_extreme:
                    breakout_extreme = high
                    max_extension = breakout_extreme - ib_high

                current_ret    = breakout_extreme - close
                ret_pct        = current_ret / max_extension if max_extension > 0 else 1.0

                # Bias alignment: IB low must have formed first (bullish IB bias)
                # Research: low-first IB = buyers absorbed early selling → continuation long
                if ret_pct < 0.25 and close > ib_high and ib_bias == "bullish":
                    if pos + 1 >= len(today_df):
                        break
                    entry_bar = today_df.iloc[pos + 1]
                    entry  = float(entry_bar["Open"])
                    # Proximity filter: entry must be within 20 pts of ib_high
                    # Far entries (>20 pts) indicate extended breakout, stop gets capped above ib_high
                    if entry - ib_high > 20.0:
                        break
                    # Stop: 2 pts below IB high — if price returns below breakout level, trade failed
                    stop = ib_high - 2.0
                    if entry - stop > MAX_RISK_PTS:
                        stop = entry - MAX_RISK_PTS
                    if entry <= stop:  # price has already fallen back below IB high
                        break
                    # 0.75× IB range extension — conservative but more reachable than 1×
                    target = ib_high + ib_range * 0.75
                    global_idx = df.index.get_loc(entry_bar.name)
                    return IBSignal(
                        direction="long", entry=entry, stop=stop, target=target,
                        ib_high=ib_high, ib_low=ib_low, ib_range=ib_range,
                        ib_bias=ib_bias, breakout_pts=max_extension,
                        retracement_pct=ret_pct, signal_bar_idx=global_idx,
                        atr_ratio=atr_ratio,
                    )

                if close < ib_high:
                    breakout_dir = None
                    max_extension = 0.0

            elif breakout_dir == "short":
                if low < breakout_extreme:
                    breakout_extreme = low
                    max_extension = ib_low - breakout_extreme

                current_ret = close - breakout_extreme
                ret_pct     = current_ret / max_extension if max_extension > 0 else 1.0

                # Bias alignment: IB high must have formed first (bearish IB bias)
                # Research: high-first IB = sellers set the tone → continuation short
                if ret_pct < 0.25 and close < ib_low and ib_bias == "bearish":
                    if pos + 1 >= len(today_df):
                        break
                    entry_bar = today_df.iloc[pos + 1]
                    entry  = float(entry_bar["Open"])
                    # Proximity filter: entry must be within 20 pts of ib_low
                    if ib_low - entry > 20.0:
                        break
                    # Stop: 2 pts above IB low — if price returns above breakout level, trade failed
                    stop = ib_low + 2.0
                    if stop - entry > MAX_RISK_PTS:
                        stop = entry + MAX_RISK_PTS
                    if entry >= stop:  # price has already risen back above IB low
                        break
                    target = ib_low - ib_range * 0.75
                    global_idx = df.index.get_loc(entry_bar.name)
                    return IBSignal(
                        direction="short", entry=entry, stop=stop, target=target,
                        ib_high=ib_high, ib_low=ib_low, ib_range=ib_range,
                        ib_bias=ib_bias, breakout_pts=max_extension,
                        retracement_pct=ret_pct, signal_bar_idx=global_idx,
                        atr_ratio=atr_ratio,
                    )

                if close > ib_low:
                    breakout_dir = None
                    max_extension = 0.0

    return None
