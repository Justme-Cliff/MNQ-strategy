"""
GEX Proxy — Gamma Exposure via VXN/VIX Ratio.

Real GEX needs options chain data (not free). Proxy: VXN (Nasdaq vol) / VIX (SPX vol).

Research basis (NQ intraday studies, SpotGamma analytics):
  VXN/VIX > 1.10 → NQ options are bid hard vs. SPX
                    → dealers are long gamma → they hedge by selling rallies / buying dips
                    → mean-reversion bias (price pinned)
  VXN/VIX < 0.95 → NQ vol compressed vs. SPX
                    → dealers are short gamma → they hedge by chasing price
                    → breakout/momentum bias (moves extend)
  0.95–1.10      → neutral; all strategies valid

Application in engine:
  "mean_rev" bias → VWAP Rev, FVG, IB Breakout preferred; ORB on caution
  "breakout" bias → ORB, Gap Fill preferred; VWAP/FVG/IB on caution
  "neutral"       → all strategies normal weight
"""
from __future__ import annotations
import yfinance as yf
import pandas as pd
from datetime import date, timedelta

GEX_HIGH = 1.10
GEX_LOW  = 0.95

MEAN_REV_FAVORED  = {"vwap_rev", "fvg", "ib_breakout"}
BREAKOUT_FAVORED  = set()   # GEX doesn't block breakout strats — trend filter handles that


def load_vxn(period: str = "90d") -> dict[date, float]:
    """Download ^VXN daily closes."""
    try:
        vxn = yf.Ticker("^VXN").history(period=period, interval="1d", auto_adjust=True)
        if vxn.empty:
            return {}
        result: dict[date, float] = {}
        for ts, row in vxn.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        return result
    except Exception:
        return {}


def _closest(cache: dict[date, float], d: date) -> float:
    if d in cache:
        return cache[d]
    for lag in range(1, 6):
        prev = d - timedelta(days=lag)
        if prev in cache:
            return cache[prev]
    return 0.0


def compute_gex_proxy(
    vix_cache: dict[date, float],
    vxn_cache: dict[date, float],
    today: date,
) -> dict:
    """
    Returns:
      ratio     : float  — VXN/VIX
      bias      : "mean_rev" | "breakout" | "neutral"
      vix       : float
      vxn       : float
      available : bool — False if either index missing
    """
    vix = _closest(vix_cache, today)
    vxn = _closest(vxn_cache, today)

    if vix < 0.1 or vxn < 0.1:
        return {"ratio": 1.0, "bias": "neutral", "vix": vix, "vxn": vxn, "available": False}

    ratio = vxn / vix
    if ratio > GEX_HIGH:
        bias = "mean_rev"
    elif ratio < GEX_LOW:
        bias = "breakout"
    else:
        bias = "neutral"

    return {"ratio": ratio, "bias": bias, "vix": vix, "vxn": vxn, "available": True}


def gex_strategy_ok(gex: dict, strategy: str) -> bool:
    """
    Returns False if GEX bias strongly opposes the strategy type.
    Mean-rev bias blocks breakout strategies and vice versa.
    """
    bias = gex.get("bias", "neutral")
    if bias == "mean_rev" and strategy in BREAKOUT_FAVORED:
        return False
    if bias == "breakout" and strategy in MEAN_REV_FAVORED:
        return False
    return True
