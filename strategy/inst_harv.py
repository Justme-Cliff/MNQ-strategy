"""
HAR-RV Volatility Forecasting + BNS Jump Detection.

HAR (Heterogeneous Autoregressive Realized Variance):
  RV_t = a + b1*RV_{t-1} + b5*mean(RV_{t-5:t-1}) + b22*mean(RV_{t-22:t-1}) + e

Coefficients from Andersen, Bollerslev & Diebold (2007) — NQ-class assets:
  b1 ~ 0.36, b5 ~ 0.28, b22 ~ 0.28

BNS Jump Test (Barndorff-Nielsen & Shephard 2004):
  RV = sum of squared 5m log returns
  BV = (pi/2) * sum(|r_i| * |r_{i+1}|) * N/(N-1)  — bipower variation
  Jump fraction = (RV - BV) / RV > 0.20 → jump present
  Jump bars: fat-tail risk, stops blow through → skip trade.

Stop multiplier from HAR vol regime:
  extreme → skip day
  high    → 1.30× stop
  normal  → 1.00×
  low     → 0.85×
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import date
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

BNS_THRESHOLD = 0.20   # jump fraction above this = jump detected


def compute_realized_variance(today_df: pd.DataFrame) -> float:
    """Sum of squared 5-min log returns for the session (annualized-style sum)."""
    closes = today_df["Close"].values
    if len(closes) < 2:
        return 0.0
    log_rets = np.diff(np.log(np.clip(closes, 1e-8, None)))
    return float(np.sum(log_rets ** 2))


def _daily_rv_series(df: pd.DataFrame, today: date, lookback: int = 30) -> pd.Series:
    """Build daily RV series for the last `lookback` days before today."""
    est_idx = df.index.tz_convert(EST)
    df2 = df.copy()
    df2["_date"] = est_idx.date
    df2["_log_ret"] = np.log(df2["Close"] / df2["Close"].shift(1).clip(lower=1e-8))
    df2["_lr2"] = df2["_log_ret"] ** 2

    past = df2[df2["_date"] < today]
    if past.empty:
        return pd.Series(dtype=float)

    daily_rv = past.groupby("_date")["_lr2"].sum().sort_index()
    return daily_rv.tail(lookback)


def har_forecast(df: pd.DataFrame, today: date) -> dict:
    """
    HAR-RV forecast for today.

    Returns:
      rv_forecast : float — expected realized variance
      vol_regime  : "low" | "normal" | "high" | "extreme"
      stop_mult   : float — 0.85 / 1.0 / 1.30 / skip
      skip_day    : bool  — True in extreme vol (too dangerous)
    """
    rv_series = _daily_rv_series(df, today, lookback=30)
    default = {"rv_forecast": 0.0, "vol_regime": "normal", "stop_mult": 1.0, "skip_day": False}

    if len(rv_series) < 5:
        return default

    rv_vals = rv_series.values
    rv_1d  = float(rv_vals[-1])
    rv_5d  = float(np.mean(rv_vals[-5:]))
    rv_22d = float(np.mean(rv_vals[-min(22, len(rv_vals)):]))

    # Small positive baseline
    a   = float(np.mean(rv_vals)) * 0.08
    b1  = 0.36
    b5  = 0.28
    b22 = 0.28

    rv_forecast = a + b1 * rv_1d + b5 * rv_5d + b22 * rv_22d

    # Regime: compare forecast to trailing 22-day distribution
    trailing = rv_vals[-min(22, len(rv_vals)):]
    pct = float(np.mean(rv_forecast > trailing))

    if pct > 0.92:
        vol_regime = "extreme"
        stop_mult  = 1.6
        skip_day   = True
    elif pct > 0.72:
        vol_regime = "high"
        stop_mult  = 1.3
        skip_day   = False
    elif pct < 0.20:
        vol_regime = "low"
        stop_mult  = 0.85
        skip_day   = False
    else:
        vol_regime = "normal"
        stop_mult  = 1.0
        skip_day   = False

    return {
        "rv_forecast": rv_forecast,
        "vol_regime":  vol_regime,
        "stop_mult":   stop_mult,
        "skip_day":    skip_day,
    }


def bns_jump_flag(today_df: pd.DataFrame, bar_idx: int, threshold: float = BNS_THRESHOLD) -> bool:
    """
    BNS jump detection on bars [0..bar_idx] in today's session.
    Returns True if a statistically significant jump is present.
    """
    bars = today_df.iloc[: bar_idx + 1]
    if len(bars) < 4:
        return False

    closes = bars["Close"].values
    log_rets = np.diff(np.log(np.clip(closes, 1e-8, None)))

    if len(log_rets) < 3:
        return False

    rv = float(np.sum(log_rets ** 2))
    if rv < 1e-12:
        return False

    # Bipower variation
    bv_sum = float(np.sum(np.abs(log_rets[:-1]) * np.abs(log_rets[1:])))
    n = len(log_rets)
    bv = (np.pi / 2.0) * bv_sum * (n / (n - 1))

    jump_fraction = (rv - bv) / rv
    return jump_fraction > threshold
