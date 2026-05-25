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
