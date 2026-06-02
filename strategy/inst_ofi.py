"""
OFI — Order Flow Imbalance.

Signed volume proxy (Cont, Kukanov & Stoikov 2014):
  signed_vol_i = vol_i * (2*close_i - high_i - low_i) / (high_i - low_i)
  Positive → net buy pressure; negative → net sell pressure.

Rolling z-score over 20 bars:
  z > +1.5  → strong buy flow   → CONFIRM long, SKIP short
  z < -1.5  → strong sell flow  → CONFIRM short, SKIP long

OFI is one of the highest-R² predictors of 5-min returns in NQ (Cont et al. 2014).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

OFI_WINDOW    = 20
Z_CONFIRM     = 1.5    # |z| > this confirms the trade direction
Z_BLOCK       = 1.5    # opposing z > this blocks the trade


def compute_ofi_series(today_df: pd.DataFrame) -> pd.Series:
    """Signed volume (OFI proxy) for the entire session."""
    vol   = today_df["Volume"].values.astype(float)
    high  = today_df["High"].values.astype(float)
    low   = today_df["Low"].values.astype(float)
    close = today_df["Close"].values.astype(float)
    spread = np.where(high - low == 0, 1e-8, high - low)
    signed = vol * (2 * close - high - low) / spread
    return pd.Series(signed, index=today_df.index)


def get_ofi_zscore(today_df: pd.DataFrame, bar_pos: int, window: int = OFI_WINDOW) -> float:
    """Z-score of OFI at bar_pos vs. trailing `window` bars."""
    if bar_pos < 3:
        return 0.0
    ofi  = compute_ofi_series(today_df)
    data = ofi.iloc[max(0, bar_pos - window): bar_pos + 1]
    if len(data) < 4:
        return 0.0
    std = float(data.std())
    if std < 1e-8:
        return 0.0
    return (float(data.iloc[-1]) - float(data.mean())) / std


def ofi_gate(today_df: pd.DataFrame, bar_pos: int, signal_direction: str) -> dict:
    """
    Gate a trade based on OFI z-score alignment.

    Returns:
      z_score : float
      skip    : bool — True if strong opposing flow
      confirm : bool — True if strong aligned flow
    """
    z = get_ofi_zscore(today_df, bar_pos)

    if signal_direction == "long":
        skip    = z < -Z_BLOCK      # strong sell flow → skip long
        confirm = z >  Z_CONFIRM    # strong buy flow  → confirm long
    else:
        skip    = z >  Z_BLOCK      # strong buy flow  → skip short
        confirm = z < -Z_CONFIRM    # strong sell flow → confirm short

    return {"z_score": z, "skip": skip, "confirm": confirm}


# ── Cumulative Volume Delta (CVD) ─────────────────────────────────────────────

def compute_session_cvd(today_df: pd.DataFrame) -> pd.Series:
    """
    Cumulative session delta: running sum of signed volume from session start.
    Uses the same Lee-Ready proxy as compute_ofi_series(). Resets each session.
    """
    return compute_ofi_series(today_df).cumsum()


def get_cvd_divergence(
    today_df: pd.DataFrame,
    bar_pos: int,
    lookback_bars: int = 10,
) -> dict:
    """
    Detect CVD divergence over the last lookback_bars bars.

    Bearish divergence: price makes higher high, CVD makes lower high
      → institutional distribution hiding in bullish price action
    Bullish divergence: price makes lower low, CVD makes higher low
      → institutional accumulation despite weak price

    Returns:
      divergence     : "bearish" | "bullish" | "none"
      strength       : float — magnitude of divergence
      bars_diverging : int
    """
    if bar_pos < lookback_bars:
        return {"divergence": "none", "strength": 0.0, "bars_diverging": 0}

    start = max(0, bar_pos - lookback_bars)
    window = today_df.iloc[start: bar_pos + 1]
    cvd = compute_session_cvd(today_df).iloc[start: bar_pos + 1]

    if len(window) < 4 or len(cvd) < 4:
        return {"divergence": "none", "strength": 0.0, "bars_diverging": 0}

    price_high_idx = window["High"].values.argmax()
    price_low_idx  = window["Low"].values.argmin()

    cvd_at_price_high = float(cvd.iloc[price_high_idx])
    cvd_at_price_low  = float(cvd.iloc[price_low_idx])
    current_price = float(window["Close"].iloc[-1])
    current_cvd   = float(cvd.iloc[-1])
    price_high    = float(window["High"].max())
    price_low     = float(window["Low"].min())

    # Bearish: price near recent high but CVD has dropped from its high
    if current_price >= price_high * 0.998 and cvd_at_price_high != 0:
        if current_cvd < cvd_at_price_high * 0.90:
            denom = abs(cvd_at_price_high) + 1e-8
            strength = (cvd_at_price_high - current_cvd) / denom
            return {"divergence": "bearish", "strength": float(strength), "bars_diverging": lookback_bars}

    # Bullish: price near recent low but CVD has recovered from its low
    if current_price <= price_low * 1.002 and cvd_at_price_low != 0:
        if current_cvd > cvd_at_price_low * 0.90:
            denom = abs(cvd_at_price_low) + 1e-8
            strength = (current_cvd - cvd_at_price_low) / denom
            return {"divergence": "bullish", "strength": float(strength), "bars_diverging": lookback_bars}

    return {"divergence": "none", "strength": 0.0, "bars_diverging": 0}


# ── CVD Climax / Volume Climax ─────────────────────────────────────────────────

def get_cvd_climax(
    today_df: pd.DataFrame,
    bar_pos: int,
    atr: float,
    vol_lookback: int = 20,
) -> dict:
    """
    Detect buying/selling climax or CVD exhaustion at session extremes.

    Patterns:
      buying:    price at session high + RVOL > 2.5 + CVD at max + next bar lower
      selling:   price at session low  + RVOL > 2.5 + CVD at min + next bar higher
      exhaustion: CVD makes new extreme but price fails to confirm

    Returns:
      climax_type  : "buying" | "selling" | "exhaustion" | "none"
      strength     : float 0-1
      reversal_dir : "short" | "long" | "none"
    """
    _def = {"climax_type": "none", "strength": 0.0, "reversal_dir": "none"}

    try:
        if bar_pos < vol_lookback + 2:
            return _def

        window  = today_df.iloc[max(0, bar_pos - vol_lookback): bar_pos + 1]
        if len(window) < 5:
            return _def

        cvd      = compute_session_cvd(window)
        avg_vol  = float(window["Volume"].mean())
        if avg_vol < 1.0:
            return _def

        cur      = today_df.iloc[bar_pos]
        cur_vol  = float(cur["Volume"])
        cur_high = float(cur["High"])
        cur_low  = float(cur["Low"])
        cur_close = float(cur["Close"])

        rvol      = cur_vol / avg_vol
        sess_high = float(window["High"].max())
        sess_low  = float(window["Low"].min())
        cvd_val   = float(cvd.iloc[-1])
        cvd_max   = float(cvd.max())
        cvd_min   = float(cvd.min())
        cvd_range = abs(cvd_max - cvd_min) + 1e-8

        near_high = cur_high >= sess_high * 0.999
        near_low  = cur_low  <= sess_low  * 1.001

        if bar_pos + 1 >= len(today_df):
            return _def
        next_close = float(today_df.iloc[bar_pos + 1]["Close"])

        if near_high and rvol > 2.5 and cvd_val >= cvd_max * 0.95 and next_close < cur_close:
            str_ = min(1.0, (rvol / 4.0) * 0.5 + 0.5 * (cvd_val - cvd_min) / cvd_range)
            return {"climax_type": "buying", "strength": str_, "reversal_dir": "short"}

        if near_low and rvol > 2.5 and cvd_val <= cvd_min * 0.95 and next_close > cur_close:
            str_ = min(1.0, rvol / 4.0)
            return {"climax_type": "selling", "strength": str_, "reversal_dir": "long"}

        if near_high and cvd_val < cvd_max * 0.80:
            return {"climax_type": "exhaustion", "strength": 0.5, "reversal_dir": "short"}
        if near_low and cvd_val > cvd_min * 0.80 and cvd_min < 0:
            return {"climax_type": "exhaustion", "strength": 0.5, "reversal_dir": "long"}

        return _def

    except Exception:
        return _def
