"""
VPIN — Volume-Synchronized Probability of Informed Trading.

Easley, Lopez de Prado & O'Hara (2012, JFE).
Buy volume proxy: Lee-Ready approximation from OHLCV.
  buy_vol_i = vol_i * (close_i - low_i) / (high_i - low_i)

VPIN over N volume buckets:
  VPIN = mean(|buy_vol_bucket - sell_vol_bucket|) / bucket_size

Interpretation:
  > 0.65 → high informed order flow → mean-reversion setups are risky
            (informed traders are pushing price away from value)
  < 0.45 → low toxicity → mean-reversion is safe
  0.45–0.65 → neutral

Application:
  For MEAN-REVERSION trades (VWAP, FVG, IB): gate_active if VPIN > 0.65 → SKIP
  For BREAKOUT trades (ORB, Gap): informed flow can help → VPIN high is OK
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

VPIN_THRESHOLD  = 0.65
MEAN_REV_STRATS = {"vwap_rev", "fvg", "ib_breakout"}


def _buy_vol_proxy(df: pd.DataFrame) -> np.ndarray:
    """Lee-Ready buy volume proxy from OHLCV."""
    vol   = df["Volume"].values.astype(float)
    high  = df["High"].values.astype(float)
    low   = df["Low"].values.astype(float)
    close = df["Close"].values.astype(float)
    spread = np.where(high - low == 0, 1e-8, high - low)
    return vol * (close - low) / spread


def compute_vpin(today_df: pd.DataFrame, n_buckets: int = 10) -> float:
    """
    Compute session VPIN using `n_buckets` equal-volume buckets.
    Returns float in [0, 1].
    """
    if len(today_df) < 4:
        return 0.5

    vol      = today_df["Volume"].values.astype(float)
    total_vol = float(vol.sum())
    if total_vol < 1:
        return 0.5

    buy_vol  = _buy_vol_proxy(today_df)
    sell_vol = vol - buy_vol

    bucket_size = total_vol / n_buckets
    imbalances  = []
    b_buy = b_sell = b_vol = 0.0

    for i in range(len(today_df)):
        bar_total = buy_vol[i] + sell_vol[i]
        if bar_total == 0:
            continue
        remaining = bar_total
        while remaining > 1e-6:
            space = bucket_size - b_vol
            fill  = min(remaining, space)
            frac  = buy_vol[i] / bar_total
            b_buy  += fill * frac
            b_sell += fill * (1 - frac)
            b_vol  += fill
            remaining -= fill
            if b_vol >= bucket_size - 1e-6:
                imbalances.append(abs(b_buy - b_sell) / bucket_size)
                b_buy = b_sell = b_vol = 0.0

    if not imbalances:
        return 0.5

    return float(np.mean(imbalances[-n_buckets:]))


def get_vpin_gate(
    today_df: pd.DataFrame,
    bar_pos: int,
    strategy: str,
    threshold: float = VPIN_THRESHOLD,
) -> dict:
    """
    Gate a trade based on VPIN and strategy type.

    strategy: strategy name string (e.g. "vwap_rev", "orb")

    Returns:
      vpin           : float
      flow_direction : "buy" | "sell" | "balanced"
      gate_active    : bool — True = SKIP this mean-reversion trade
    """
    if bar_pos < 4:
        return {"vpin": 0.5, "flow_direction": "balanced", "gate_active": False}

    window = today_df.iloc[: bar_pos + 1]
    vpin   = compute_vpin(window)

    # Flow direction from last 5 bars
    recent   = today_df.iloc[max(0, bar_pos - 5): bar_pos + 1]
    buy_v    = float(_buy_vol_proxy(recent).sum())
    total_v  = float(recent["Volume"].sum())
    sell_v   = total_v - buy_v

    if buy_v > sell_v * 1.2:
        flow_dir = "buy"
    elif sell_v > buy_v * 1.2:
        flow_dir = "sell"
    else:
        flow_dir = "balanced"

    # Only gate mean-reversion strategies on high VPIN
    is_mean_rev = strategy in MEAN_REV_STRATS
    gate_active = is_mean_rev and vpin > threshold

    return {
        "vpin":           vpin,
        "flow_direction": flow_dir,
        "gate_active":    gate_active,
    }
