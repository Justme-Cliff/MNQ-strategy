"""
Order Block detection.

ICT/TJR concept: An order block is the last opposing candle before a displacement
move. It marks where institutions filled large orders. Price almost always returns
to that zone (retracement) before continuing in the new direction.

For LONG setups: last bearish candle body before the bullish MSS displacement.
For SHORT setups: last bullish candle body before the bearish MSS displacement.

Entry at the order block gives tighter stops and better R:R than the fixed
"stop + 25 points" placeholder.
"""
from __future__ import annotations
import pandas as pd


def find_order_block(
    df: pd.DataFrame,
    sweep_bar_idx: int,
    mss_bar_idx: int,
    direction: str,
    min_body_points: float = 3.0,
) -> dict | None:
    """
    Find the order block in the range [sweep_bar_idx, mss_bar_idx).

    direction: "long" or "short"

    Returns dict or None if no valid OB found:
        ob_high       : float — top of OB body
        ob_low        : float — bottom of OB body
        ob_wick_high  : float — candle high (for stop placement)
        ob_wick_low   : float — candle low  (for stop placement)
        ob_bar_idx    : int
        entry         : float — ideal limit entry price
        stop          : float — stop level beyond OB wick
        stop_distance : float — points between entry and stop
    """
    if mss_bar_idx <= sweep_bar_idx:
        return None

    opens  = df["Open"]  if "Open"  in df.columns else df["open"]
    closes = df["Close"] if "Close" in df.columns else df["close"]
    highs  = df["High"]  if "High"  in df.columns else df["high"]
    lows   = df["Low"]   if "Low"   in df.columns else df["low"]

    ob_bar = None

    if direction == "long":
        # Last bearish candle (close < open) between sweep and MSS
        for i in range(sweep_bar_idx, mss_bar_idx):
            o = float(opens.iloc[i])
            c = float(closes.iloc[i])
            if c < o and (o - c) >= min_body_points:
                ob_bar = i

        if ob_bar is None:
            return None

        o = float(opens.iloc[ob_bar])
        c = float(closes.iloc[ob_bar])
        ob_high = o     # bearish candle: open is top of body
        ob_low  = c     # close is bottom of body
        wick_high = float(highs.iloc[ob_bar])
        wick_low  = float(lows.iloc[ob_bar])

        entry = round(ob_high, 2)           # enter when price retraces into OB top
        stop  = round(wick_low - 1.0, 2)   # stop below the full OB wick

    else:  # short
        # Last bullish candle (close > open) between sweep and MSS
        for i in range(sweep_bar_idx, mss_bar_idx):
            o = float(opens.iloc[i])
            c = float(closes.iloc[i])
            if c > o and (c - o) >= min_body_points:
                ob_bar = i

        if ob_bar is None:
            return None

        o = float(opens.iloc[ob_bar])
        c = float(closes.iloc[ob_bar])
        ob_high = c     # bullish candle: close is top of body
        ob_low  = o     # open is bottom of body
        wick_high = float(highs.iloc[ob_bar])
        wick_low  = float(lows.iloc[ob_bar])

        entry = round(ob_low, 2)             # enter when price retraces into OB bottom
        stop  = round(wick_high + 1.0, 2)  # stop above the full OB wick

    stop_distance = round(abs(entry - stop), 2)

    return {
        "ob_high":       round(ob_high, 2),
        "ob_low":        round(ob_low, 2),
        "ob_wick_high":  round(wick_high, 2),
        "ob_wick_low":   round(wick_low, 2),
        "ob_bar_idx":    ob_bar,
        "entry":         entry,
        "stop":          stop,
        "stop_distance": stop_distance,
    }
