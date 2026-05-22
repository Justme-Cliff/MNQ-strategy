"""
Fair Value Gap (FVG) detection.

A bullish FVG is a 3-candle pattern where candle[i-2].high < candle[i].low,
leaving an unfilled gap. Bearish is the inverse.

Entry is when price retraces INTO the FVG zone.
"""
from __future__ import annotations
import pandas as pd


def find_fvgs(
    df: pd.DataFrame,
    direction: str,
    start_idx: int,
    end_idx: int,
    min_size_points: float = 2.0,
) -> list[dict]:
    """
    Scan bars from start_idx to end_idx for FVGs.

    direction: "bullish" or "bearish"

    Returns list of:
        {"top": float, "bottom": float, "bar_idx": int, "filled": bool}
    """
    highs = df["High"] if "High" in df.columns else df["high"]
    lows = df["Low"] if "Low" in df.columns else df["low"]

    fvgs = []
    for i in range(start_idx + 2, min(end_idx + 1, len(df))):
        if direction == "bullish":
            gap_bottom = float(highs.iloc[i - 2])
            gap_top = float(lows.iloc[i])
            if gap_top > gap_bottom and (gap_top - gap_bottom) >= min_size_points:
                fvgs.append({
                    "top": gap_top,
                    "bottom": gap_bottom,
                    "bar_idx": i,
                    "filled": False,
                })
        else:
            gap_top = float(lows.iloc[i - 2])
            gap_bottom = float(highs.iloc[i])
            if gap_top > gap_bottom and (gap_top - gap_bottom) >= min_size_points:
                fvgs.append({
                    "top": gap_top,
                    "bottom": gap_bottom,
                    "bar_idx": i,
                    "filled": False,
                })
    return fvgs


def price_in_fvg(price: float, fvg: dict) -> bool:
    """True if price is inside the FVG zone."""
    return fvg["bottom"] <= price <= fvg["top"]


def get_active_fvg(
    fvgs: list[dict],
    current_price: float,
    direction: str,
) -> dict | None:
    """Return the most recent unfilled FVG that price has entered."""
    for fvg in reversed(fvgs):
        if fvg["filled"]:
            continue
        if direction == "bullish" and price_in_fvg(current_price, fvg):
            return fvg
        if direction == "bearish" and price_in_fvg(current_price, fvg):
            return fvg
    return None


def nearest_fvg(fvgs: list[dict], current_price: float) -> dict | None:
    """Return the closest unfilled FVG regardless of price being inside it."""
    if not fvgs:
        return None
    unfilled = [f for f in fvgs if not f["filled"]]
    if not unfilled:
        return None
    return min(unfilled, key=lambda f: abs(current_price - (f["top"] + f["bottom"]) / 2))
