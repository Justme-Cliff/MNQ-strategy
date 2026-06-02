"""
Absorption Detection — Wyckoff Effort vs. Result.

Richard Wyckoff's Law: if a large effort (high volume) produces a small result
(narrow price range), the opposing side is absorbing. Large limit orders are sitting
at that level eating every market order.

Conditions for absorption:
  1. Volume > 1.8x rolling average (large effort)
  2. Bar range < 40% of average range (small result)
  3. Body < 30% of bar range (close near midpoint)

Direction:
  sell_side: close near top of bar = sellers absorbing buying (at resistance)
  buy_side:  close near bottom = buyers absorbing selling (at support)

Documented edge: stop entering INTO sell-side absorption (don't buy into a wall),
don't short into buy-side absorption.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def detect_absorption(
    today_df: pd.DataFrame,
    bar_pos: int,
    atr: float,
    lookback: int = 20,
) -> dict:
    """
    Detect institutional absorption (Wyckoff effort vs result).

    Returns:
      absorbed     : bool
      direction    : "buy_side" | "sell_side" | "neutral"
                     buy_side  = buyers absorbed selling  (at support — don't short into it)
                     sell_side = sellers absorbed buying  (at resistance — don't buy into it)
      strength     : float 0–1
      vol_ratio    : float
      range_ratio  : float
    """
    _default = {
        "absorbed": False, "direction": "neutral",
        "strength": 0.0, "vol_ratio": 1.0, "range_ratio": 1.0,
    }

    try:
        if bar_pos < lookback or atr <= 0:
            return _default

        window = today_df.iloc[max(0, bar_pos - lookback): bar_pos]
        if len(window) < 5:
            return _default

        avg_vol   = float(window["Volume"].mean())
        avg_range = float((window["High"] - window["Low"]).mean())

        if avg_vol < 1.0 or avg_range < 0.1:
            return _default

        cur = today_df.iloc[bar_pos]
        cur_vol   = float(cur["Volume"])
        cur_range = float(cur["High"] - cur["Low"])
        cur_open  = float(cur["Open"])
        cur_close = float(cur["Close"])
        cur_high  = float(cur["High"])
        cur_low   = float(cur["Low"])

        vol_ratio   = cur_vol / avg_vol
        range_ratio = cur_range / avg_range if avg_range > 0 else 1.0

        body     = abs(cur_close - cur_open)
        body_pct = body / cur_range if cur_range > 0 else 1.0

        high_vol   = vol_ratio > 1.8
        narrow_rng = range_ratio < 0.40
        near_mid   = body_pct < 0.30

        absorbed = high_vol and narrow_rng and near_mid

        if cur_range > 0:
            close_pos = (cur_close - cur_low) / cur_range
        else:
            close_pos = 0.5

        if close_pos > 0.65:
            direction = "sell_side"   # close near top = sellers winning = resistance
        elif close_pos < 0.35:
            direction = "buy_side"    # close near bottom = buyers winning = support
        else:
            direction = "neutral"

        strength = 0.0
        if absorbed:
            strength = min(1.0, (vol_ratio / 3.0) * (1.0 - range_ratio) * (1.0 - body_pct))

        return {
            "absorbed":    absorbed,
            "direction":   direction,
            "strength":    strength,
            "vol_ratio":   vol_ratio,
            "range_ratio": range_ratio,
        }

    except Exception:
        return _default
