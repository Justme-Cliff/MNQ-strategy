"""
Anchored VWAP (AVWAP) — Brian Shannon methodology.

Standard VWAP resets every session. Anchored VWAP starts from a meaningful
pivot and represents the average cost basis for all participants since that event.

Key anchors for NQ:
  1. Yearly open  — all year's institutional longs/shorts started here
  2. Last major swing low — cost basis of buyers at the panic bottom
  3. Weekly open  — current week's institutional cost basis

Edge (Brian Shannon, CMT Association 2024):
  "The first one or two touches on AVWAP anchored to an important point
   are more likely to see strong moves."
  When 2+ AVWAPs converge at the same price level = high-conviction support/resistance.

Speed: pure OHLCV computation, no external data, ~1ms per call.
"""
from __future__ import annotations
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

EST = ZoneInfo("America/New_York")

AVWAP_NEAR_ATR_MULT = 0.025   # price within 2.5% of ATR from AVWAP = "near"


def compute_avwap(df: pd.DataFrame, anchor_date: date) -> Optional[pd.Series]:
    """
    Compute Anchored VWAP from anchor_date forward.
    Formula: cumsum(typical_price × volume) / cumsum(volume)
    typical_price = (High + Low + Close) / 3
    """
    try:
        est_idx = df.index.tz_convert(EST)
        mask    = est_idx.date >= anchor_date
        subset  = df[mask]
        if len(subset) < 2:
            return None

        tp  = (subset["High"] + subset["Low"] + subset["Close"]) / 3.0
        tpv = tp * subset["Volume"]
        cum_vol = subset["Volume"].cumsum()
        safe_vol = cum_vol.where(cum_vol > 0, other=1)
        return (tpv.cumsum() / safe_vol).rename("avwap")
    except Exception:
        return None


def _find_yearly_open(df: pd.DataFrame, today: date) -> Optional[date]:
    """First trading bar of the current year."""
    try:
        est_idx = df.index.tz_convert(EST)
        year    = today.year
        year_bars = df[(est_idx.date >= date(year, 1, 1)) &
                       (est_idx.date < today)]
        if year_bars.empty:
            return None
        return year_bars.index[0].astimezone(EST).date()
    except Exception:
        return None


def _find_weekly_open(df: pd.DataFrame, today: date) -> Optional[date]:
    """Monday's first bar of the current ISO week."""
    try:
        est_idx  = df.index.tz_convert(EST)
        dow      = today.weekday()               # 0=Mon
        monday   = today - pd.Timedelta(days=dow)
        week_bars = df[(est_idx.date >= monday) & (est_idx.date < today)]
        if week_bars.empty:
            return None
        return week_bars.index[0].astimezone(EST).date()
    except Exception:
        return None


def _find_swing_low(df: pd.DataFrame, today: date, lookback: int = 60,
                    bounce_pct: float = 0.03) -> Optional[date]:
    """
    Most recent major swing low: rolling 20-session minimum daily close
    with at least `bounce_pct` rally since the low.
    """
    try:
        est_idx   = df.index.tz_convert(EST)
        past      = df[(est_idx.date < today)]
        if past.empty:
            return None

        past_est  = past.index.tz_convert(EST)
        daily_close = (
            past.groupby(past_est.date)["Close"]
            .last()
            .sort_index()
            .tail(lookback)
        )

        if len(daily_close) < 10:
            return None

        min_idx   = daily_close.values.argmin()
        low_date  = daily_close.index[min_idx]
        low_price = float(daily_close.iloc[min_idx])
        latest    = float(daily_close.iloc[-1])

        if latest < low_price * (1 + bounce_pct):
            return None  # not enough bounce from the low

        # Map daily low_date back to first bar of that session
        low_bars = df[est_idx.date == low_date]
        if low_bars.empty:
            return None
        return low_bars.index[0].astimezone(EST).date()

    except Exception:
        return None


def get_avwap_levels(
    df: pd.DataFrame,
    today: date,
    current_price: float,
    atr: float,
) -> dict:
    """
    Compute AVWAP from 3 anchors and check price proximity.

    Returns:
      yearly_avwap   : float | None
      weekly_avwap   : float | None
      swing_avwap    : float | None
      near_avwap     : bool  — price within threshold of any AVWAP
      avwap_support  : bool  — price just above an AVWAP (bullish)
      avwap_resist   : bool  — price just below an AVWAP (bearish)
      confluence     : bool  — 2+ AVWAPs within 5pts of same level
    """
    default = {
        "yearly_avwap": None, "weekly_avwap": None, "swing_avwap": None,
        "near_avwap": False, "avwap_support": False,
        "avwap_resist": False, "confluence": False,
    }

    try:
        tolerance = max(5.0, atr * AVWAP_NEAR_ATR_MULT)

        # --- Compute all 3 AVWAPs ---
        yearly_date = _find_yearly_open(df, today)
        weekly_date = _find_weekly_open(df, today)
        swing_date  = _find_swing_low(df, today)

        def _current_val(series: Optional[pd.Series]) -> Optional[float]:
            if series is None or series.empty:
                return None
            # Get the value at the last bar before 'today'
            est_idx = series.index.tz_convert(EST)
            past    = series[est_idx.date < today]
            if past.empty:
                return None
            return float(past.iloc[-1])

        yearly_val = _current_val(compute_avwap(df, yearly_date)) if yearly_date else None
        weekly_val = _current_val(compute_avwap(df, weekly_date)) if weekly_date else None
        swing_val  = _current_val(compute_avwap(df, swing_date))  if swing_date  else None

        levels = [v for v in [yearly_val, weekly_val, swing_val] if v is not None]

        if not levels:
            return default

        # Proximity checks
        near   = any(abs(current_price - v) <= tolerance for v in levels)
        above  = any(0 < current_price - v <= tolerance for v in levels)  # price just above AVWAP = support
        below  = any(0 < v - current_price <= tolerance for v in levels)  # price just below AVWAP = resistance

        # Confluence: any 2 AVWAPs within 5pts of each other
        confl = False
        for i in range(len(levels)):
            for j in range(i + 1, len(levels)):
                if abs(levels[i] - levels[j]) <= 5.0:
                    confl = True

        return {
            "yearly_avwap": yearly_val,
            "weekly_avwap": weekly_val,
            "swing_avwap":  swing_val,
            "near_avwap":   near,
            "avwap_support": above,
            "avwap_resist":  below,
            "confluence":   confl,
        }

    except Exception:
        return default
