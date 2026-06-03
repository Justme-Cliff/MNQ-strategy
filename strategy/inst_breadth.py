"""
Market Breadth — Daily Nasdaq Advance/Decline Bias.

Ideal data: $ADDN (Nasdaq A-D difference) — NOT available via yfinance.
Fallback: QQQ vs IWM relative performance as a breadth proxy.
  When large-cap (QQQ) beats small-cap (IWM) → narrow breadth → weaker signal
  When small-cap (IWM) beats QQQ → broad participation → stronger signal

Also attempts $ADDN and $ADD via yfinance (they occasionally work via ^ADDN / ^ADD).

Thresholds from research:
  $ADDN >  +800: bullish breadth — broad Nasdaq participation
  $ADDN <  -800: bearish breadth — broadly declining
  QQQ/IWM 5-day RS > 1.005: narrow breadth (large-cap only)
  QQQ/IWM 5-day RS < 0.995: broad breadth (small-cap confirming)

Speed: pre-loaded daily from yfinance at session startup. ~0ms during evaluation.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


def _load_series(ticker: str, period: str = "30d") -> pd.Series:
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


def _try_addn(period: str = "30d") -> pd.Series:
    """Attempt to fetch $ADDN from yfinance — often unavailable. Silently skip if missing."""
    import logging, warnings
    # Suppress yfinance 404 noise — these symbols are not available on the free tier
    yf_logger = logging.getLogger("yfinance")
    prev_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)
    try:
        for ticker in ["^ADDN", "^ADD"]:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                s = _load_series(ticker, period)
            if not s.empty:
                return s
    finally:
        yf_logger.setLevel(prev_level)
    return pd.Series(dtype=float)


def _qqq_iwm_breadth(
    qqq_closes: pd.Series,
    iwm_closes: pd.Series,
    today: date,
    window: int = 5,
) -> dict:
    """QQQ/IWM RS ratio as breadth proxy."""
    default = {"rs": 1.0, "bias": "neutral", "broad_up": False, "narrow_up": False}
    try:
        common = sorted(set(qqq_closes.index) & set(iwm_closes.index))
        common = [d for d in common if d < today]
        if len(common) < window + 1:
            return default

        qqq = qqq_closes.reindex(common).iloc[-window:]
        iwm = iwm_closes.reindex(common).iloc[-window:]

        rs = float((qqq.iloc[-1] / qqq.iloc[0]) / (iwm.iloc[-1] / iwm.iloc[0]))

        if rs < 0.995:
            bias = "broad"     # small-cap keeping up → healthy breadth
            broad_up = True
            narrow_up = False
        elif rs > 1.015:
            bias = "narrow"    # only large-cap going up → warning
            broad_up = False
            narrow_up = True
        else:
            bias = "neutral"
            broad_up = False
            narrow_up = False

        return {"rs": rs, "bias": bias, "broad_up": broad_up, "narrow_up": narrow_up}
    except Exception:
        return default


def get_breadth_bias(
    today: date,
    qqq_closes: Optional[pd.Series] = None,
    iwm_closes: Optional[pd.Series] = None,
    addn_series: Optional[pd.Series] = None,
) -> dict:
    """
    Daily breadth bias for NQ.

    Returns:
      source       : "addn" | "qqq_iwm" | "none"
      addn_value   : float | None
      breadth_bias : "bullish" | "bearish" | "neutral"
      long_ok      : bool
      short_favor  : bool
      available    : bool
    """
    default = {
        "source": "none", "addn_value": None,
        "breadth_bias": "neutral", "long_ok": True,
        "short_favor": False, "available": False,
    }

    try:
        # Tier 1: $ADDN if available
        if addn_series is not None and not addn_series.empty:
            past = addn_series[addn_series.index < today]
            if not past.empty:
                val = float(past.iloc[-1])
                if val > 800:
                    bias = "bullish"
                elif val < -800:
                    bias = "bearish"
                else:
                    bias = "neutral"
                return {
                    "source": "addn", "addn_value": val,
                    "breadth_bias": bias,
                    "long_ok": bias != "bearish",
                    "short_favor": bias == "bearish",
                    "available": True,
                }

        # Tier 2: QQQ/IWM RS
        if qqq_closes is not None and iwm_closes is not None:
            brd = _qqq_iwm_breadth(qqq_closes, iwm_closes, today)
            if brd["bias"] != "neutral" or not qqq_closes.empty:
                if brd["bias"] == "broad":
                    bias = "bullish"
                elif brd["bias"] == "narrow":
                    bias = "neutral"   # narrow breadth is caution, not outright bearish
                else:
                    bias = "neutral"
                return {
                    "source": "qqq_iwm", "addn_value": None,
                    "breadth_bias": bias,
                    "long_ok": True,
                    "short_favor": False,
                    "available": True,
                }

        return default

    except Exception:
        return default


# Module-level caches
_qqq_cache:  Optional[pd.Series] = None
_iwm_cache:  Optional[pd.Series] = None
_addn_cache: Optional[pd.Series] = None


def load_breadth_data(period: str = "30d") -> tuple:
    """Load and cache QQQ, IWM closes and attempt $ADDN."""
    global _qqq_cache, _iwm_cache, _addn_cache
    if _qqq_cache is None:
        _qqq_cache  = _load_series("QQQ", period)
        _iwm_cache  = _load_series("IWM", period)
        _addn_cache = _try_addn(period)
    return _qqq_cache, _iwm_cache, _addn_cache
