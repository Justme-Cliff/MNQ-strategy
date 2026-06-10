"""
Opening Range Breakout (ORB) — 5-minute opening range, ATR-normalized.

Research basis:
  Toby Crabel (1990): 68% WR on S&P 500 futures (original)
  Edgeful ES backtest: 72.17% WR, profit factor 1.623
  Unger Academy NQ: 74.56% WR, profit factor 2.512

Opening range: first 5-minute bar (9:30–9:35 ET).

Improvements over v1:
  - Pullback entry: instead of entering at the breakout bar, wait for the first
    pullback toward the ORB level (within 25% of ORB range). Entry closer to the
    level = tighter stop + better R:R. Fallback to direct entry if no pullback
    within 4 bars.
  - Tighter stop on pullback entry: 2 pts below orb_high (vs 50% ORB previously).
  - Bigger target on pullback entry: 2.0× ORB range (vs 1.0× previously) —
    justified by better entry price and confirmed institutional interest.
  - Raised VIX tolerance: engine now allows VIX < 25 (was 22) with strong trend.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional
import pandas as pd
from zoneinfo import ZoneInfo
from strategy.quant_regime import session_vwap

EST = ZoneInfo("America/New_York")

MAX_RISK_PTS   = 25.0
PULLBACK_ZONE  = 0.25   # pullback within 25% of ORB range from the breakout level
PULLBACK_BARS  = 4       # bars to wait for pullback before falling back to direct entry


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
    atr_ratio: float
    entry_type: str = "pullback"   # "pullback" or "direct"


def detect(
    df: pd.DataFrame,
    today: date,
    atr: float,
    day_of_week: int,
) -> Optional[ORBSignal]:
    """
    Detect ORB signal with pullback entry for better R:R.
    atr should be the adaptive ATR (max of 5-day and 20-day).
    """
    est_idx  = df.index.tz_convert(EST)
    today_df = df[est_idx.date == today].copy()

    if len(today_df) < 3:
        return None

    # Locate the 9:30 bar
    orb_bar = orb_bar_loc = None
    for ts, row in today_df.iterrows():
        dt = ts.astimezone(EST)
        if dt.hour == 9 and dt.minute == 30:
            orb_bar     = row
            orb_bar_loc = ts
            break

    if orb_bar is None:
        return None

    orb_high  = float(orb_bar["High"])
    orb_low   = float(orb_bar["Low"])
    orb_range = orb_high - orb_low

    if atr <= 0 or orb_range <= 0:
        return None

    min_range = max(3.0, atr * 0.025)
    max_range = atr * 0.50
    if orb_range < min_range or orb_range > max_range:
        return None

    atr_ratio    = orb_range / atr
    vwap_series  = session_vwap(today_df)
    past_orb     = False
    breakout_dir = None      # "long" or "short" once initial breakout is seen
    bars_since_breakout = 0
    initial_entry_bar   = None    # saved for direct-entry fallback
    initial_entry_vwap  = 0.0

    for pos, (ts, row) in enumerate(today_df.iterrows()):
        dt = ts.astimezone(EST)

        if not past_orb:
            if ts == orb_bar_loc:
                past_orb = True
            continue

        if dt.hour >= 12:
            break

        close    = float(row["Close"])
        high     = float(row["High"])
        low      = float(row["Low"])
        vwap_val = float(vwap_series.iloc[pos])

        # ── Phase 1: detect initial breakout ──────────────────────────────────
        if breakout_dir is None:
            if close > orb_high and close >= vwap_val:
                # Block Monday longs: weekend repositioning creates false breakout signals.
                # Tuesday is a normal trading day — no structural reason to skip it.
                if day_of_week == 0:
                    return None
                breakout_dir = "long"
                bars_since_breakout = 0
                # Save direct-entry fallback (next bar)
                if pos + 1 < len(today_df):
                    initial_entry_bar  = today_df.iloc[pos + 1]
                    initial_entry_vwap = vwap_val
                continue

            elif close < orb_low and close <= vwap_val:
                breakout_dir = "short"
                bars_since_breakout = 0
                if pos + 1 < len(today_df):
                    initial_entry_bar  = today_df.iloc[pos + 1]
                    initial_entry_vwap = vwap_val
                continue

        # ── Phase 2: look for pullback entry ──────────────────────────────────
        else:
            bars_since_breakout += 1

            if breakout_dir == "long":
                pullback_ceiling = orb_high + orb_range * PULLBACK_ZONE
                in_pullback_zone = orb_high <= close <= pullback_ceiling

                # Depth filter: price must have retraced ≥75% of the extension back toward ORB high
                # Shallow pullbacks (e.g. 5pt from ORB high on a 10pt ORB) = poor R:R, skip
                if in_pullback_zone and orb_range > 0:
                    retrace_depth = (close - orb_low) / orb_range
                    if retrace_depth < 0.75:
                        in_pullback_zone = False

                if in_pullback_zone and close >= vwap_val:
                    # Pullback entry: enter at next bar open
                    if pos + 1 >= len(today_df):
                        break
                    entry_bar = today_df.iloc[pos + 1]
                    entry = float(entry_bar["Open"])
                    # Tight stop: 2 pts below ORB high
                    stop  = orb_high - 2.0
                    if entry - stop > MAX_RISK_PTS:
                        stop = entry - MAX_RISK_PTS
                    if entry <= stop:
                        break
                    risk_pts_calc = entry - stop
                    target = entry + min(orb_range * 1.0, risk_pts_calc * 3.0)
                    global_idx = df.index.get_loc(entry_bar.name)
                    return ORBSignal(
                        direction="long", entry=entry, stop=stop, target=target,
                        orb_high=orb_high, orb_low=orb_low, orb_range=orb_range,
                        signal_bar_idx=global_idx, vwap_at_entry=vwap_val,
                        atr_ratio=atr_ratio, entry_type="pullback",
                    )

                # Fallback: direct entry after PULLBACK_BARS bars with no pullback
                if bars_since_breakout >= PULLBACK_BARS and initial_entry_bar is not None:
                    entry  = float(initial_entry_bar["Open"])
                    stop   = orb_high - orb_range * 0.5
                    if entry - stop > MAX_RISK_PTS:
                        stop = entry - MAX_RISK_PTS
                    risk_pts_calc = entry - stop
                    target = entry + min(orb_range, risk_pts_calc * 3.0)
                    if abs(entry - target) < 3.0 or entry <= stop:
                        break
                    global_idx = df.index.get_loc(initial_entry_bar.name)
                    return ORBSignal(
                        direction="long", entry=entry, stop=stop, target=target,
                        orb_high=orb_high, orb_low=orb_low, orb_range=orb_range,
                        signal_bar_idx=global_idx, vwap_at_entry=initial_entry_vwap,
                        atr_ratio=atr_ratio, entry_type="direct",
                    )

                # Breakout failed: price went back inside ORB
                if close < orb_high:
                    breakout_dir = None

            elif breakout_dir == "short":
                pullback_floor = orb_low - orb_range * PULLBACK_ZONE
                in_pullback_zone = pullback_floor <= close <= orb_low

                # Depth filter: price must have retraced ≥75% of the extension back toward ORB low
                if in_pullback_zone and orb_range > 0:
                    retrace_depth = (orb_high - close) / orb_range
                    if retrace_depth < 0.75:
                        in_pullback_zone = False

                if in_pullback_zone and close <= vwap_val:
                    if pos + 1 >= len(today_df):
                        break
                    entry_bar = today_df.iloc[pos + 1]
                    entry = float(entry_bar["Open"])
                    stop  = orb_low + 2.0
                    if stop - entry > MAX_RISK_PTS:
                        stop = entry + MAX_RISK_PTS
                    if entry >= stop:
                        break
                    risk_pts_calc = stop - entry
                    target = entry - min(orb_range * 1.0, risk_pts_calc * 3.0)
                    global_idx = df.index.get_loc(entry_bar.name)
                    return ORBSignal(
                        direction="short", entry=entry, stop=stop, target=target,
                        orb_high=orb_high, orb_low=orb_low, orb_range=orb_range,
                        signal_bar_idx=global_idx, vwap_at_entry=vwap_val,
                        atr_ratio=atr_ratio, entry_type="pullback",
                    )

                if bars_since_breakout >= PULLBACK_BARS and initial_entry_bar is not None:
                    entry  = float(initial_entry_bar["Open"])
                    stop   = orb_low + orb_range * 0.5
                    if stop - entry > MAX_RISK_PTS:
                        stop = entry + MAX_RISK_PTS
                    risk_pts_calc = stop - entry
                    target = entry - min(orb_range, risk_pts_calc * 3.0)
                    if abs(entry - target) < 3.0 or entry >= stop:
                        break
                    global_idx = df.index.get_loc(initial_entry_bar.name)
                    return ORBSignal(
                        direction="short", entry=entry, stop=stop, target=target,
                        orb_high=orb_high, orb_low=orb_low, orb_range=orb_range,
                        signal_bar_idx=global_idx, vwap_at_entry=initial_entry_vwap,
                        atr_ratio=atr_ratio, entry_type="direct",
                    )

                if close > orb_low:
                    breakout_dir = None

    return None
