"""
VWAP 2-Standard-Deviation Reversion — ATR-normalized.

Research basis:
  ES mean reversion (Bollinger Bands, 25-year backtest): 66-67% WR
  With regime filter (VIX < 22 AND ADX < 25): consistent positive expectancy
  Without regime filter: severe drawdowns during trending years

Active only when:
  - EMA trend == "neutral" (EMA8/EMA21 within ±1%)
  - VIX < 22
  - Volatility regime is normal or compressed (not elevated/crisis)

ATR-normalized parameters:
  MIN_DEV = max(5, atr × 0.025)   — minimum deviation to be meaningful signal
  MAX_DEV = min(50, atr × 0.18)   — maximum: beyond this, 10pt stop can't recover
  STOP    = max(8, atr × 0.06)    — proportional stop (scales with vol)

Logic:
  - Buy when price closes below VWAP − 2σ and deviation is within bounds
  - Sell when price closes above VWAP + 2σ
  - Target: VWAP (full mean reversion)
  - Only first signal per direction per session
  - Window: 9:45–11:30 (skip first 15min chaos; stop at noon-ish)
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo
from strategy.quant_regime import session_vwap, vwap_std_bands

EST = ZoneInfo("America/New_York")

SIGNAL_STD = 1.5    # σ bands for signal (was 2.0 — 1.5 fires more often)
STOP_STD   = 2.0    # σ bands for stop


@dataclass
class VWAPSignal:
    direction: str
    entry: float
    stop: float
    target: float
    vwap: float
    deviation_pts: float
    deviation_std: float
    signal_bar_idx: int


def detect_all(
    df: pd.DataFrame,
    today: date,
    vix: float,
    atr: float,
    max_signals: int = 2,
    start_min: int | None = None,   # minutes from midnight; None = 9:45 AM default
    end_min:   int | None = None,   # None = 11:30 AM default
) -> list[VWAPSignal]:
    """
    Detect VWAP reversion signals for today.
    atr: adaptive ATR (max of 5d and 20d) for ATR-normalized thresholds.
    """
    from strategy.quant_regime import vwap_reversion_ok
    if not vwap_reversion_ok(vix):
        return []

    # ATR-normalized deviation bounds
    min_dev = max(5.0,  atr * 0.025)   # at least 2.5% of daily ATR
    max_dev = min(50.0, atr * 0.18)    # at most 18% of daily ATR
    stop_dist = max(8.0, atr * 0.06)   # proportional stop

    est_idx = df.index.tz_convert(EST)
    today_mask = est_idx.date == today
    today_df = df[today_mask].copy()

    if len(today_df) < 10:
        return []

    vwap, upper, lower = vwap_std_bands(today_df, n_std=SIGNAL_STD)

    signals = []
    long_fired  = False
    short_fired = False

    _start = start_min if start_min is not None else 9 * 60 + 45
    _end   = end_min   if end_min   is not None else 11 * 60 + 30

    for pos, (ts, row) in enumerate(today_df.iterrows()):
        dt = ts.astimezone(EST)
        mins = dt.hour * 60 + dt.minute

        if mins < _start:
            continue
        if mins >= _end:
            break

        close    = float(row["Close"])
        vwap_val = float(vwap.iloc[pos])
        lower_val = float(lower.iloc[pos])
        upper_val = float(upper.iloc[pos])

        deviation_pts = abs(close - vwap_val)

        # Deviation bounds: must be meaningful but recoverable within session
        if deviation_pts < min_dev or deviation_pts > max_dev:
            continue

        # Long signal: below -2σ
        if not long_fired and close < lower_val:
            long_fired = True
            if pos + 1 >= len(today_df):
                break
            entry_bar = today_df.iloc[pos + 1]
            entry  = float(entry_bar["Open"])
            stop   = entry - stop_dist
            target = vwap_val
            if abs(entry - target) < 3.0:   # target too close
                continue
            if entry >= target:             # already past target
                continue
            global_idx = df.index.get_loc(entry_bar.name)
            signals.append(VWAPSignal(
                direction="long", entry=entry, stop=stop, target=target,
                vwap=vwap_val, deviation_pts=deviation_pts,
                deviation_std=SIGNAL_STD, signal_bar_idx=global_idx,
            ))
            if len(signals) >= max_signals:
                break

        # Short signal: above +2σ
        elif not short_fired and close > upper_val:
            short_fired = True
            if pos + 1 >= len(today_df):
                break
            entry_bar = today_df.iloc[pos + 1]
            entry  = float(entry_bar["Open"])
            stop   = entry + stop_dist
            target = vwap_val
            if abs(entry - target) < 3.0:
                continue
            if entry <= target:
                continue
            global_idx = df.index.get_loc(entry_bar.name)
            signals.append(VWAPSignal(
                direction="short", entry=entry, stop=stop, target=target,
                vwap=vwap_val, deviation_pts=deviation_pts,
                deviation_std=SIGNAL_STD, signal_bar_idx=global_idx,
            ))
            if len(signals) >= max_signals:
                break

    return signals


def detect_bounce(
    df: pd.DataFrame,
    today: date,
    vix: float,
    atr: float,
    trend_dir: str,
    max_signals: int = 1,
    start_min: int | None = None,
    end_min: int | None = None,
) -> list[VWAPSignal]:
    """
    VWAP bounce — trend continuation when price tests VWAP as support/resistance.

    In bull/strong_bull: price dips to touch VWAP (within ±0.5σ), enter long.
    In bear/strong_bear: price rallies to touch VWAP from below, enter short.
    Target = ATR-based extension (0.08× daily ATR).
    Only fires in trending markets — reversion handles neutral.
    """
    from strategy.quant_regime import vwap_reversion_ok
    if trend_dir not in ("bull", "strong_bull", "bear", "strong_bear"):
        return []
    if not vwap_reversion_ok(vix):
        return []

    est_idx = df.index.tz_convert(EST)
    today_mask = est_idx.date == today
    today_df = df[today_mask].copy()
    if len(today_df) < 10:
        return []

    vwap, upper, lower = vwap_std_bands(today_df, n_std=0.5)

    stop_dist   = max(5.0, atr * 0.03)
    target_dist = max(12.0, atr * 0.08)

    _start = start_min if start_min is not None else 10 * 60      # 10:00 AM
    _end   = end_min   if end_min   is not None else 11 * 60 + 30  # 11:30 AM

    signals: list[VWAPSignal] = []
    fired = False

    for pos, (ts, row) in enumerate(today_df.iterrows()):
        dt   = ts.astimezone(EST)
        mins = dt.hour * 60 + dt.minute
        if mins < _start:
            continue
        if mins >= _end:
            break
        if fired:
            break

        close     = float(row["Close"])
        vwap_val  = float(vwap.iloc[pos])
        lower_val = float(lower.iloc[pos])  # VWAP − 0.5σ
        upper_val = float(upper.iloc[pos])  # VWAP + 0.5σ

        if trend_dir in ("bull", "strong_bull"):
            if lower_val <= close <= upper_val:
                fired = True
                if pos + 1 >= len(today_df):
                    break
                entry_bar = today_df.iloc[pos + 1]
                entry  = float(entry_bar["Open"])
                stop   = entry - stop_dist
                target = entry + target_dist
                if target - entry < 5.0 or entry <= stop:
                    continue
                global_idx = df.index.get_loc(entry_bar.name)
                signals.append(VWAPSignal(
                    direction="long", entry=entry, stop=stop, target=target,
                    vwap=vwap_val, deviation_pts=abs(close - vwap_val),
                    deviation_std=0.5, signal_bar_idx=global_idx,
                ))

        elif trend_dir in ("bear", "strong_bear"):
            if lower_val <= close <= upper_val:
                fired = True
                if pos + 1 >= len(today_df):
                    break
                entry_bar = today_df.iloc[pos + 1]
                entry  = float(entry_bar["Open"])
                stop   = entry + stop_dist
                target = entry - target_dist
                if entry - target < 5.0 or entry >= stop:
                    continue
                global_idx = df.index.get_loc(entry_bar.name)
                signals.append(VWAPSignal(
                    direction="short", entry=entry, stop=stop, target=target,
                    vwap=vwap_val, deviation_pts=abs(close - vwap_val),
                    deviation_std=0.5, signal_bar_idx=global_idx,
                ))

    return signals[:max_signals]
