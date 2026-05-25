"""
Opening Range Breakout (ORB) — 5-minute opening range, ATR-normalized.

Research basis:
  Toby Crabel (1990): 68% WR on S&P 500 futures (original)
  Edgeful ES backtest: 72.17% WR, profit factor 1.623
  Unger Academy NQ: 74.56% WR, profit factor 2.512

Opening range: first 5-minute bar (9:30–9:35 ET).

Filters (ATR-normalized — self-adapts to ANY volatility regime):
  1. ORB range between 0.025× ATR (not a doji) and 0.50× ATR (not chaotic)
     In high-vol (ATR=250): allows 6–125 pt ranges
     In normal-vol (ATR=150): allows 4–75 pt ranges
  2. Long breakout: close above ORB high AND above session VWAP
  3. Short breakout: close below ORB low AND below session VWAP
  4. Monday/Tuesday longs blocked (weekly bias not established)
  5. First breakout only per session

Stop: 50% back into ORB from breakout point, absolute cap at MAX_RISK_PTS.
Target: entry ± 1.0× ORB range (conservative; breakouts often extend 1.5-2×).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional
import pandas as pd
from zoneinfo import ZoneInfo
from strategy.quant_regime import session_vwap

EST = ZoneInfo("America/New_York")

MAX_RISK_PTS = 25.0   # prop firm hard cap: 25 pts × $2/pt = $50 MNQ


@dataclass
class ORBSignal:
    direction: str
    entry: float
    stop: float
    target: float
    orb_high: float
    orb_low: float
    orb_range: float
    signal_bar_idx: int
    vwap_at_entry: float
    atr_ratio: float     # orb_range / atr — how "wide" this ORB is relative to vol


def detect(
    df: pd.DataFrame,
    today: date,
    atr: float,
    day_of_week: int,
) -> Optional[ORBSignal]:
    """
    Detect ORB signal for today using ATR-normalized quality filters.
    atr should be the adaptive ATR (max of 5-day and 20-day).
    """
    est_idx = df.index.tz_convert(EST)
    today_mask = est_idx.date == today
    today_df = df[today_mask].copy()

    if len(today_df) < 3:
        return None

    # Locate the 9:30 bar
    orb_bar = None
    orb_bar_loc = None
    for ts, row in today_df.iterrows():
        dt = ts.astimezone(EST)
        if dt.hour == 9 and dt.minute == 30:
            orb_bar = row
            orb_bar_loc = ts
            break

    if orb_bar is None:
        return None

    orb_high  = float(orb_bar["High"])
    orb_low   = float(orb_bar["Low"])
    orb_range = orb_high - orb_low

    if atr <= 0:
        return None

    # ATR-normalized range filter
    # Minimum: 0.025× ATR — eliminates doji/noise opens
    # Maximum: 0.50× ATR  — eliminates chaotic/news-spike opens
    min_range = max(3.0, atr * 0.025)
    max_range = atr * 0.50

    if orb_range < min_range:
        return None
    if orb_range > max_range:
        return None

    atr_ratio = orb_range / atr

    # Precompute session VWAP
    vwap_series = session_vwap(today_df)

    past_orb = False
    for pos, (ts, row) in enumerate(today_df.iterrows()):
        dt = ts.astimezone(EST)

        if not past_orb:
            if ts == orb_bar_loc:
                past_orb = True
            continue

        if dt.hour >= 12:
            break

        close    = float(row["Close"])
        vwap_val = float(vwap_series.iloc[pos])

        # Long breakout
        if close > orb_high:
            if close < vwap_val:             # must be above VWAP
                continue
            if day_of_week in (0, 1):        # Mon/Tue longs blocked
                continue
            if pos + 1 >= len(today_df):
                break
            entry_bar = today_df.iloc[pos + 1]
            entry  = float(entry_bar["Open"])
            # Stop: 50% back into ORB (gives breakout room to breathe)
            stop   = orb_high - orb_range * 0.5
            # Absolute risk cap for prop firm rules
            if entry - stop > MAX_RISK_PTS:
                stop = entry - MAX_RISK_PTS
            target = entry + orb_range        # 100% extension
            if abs(entry - target) < 3.0:
                continue
            global_idx = df.index.get_loc(entry_bar.name)
            return ORBSignal(
                direction="long", entry=entry, stop=stop, target=target,
                orb_high=orb_high, orb_low=orb_low, orb_range=orb_range,
                signal_bar_idx=global_idx, vwap_at_entry=vwap_val,
                atr_ratio=atr_ratio,
            )

        # Short breakout
        elif close < orb_low:
            if close > vwap_val:             # must be below VWAP
                continue
            if pos + 1 >= len(today_df):
                break
            entry_bar = today_df.iloc[pos + 1]
            entry  = float(entry_bar["Open"])
            stop   = orb_low + orb_range * 0.5
            if stop - entry > MAX_RISK_PTS:
                stop = entry + MAX_RISK_PTS
            target = entry - orb_range
            if abs(entry - target) < 3.0:
                continue
            global_idx = df.index.get_loc(entry_bar.name)
            return ORBSignal(
                direction="short", entry=entry, stop=stop, target=target,
                orb_high=orb_high, orb_low=orb_low, orb_range=orb_range,
                signal_bar_idx=global_idx, vwap_at_entry=vwap_val,
                atr_ratio=atr_ratio,
            )

    return None
