"""
Market Structure Shift (MSS) detection.

After a liquidity sweep of the Asia range, we wait for price to create a
new swing high/low in the opposite direction and then break through it.

Bullish MSS: after sweeping Asia Low → price closes ABOVE a recent swing high.
Bearish MSS: after sweeping Asia High → price closes BELOW a recent swing low.
"""
from __future__ import annotations
import pandas as pd
import numpy as np


def _swing_highs(highs: pd.Series, strength: int = 2) -> pd.Series:
    """Returns a boolean Series where True = confirmed swing high."""
    result = pd.Series(False, index=highs.index)
    for i in range(strength, len(highs) - strength):
        window = highs.iloc[i - strength : i + strength + 1]
        if highs.iloc[i] == window.max():
            result.iloc[i] = True
    return result


def _swing_lows(lows: pd.Series, strength: int = 2) -> pd.Series:
    """Returns a boolean Series where True = confirmed swing low."""
    result = pd.Series(False, index=lows.index)
    for i in range(strength, len(lows) - strength):
        window = lows.iloc[i - strength : i + strength + 1]
        if lows.iloc[i] == window.min():
            result.iloc[i] = True
    return result


def detect_mss(
    df: pd.DataFrame,
    sweep_bar_idx: int,
    direction: str,
    lookback: int = 20,
    pivot_strength: int = 2,
) -> dict:
    """
    Given a DataFrame slice and the index of the sweep bar,
    detect if a Market Structure Shift occurs in the following bars.

    direction: "bullish" (swept Asia Low, expect price to reverse up)
               "bearish" (swept Asia High, expect price to reverse down)

    Returns:
        {
            "detected": bool,
            "mss_bar_idx": int | None,
            "break_level": float | None,
        }
    """
    closes = df["Close"] if "Close" in df.columns else df["close"]
    highs = df["High"] if "High" in df.columns else df["high"]
    lows = df["Low"] if "Low" in df.columns else df["low"]

    search_start = sweep_bar_idx + 1
    search_end = min(sweep_bar_idx + lookback + 1, len(df))

    if search_start >= len(df):
        return {"detected": False, "mss_bar_idx": None, "break_level": None}

    # MSS = price closes above (bullish) / below (bearish) the highest/lowest high/low
    # of the last `pivot_strength` bars AFTER the sweep.
    # This detects the first real structural break after a liquidity grab.

    if direction == "bullish":
        for i in range(search_start, search_end):
            # Look at highest high in the last `pivot_strength` bars since the sweep
            window_start = max(sweep_bar_idx, i - pivot_strength)
            recent_high = float(highs.iloc[window_start:i].max()) if i > window_start else float(highs.iloc[sweep_bar_idx])
            if float(closes.iloc[i]) > recent_high and float(closes.iloc[i]) > float(closes.iloc[i - 1]):
                return {"detected": True, "mss_bar_idx": i, "break_level": recent_high}

    else:  # bearish
        for i in range(search_start, search_end):
            window_start = max(sweep_bar_idx, i - pivot_strength)
            recent_low = float(lows.iloc[window_start:i].min()) if i > window_start else float(lows.iloc[sweep_bar_idx])
            if float(closes.iloc[i]) < recent_low and float(closes.iloc[i]) < float(closes.iloc[i - 1]):
                return {"detected": True, "mss_bar_idx": i, "break_level": recent_low}

    return {"detected": False, "mss_bar_idx": None, "break_level": None}
