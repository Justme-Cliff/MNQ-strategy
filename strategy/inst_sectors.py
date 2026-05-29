"""
XLK/SPY Relative Strength — Tech Sector Institutional Flow.

NQ is a tech-heavy index (top 10 = ~50% of weight). When institutions
rotate INTO tech (XLK outperforms SPY), NQ longs have a tailwind.
When rotating OUT, NQ longs face a headwind.

Data: XLK + SPY daily closes — free via yfinance.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf


def _load_etf_closes(ticker: str, period: str = "60d") -> pd.Series:
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if hist.empty:
            return pd.Series(dtype=float)
        result = {}
        for ts, row in hist.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        return pd.Series(result).sort_index()
    except Exception:
        return pd.Series(dtype=float)


def get_tech_sector_bias(
    today: date,
    xlk_closes: Optional[pd.Series] = None,
    spy_closes: Optional[pd.Series] = None,
    sma_period: int = 10,
) -> dict:
    """
    XLK/SPY relative strength ratio vs. its 10-day SMA.

    Returns:
      rs_ratio      : float  — XLK price / SPY price
      rs_vs_sma     : float  — % above/below 10d SMA
      bias          : "bullish" | "neutral" | "bearish"
      xlk_daily_ret : float  — today's XLK daily return
      spy_daily_ret : float  — today's SPY daily return
      tech_vs_market: float  — xlk_daily_ret - spy_daily_ret (sector alpha)
      long_favored  : bool
      short_favored : bool
      available     : bool
    """
    default = {
        "rs_ratio": 0.0, "rs_vs_sma": 0.0, "bias": "neutral",
        "xlk_daily_ret": 0.0, "spy_daily_ret": 0.0, "tech_vs_market": 0.0,
        "long_favored": False, "short_favored": False, "available": False,
    }

    if xlk_closes is None:
        xlk_closes = _load_etf_closes("XLK")
    if spy_closes is None:
        spy_closes = _load_etf_closes("SPY")

    if xlk_closes.empty or spy_closes.empty:
        return default

    # Align on common dates up to (not including) today
    common = sorted(set(xlk_closes.index) & set(spy_closes.index))
    common = [d for d in common if d < today]
    if len(common) < sma_period + 1:
        return default

    xlk = xlk_closes.reindex(common)
    spy = spy_closes.reindex(common)

    ratio = (xlk / spy).dropna()
    if len(ratio) < sma_period:
        return default

    current_ratio = float(ratio.iloc[-1])
    sma = float(ratio.tail(sma_period).mean())
    rs_vs_sma = (current_ratio / sma - 1.0) if sma > 0 else 0.0

    # Today's returns (prior close vs prior-prior close)
    xlk_ret = float((xlk.iloc[-1] / xlk.iloc[-2]) - 1.0) if len(xlk) >= 2 else 0.0
    spy_ret = float((spy.iloc[-1] / spy.iloc[-2]) - 1.0) if len(spy) >= 2 else 0.0
    sector_alpha = xlk_ret - spy_ret

    # Bias classification
    if rs_vs_sma > 0.005:         # XLK 0.5%+ above SMA → tech leading
        bias = "bullish"
        long_favored = True
        short_favored = False
    elif rs_vs_sma < -0.010:      # XLK 1%+ below SMA → rotating out
        bias = "bearish"
        long_favored = False
        short_favored = True
    else:
        bias = "neutral"
        long_favored = False
        short_favored = False

    # Same-day sector alpha override: if tech is clearly selling today, block longs
    if sector_alpha < -0.010:     # tech -1% vs market → hard headwind
        long_favored = False
        short_favored = True
        bias = "bearish"
    elif sector_alpha > 0.010:    # tech +1% vs market → strong tailwind
        long_favored = True
        short_favored = False
        if bias == "neutral":
            bias = "bullish"

    return {
        "rs_ratio":       current_ratio,
        "rs_vs_sma":      rs_vs_sma,
        "bias":           bias,
        "xlk_daily_ret":  xlk_ret,
        "spy_daily_ret":  spy_ret,
        "tech_vs_market": sector_alpha,
        "long_favored":   long_favored,
        "short_favored":  short_favored,
        "available":      True,
    }


# Module-level cache to avoid re-fetching within a session
_xlk_cache: Optional[pd.Series] = None
_spy_cache: Optional[pd.Series] = None


def load_sector_data(period: str = "60d") -> tuple[pd.Series, pd.Series]:
    """Load and cache XLK + SPY closes."""
    global _xlk_cache, _spy_cache
    if _xlk_cache is None:
        _xlk_cache = _load_etf_closes("XLK", period)
    if _spy_cache is None:
        _spy_cache = _load_etf_closes("SPY", period)
    return _xlk_cache, _spy_cache
