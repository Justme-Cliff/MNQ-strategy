"""
DXY + 10-Year Yield (TNX) — Macro Headwind/Tailwind Gauge.

NQ is a growth/tech index. Two macro variables move it every day:
  DXY (Dollar Index)   — strong dollar → multinational earnings headwind → NQ down
  TNX (10-yr yield)    — rising yields → higher discount rate → tech valuations compress → NQ down

Combined signal: DXY up + TNX up on same day = severe NQ headwind.
Happens 8-12x per 60-day window. On those days, long setups have lower follow-through.

Data: DX-Y.NYB + ^TNX — both free via yfinance daily.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf


def _load_macro_series(ticker: str, period: str = "30d") -> pd.Series:
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


def get_macro_bias(
    today: date,
    dxy_closes: Optional[pd.Series] = None,
    tnx_closes: Optional[pd.Series] = None,
) -> dict:
    """
    Compute prior-day DXY and TNX changes and return NQ macro bias.

    Returns:
      dxy_ret       : float  — prior day DXY % return
      tnx_chg_bps   : float  — prior day 10yr yield change in bps
      dxy_pressure  : "bullish_nq" | "neutral" | "bearish_nq"
      tnx_pressure  : "bullish_nq" | "neutral" | "bearish_nq"
      combined      : "tailwind" | "neutral" | "headwind" | "strong_headwind"
      long_ok       : bool
      short_favored : bool
      available     : bool
    """
    default = {
        "dxy_ret": 0.0, "tnx_chg_bps": 0.0,
        "dxy_pressure": "neutral", "tnx_pressure": "neutral",
        "combined": "neutral", "long_ok": True, "short_favored": False,
        "available": False,
    }

    if dxy_closes is None:
        dxy_closes = _load_macro_series("DX-Y.NYB")
    if tnx_closes is None:
        tnx_closes = _load_macro_series("^TNX")

    past_dxy = dxy_closes[dxy_closes.index < today].tail(2)
    past_tnx = tnx_closes[tnx_closes.index < today].tail(2)

    if len(past_dxy) < 2 or len(past_tnx) < 2:
        return default

    dxy_ret = float((past_dxy.iloc[-1] / past_dxy.iloc[-2]) - 1.0)
    # TNX is a yield (percent), so delta in bps = (today - yesterday) * 100
    tnx_chg_bps = float((past_tnx.iloc[-1] - past_tnx.iloc[-2]) * 100.0)

    # DXY: -0.3%+ weakening = NQ tailwind; +0.3%+ strengthening = headwind
    if dxy_ret < -0.003:
        dxy_p = "bullish_nq"
    elif dxy_ret > 0.003:
        dxy_p = "bearish_nq"
    else:
        dxy_p = "neutral"

    # TNX: yield falling >3bps = NQ tailwind; rising >5bps = headwind
    if tnx_chg_bps < -3.0:
        tnx_p = "bullish_nq"
    elif tnx_chg_bps > 5.0:
        tnx_p = "bearish_nq"
    else:
        tnx_p = "neutral"

    bearish_count = sum(1 for p in [dxy_p, tnx_p] if p == "bearish_nq")
    bullish_count = sum(1 for p in [dxy_p, tnx_p] if p == "bullish_nq")

    if bearish_count == 2:
        combined      = "strong_headwind"
        long_ok       = False
        short_favored = True
    elif bearish_count == 1 and bullish_count == 0:
        combined      = "headwind"
        long_ok       = True
        short_favored = False
    elif bullish_count >= 1:
        combined      = "tailwind"
        long_ok       = True
        short_favored = False
    else:
        combined      = "neutral"
        long_ok       = True
        short_favored = False

    return {
        "dxy_ret":      dxy_ret,
        "tnx_chg_bps":  tnx_chg_bps,
        "dxy_pressure": dxy_p,
        "tnx_pressure": tnx_p,
        "combined":     combined,
        "long_ok":      long_ok,
        "short_favored": short_favored,
        "available":    True,
    }


# Module-level cache
_dxy_cache: Optional[pd.Series] = None
_tnx_cache: Optional[pd.Series] = None


def load_macro_data(period: str = "30d") -> tuple[pd.Series, pd.Series]:
    """Load and cache DXY + TNX closes."""
    global _dxy_cache, _tnx_cache
    if _dxy_cache is None:
        _dxy_cache = _load_macro_series("DX-Y.NYB", period)
    if _tnx_cache is None:
        _tnx_cache = _load_macro_series("^TNX", period)
    return _dxy_cache, _tnx_cache
