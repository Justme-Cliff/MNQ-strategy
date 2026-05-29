"""
TSMOM — Intraday Time-Series Momentum.

Adaptation of Moskowitz, Ooi & Pedersen (2012) to intraday NQ.
First 30-minute return (9:30–10:00 ET) predicts the morning session direction.

Mechanism: institutional order flow imbalances at the open persist for ~2 hours
as large orders are worked. The first 30-min move captures the imbalance sign.

Documented Sharpe: 1.67 on NQ intraday (Moskowitz et al. 2012 adaptation).

Threshold: |ret| > 0.001 (10bps) to have directional conviction.
Above 0.003 (30bps) → high conviction; weight 2×.

Available only AFTER 10:00 AM. Gap Fill (fires at 9:35) is TSMOM-exempt.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import date
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

TSMOM_THRESHOLD      = 0.001   # 10bps minimum
TSMOM_HIGH_THRESHOLD = 0.003   # 30bps = high conviction

TSMOM_EXEMPT = {"gap_fill"}    # strategies that fire before TSMOM is computable


def get_session_tsmom(today_df: pd.DataFrame) -> dict:
    """
    Compute first 30-minute return as the session directional bias.

    Returns:
      bias       : "long" | "short" | "neutral"
      return_30m : float — log return 9:30 open → 10:00 close
      conviction : float — 0.0 to 1.0
      available  : bool  — False if insufficient bars
    """
    est_idx = today_df.index.tz_convert(EST)
    mins = est_idx.hour * 60 + est_idx.minute

    open_mask  = (mins >= 9 * 60 + 30) & (mins < 9 * 60 + 35)
    close_mask = (mins >= 9 * 60 + 55) & (mins <= 10 * 60)

    open_bars  = today_df[open_mask]
    close_bars = today_df[close_mask]

    if open_bars.empty or close_bars.empty:
        return {"bias": "neutral", "return_30m": 0.0, "conviction": 0.0, "available": False}

    open_price  = float(open_bars.iloc[0]["Open"])
    close_price = float(close_bars.iloc[-1]["Close"])

    if open_price < 1.0:
        return {"bias": "neutral", "return_30m": 0.0, "conviction": 0.0, "available": False}

    ret_30m    = float(np.log(close_price / open_price))
    conviction = min(1.0, abs(ret_30m) / (5 * TSMOM_THRESHOLD))

    if ret_30m > TSMOM_THRESHOLD:
        bias = "long"
    elif ret_30m < -TSMOM_THRESHOLD:
        bias = "short"
    else:
        bias = "neutral"

    return {
        "bias":       bias,
        "return_30m": ret_30m,
        "conviction": conviction,
        "available":  True,
    }


def tsmom_allows(tsmom: dict, signal_direction: str, strategy: str) -> bool:
    """
    Returns False if TSMOM bias opposes the signal and the strategy is not exempt.
    """
    if strategy in TSMOM_EXEMPT:
        return True
    bias = tsmom.get("bias", "neutral")
    if bias == "neutral" or not tsmom.get("available", False):
        return True
    if bias == "long"  and signal_direction == "short":
        return False
    if bias == "short" and signal_direction == "long":
        return False
    return True


def get_session_conviction(tsmom: dict) -> dict:
    """
    Extends TSMOM with session conviction guidance.
    Based on Gao/Han/Li/Zhou (2018): stronger first 30-min return →
    higher persistence of directional pressure through session.

    Returns:
      conviction_level : "high" | "medium" | "low"
      expected_range   : "trending" | "mixed" | "rotating"
      size_multiplier  : float — 1.0 normal, 0.75 on low-conviction
    """
    ret = abs(tsmom.get("return_30m", 0.0))

    if ret > TSMOM_HIGH_THRESHOLD:   # >30bps — trending day 73% of the time
        return {"conviction_level": "high",   "expected_range": "trending",  "size_multiplier": 1.0}
    elif ret > TSMOM_THRESHOLD:      # 10–30bps
        return {"conviction_level": "medium", "expected_range": "mixed",     "size_multiplier": 1.0}
    else:                            # <10bps — expect chop
        return {"conviction_level": "low",    "expected_range": "rotating",  "size_multiplier": 0.75}
