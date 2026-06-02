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
_smh_cache: Optional[pd.Series] = None


def load_sector_data(period: str = "60d") -> tuple[pd.Series, pd.Series]:
    """Load and cache XLK + SPY closes."""
    global _xlk_cache, _spy_cache
    if _xlk_cache is None:
        _xlk_cache = _load_etf_closes("XLK", period)
    if _spy_cache is None:
        _spy_cache = _load_etf_closes("SPY", period)
    return _xlk_cache, _spy_cache


def load_smh_data(period: str = "60d") -> pd.Series:
    """Load and cache SMH (semiconductor ETF) closes."""
    global _smh_cache
    if _smh_cache is None:
        _smh_cache = _load_etf_closes("SMH", period)
    return _smh_cache


def get_smh_lead_signal(
    today: date,
    smh_closes: Optional[pd.Series] = None,
    qqq_closes: Optional[pd.Series] = None,
    vxn: float = 20.0,
    slope_bars: int = 6,
) -> dict:
    """
    SMH/QQQ 6-bar relative strength slope as NQ breadth confirmation.

    Semis (NVDA, AMD, AVGO, TSM) = 20-25% of QQQ weight. When semis
    diverge FROM NQ, the move has weak institutional backing.

    Only reliable when VXN 15-30. Above 30, macro dominates.

    Returns:
      smh_rs_slope : float  — recent RS trend (positive = SMH leading)
      signal       : "confirming" | "diverging" | "neutral"
      long_boost   : bool — semis confirm long direction
      short_boost  : bool — semis confirm short direction
      available    : bool
    """
    default = {
        "smh_rs_slope": 0.0, "signal": "neutral",
        "long_boost": False, "short_boost": False, "available": False,
    }

    try:
        # Only meaningful when VXN is in normal range
        if vxn > 30.0 or vxn < 12.0:
            return default

        if smh_closes is None:
            smh_closes = _load_etf_closes("SMH")
        if qqq_closes is None:
            qqq_closes = _load_etf_closes("QQQ")

        if smh_closes.empty or qqq_closes.empty:
            return default

        common = sorted(set(smh_closes.index) & set(qqq_closes.index))
        common = [d for d in common if d < today]
        if len(common) < slope_bars + 2:
            return default

        smh = smh_closes.reindex(common).tail(slope_bars + 2)
        qqq = qqq_closes.reindex(common).tail(slope_bars + 2)

        rs = (smh / qqq).dropna()
        if len(rs) < slope_bars:
            return default

        # Linear slope of RS over last slope_bars bars
        y = rs.values[-slope_bars:]
        x = np.arange(slope_bars, dtype=float)
        slope = float(np.polyfit(x, y, 1)[0])

        # Normalized by mean RS to get % slope per bar
        mean_rs = float(np.mean(y))
        norm_slope = slope / (mean_rs + 1e-8)

        if norm_slope > 0.0003:   # SMH leading
            signal = "confirming"
            long_boost  = True
            short_boost = False
        elif norm_slope < -0.0003:  # SMH lagging
            signal = "diverging"
            long_boost  = False
            short_boost = True
        else:
            signal = "neutral"
            long_boost  = False
            short_boost = False

        return {
            "smh_rs_slope": norm_slope,
            "signal":       signal,
            "long_boost":   long_boost,
            "short_boost":  short_boost,
            "available":    True,
        }

    except Exception:
        return default
