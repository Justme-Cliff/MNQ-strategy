"""
Regime classifier — adaptive market state detection for any market condition.

Regime layers:
  1. Volatility:  ATR-percentile based (compressed / normal / elevated / crisis)
  2. Trend:       EMA8/EMA21 cross + slope strength (strong_bull / bull / neutral / bear / strong_bear)
  3. VIX:         Classic low/normal/elevated/high buckets (unchanged from v1)

Strategy gating (which strategies are valid RIGHT NOW):
  ORB             → valid in any regime; ATR-normalized range filter replaces fixed caps
  IB Breakout     → valid in any regime; ATR-normalized range filter
  Gap Fill        → valid in all regimes (tiny gap = institutional, not news)
  VWAP Reversion  → only when trend == neutral AND vol == normal/compressed
  FVG             → valid in ALL regimes (works in crash AND calm)

Direction gating:
  strong_bull     → longs only
  bull            → longs preferred; shorts allowed only on strong FVG/ORB
  neutral         → both directions
  bear            → shorts preferred; longs allowed only on strong FVG/ORB
  strong_bear     → shorts only
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import yfinance as yf

EST = ZoneInfo("America/New_York")


# ── ATR helpers ────────────────────────────────────────────────────────────────

def get_daily_atr(df: pd.DataFrame, today: date, lookback: int = 20) -> float:
    """
    True Range ATR from 5m OHLCV bars grouped into daily ranges.
    Returns the average daily range over `lookback` days before `today`.
    """
    est_idx = df.index.tz_convert(EST)
    df2 = df.copy()
    df2["_date"] = est_idx.date
    past = df2[df2["_date"] < today]
    if past.empty:
        return 200.0
    daily = past.groupby("_date").apply(
        lambda g: float(g["High"].max() - g["Low"].min())
    )
    if len(daily) == 0:
        return 200.0
    return float(daily.tail(lookback).mean())


def get_atr_adaptive(df: pd.DataFrame, today: date) -> float:
    """
    Adaptive ATR: max(ATR_5, ATR_20).
    Takes the LARGER of the recent 5-day and medium 20-day ATR.
    This prevents using stale "normal" ATR during a volatility spike,
    AND prevents using a spike-inflated ATR in a calm recovery.
    The max ensures stops/ranges are never *too* tight for current conditions.
    """
    atr5  = get_daily_atr(df, today, lookback=5)
    atr20 = get_daily_atr(df, today, lookback=20)
    return max(atr5, atr20)


# ── VWAP helpers ───────────────────────────────────────────────────────────────

def session_vwap(today_df: pd.DataFrame) -> pd.Series:
    typical = (today_df["High"] + today_df["Low"] + today_df["Close"]) / 3
    cum_tp_vol = (typical * today_df["Volume"]).cumsum()
    cum_vol = today_df["Volume"].cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap.fillna(typical)


def vwap_std_bands(today_df: pd.DataFrame, n_std: float = 2.0):
    vwap = session_vwap(today_df)
    deviation = today_df["Close"] - vwap
    # Rolling std with min_periods=8: avoids unrealistically tight bands in first few bars
    # expanding() at bar 3 uses only 3 points — fires noise signals early session
    rolling_std = deviation.rolling(window=20, min_periods=8).std().fillna(0)
    upper = vwap + n_std * rolling_std
    lower = vwap - n_std * rolling_std
    return vwap, upper, lower


# ── Trend detection ────────────────────────────────────────────────────────────

def _daily_closes(df: pd.DataFrame, today: date, n: int = 60) -> pd.Series:
    """Return last `n` daily closes strictly before `today`, sorted ascending."""
    est_idx = df.index.tz_convert(EST)
    df2 = df.copy()
    df2["_date"] = est_idx.date
    past = df2[df2["_date"] < today]
    if past.empty:
        return pd.Series(dtype=float)
    closes = past.groupby("_date")["Close"].last().sort_index()
    return closes.tail(n)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def get_ema_trend(df: pd.DataFrame, today: date, fast: int = 8, slow: int = 21) -> dict:
    """
    EMA8/EMA21 crossover trend on daily closes.

    Returns:
      direction : "strong_bull" | "bull" | "neutral" | "bear" | "strong_bear"
      strength  : float — how many % the fast EMA is above/below the slow EMA
      ema_fast  : last fast EMA value
      ema_slow  : last slow EMA value

    Strength thresholds:
      |strength| > 3% → strong trend
      |strength| > 1% → trend
      |strength| ≤ 1% → neutral
    """
    closes = _daily_closes(df, today, n=60)
    if len(closes) < slow + 2:
        return {"direction": "neutral", "strength": 0.0, "ema_fast": 0.0, "ema_slow": 0.0}

    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)

    last_fast = float(fast_ema.iloc[-1])
    last_slow = float(slow_ema.iloc[-1])

    if last_slow == 0:
        return {"direction": "neutral", "strength": 0.0, "ema_fast": last_fast, "ema_slow": last_slow}

    strength = (last_fast - last_slow) / last_slow * 100.0  # % above/below

    _WEAK_TREND   = 1.0   # 1%: minimum to distinguish trend from noise (backtested on 60d)
    _STRONG_TREND = 3.0   # 3%: 3× min threshold, reliably directional

    if strength > _STRONG_TREND:
        direction = "strong_bull"
    elif strength > _WEAK_TREND:
        direction = "bull"
    elif strength < -_STRONG_TREND:
        direction = "strong_bear"
    elif strength < -_WEAK_TREND:
        direction = "bear"
    else:
        direction = "neutral"

    return {
        "direction": direction,
        "strength": strength,
        "ema_fast": last_fast,
        "ema_slow": last_slow,
    }


def get_trend_bias(df: pd.DataFrame, today: date, lookback_days: int = 5) -> str:
    """
    Legacy 5-day price change trend (kept for compatibility).
    Prefer get_ema_trend() for new code.
    """
    closes = _daily_closes(df, today, n=lookback_days + 5)
    if len(closes) < lookback_days + 1:
        return "neutral"
    recent = float(closes.iloc[-1])
    prior  = float(closes.iloc[-(lookback_days + 1)])
    if prior == 0:
        return "neutral"
    pct = (recent - prior) / prior
    if pct < -0.015:
        return "bearish"
    elif pct > 0.015:
        return "bullish"
    return "neutral"


# ── Volatility regime ──────────────────────────────────────────────────────────

def get_volatility_regime(df: pd.DataFrame, today: date) -> str:
    """
    Classify current volatility by comparing recent ATR(5) to medium ATR(60).
    Returns: "compressed" | "normal" | "elevated" | "crisis"

    Thresholds:
      ratio > 2.0  → crisis  (vol more than 2x normal)
      ratio > 1.4  → elevated
      ratio > 0.6  → normal
      ratio ≤ 0.6  → compressed (very low vol, potential breakout setup)
    """
    atr_recent = get_daily_atr(df, today, lookback=5)
    atr_medium = get_daily_atr(df, today, lookback=60)
    if atr_medium == 0:
        return "normal"
    ratio = atr_recent / atr_medium
    if ratio > 2.0:
        return "crisis"
    elif ratio > 1.4:
        return "elevated"
    elif ratio > 0.6:
        return "normal"
    return "compressed"


# ── VIX regime (legacy) ────────────────────────────────────────────────────────

def classify_regime(vix: float) -> str:
    if vix <= 0:
        return "normal"
    if vix < 15:
        return "low"
    if vix < 22:
        return "normal"
    if vix < 30:
        return "elevated"
    return "high"


# ── Direction gating ───────────────────────────────────────────────────────────

def direction_allowed(signal_dir: str, trend: dict, strict: bool = False) -> bool:
    """
    Returns True if `signal_dir` ("long"/"short") is allowed given the EMA trend.

    strict=False (default): blocks signals AGAINST a STRONG trend only.
      → "strong_bull" blocks shorts; "strong_bear" blocks longs; rest = both OK
    strict=True: tighter filter — any confirmed trend blocks the opposite direction.
      → "bull"/"strong_bull" blocks shorts; "bear"/"strong_bear" blocks longs
    """
    d = trend.get("direction", "neutral")
    if strict:
        if signal_dir == "short" and d in ("bull", "strong_bull"):
            return False
        if signal_dir == "long" and d in ("bear", "strong_bear"):
            return False
    else:
        if signal_dir == "short" and d == "strong_bull":
            return False
        if signal_dir == "long" and d == "strong_bear":
            return False
    return True


# ── Comprehensive market state ─────────────────────────────────────────────────

def classify_market_full(
    df: pd.DataFrame,
    today: date,
    vix: float,
    vix3m: Optional[float] = None,
    vvix:  Optional[float] = None,
    today_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Full market state dictionary used by the adaptive engine.

    Keys (original):
      atr, atr_5, atr_20, vix, vix_regime, vol_regime, ema_trend,
      vwap_ok, orb_ok, ib_ok, fvg_ok

    Keys (new — institutional upgrades):
      overnight    : dict — overnight range type (expansion/rotation/neutral)
      vix_term     : dict — VIX term structure (contango/backwardation)
      vvix_regime  : dict — vol-of-vol gate
      open_type    : dict — open drive/auction/reversal classification
      expiry       : dict — 0DTE gamma expiry context
    """
    atr5  = get_daily_atr(df, today, lookback=5)
    atr20 = get_daily_atr(df, today, lookback=20)
    atr   = max(atr5, atr20)

    vix_regime  = classify_regime(vix)
    vol_regime  = get_volatility_regime(df, today)
    ema_trend   = get_ema_trend(df, today)

    vwap_ok = (
        vol_regime in ("normal", "compressed", "elevated")
        and vix < 25
    )

    # ── New institutional context ──────────────────────────────────────────────
    overnight   = get_overnight_range_type(df, today, atr)

    # VIX3M and VVIX: try to load if not supplied
    _vix3m = vix3m
    _vvix  = vvix
    if _vix3m is None:
        _vix3m = _get_cached_extended("^VIX3M", "_vix3m_cache", today)
    if _vvix is None:
        _vvix = _get_cached_extended("^VVIX", "_vvix_cache", today)

    vix_term    = get_vix_term_structure(vix, _vix3m or 0.0)
    vvix_regime = get_vvix_regime(_vvix or 0.0)

    # Open type needs today's bars (available intraday, not at backtest day-start)
    if today_df is not None and len(today_df) >= 3:
        open_type = classify_open_type(today_df, atr)
    else:
        open_type = {"open_type": "unknown", "initial_dir": "neutral",
                     "drive_strength": 0.0, "day_type_hint": "mixed"}

    expiry = get_expiry_context(today)

    return {
        "atr":        atr,
        "atr_5":      atr5,
        "atr_20":     atr20,
        "vix":        vix,
        "vix_regime": vix_regime,
        "vol_regime": vol_regime,
        "ema_trend":  ema_trend,
        "vwap_ok":    vwap_ok,
        "orb_ok":     True,
        "ib_ok":      True,
        "fvg_ok":     True,
        # New
        "overnight":   overnight,
        "vix_term":    vix_term,
        "vvix_regime": vvix_regime,
        "open_type":   open_type,
        "expiry":      expiry,
    }


# ── Overnight range → day type ────────────────────────────────────────────────

def get_overnight_range_type(df: pd.DataFrame, today: date, atr: float) -> dict:
    """
    Classify today's overnight range vs. ATR.
    Overnight window: 6 PM ET prior day → 9:30 AM ET today.

    Returns:
      overnight_range   : float — pts from overnight low to overnight high
      overnight_pct_atr : float — overnight_range / atr
      day_type_bias     : "expansion" | "rotation" | "neutral"
      breakout_favored  : bool  — tight overnight → ORB/IB/Gap favored
      meanrev_favored   : bool  — wide overnight → VWAP/FVG favored
    """
    est_idx = df.index.tz_convert(EST)
    df2 = df.copy()
    df2["_date"] = est_idx.date
    df2["_hour"] = est_idx.hour
    df2["_min"]  = est_idx.minute

    prior_day = today - timedelta(days=1)
    # extend lookback to find last trading day
    for lag in range(5):
        check = today - timedelta(days=lag + 1)
        if any(df2["_date"] == check):
            prior_day = check
            break

    overnight_mask = (
        ((df2["_date"] == prior_day) & (df2["_hour"] >= 18)) |
        ((df2["_date"] == today) & (
            (df2["_hour"] < 9) | ((df2["_hour"] == 9) & (df2["_min"] < 30))
        ))
    )
    ov_bars = df[overnight_mask]

    default = {
        "overnight_range": 0.0, "overnight_pct_atr": 0.5,
        "day_type_bias": "neutral",
        "breakout_favored": False, "meanrev_favored": False,
    }

    if ov_bars.empty or atr <= 0:
        return default

    ov_range = float(ov_bars["High"].max() - ov_bars["Low"].min())
    pct_atr  = ov_range / atr

    if pct_atr < 0.25:
        bias = "expansion"      # coiled → breakout day expected
    elif pct_atr > 0.60:
        bias = "rotation"       # wide overnight → mean-rev expected
    else:
        bias = "neutral"

    return {
        "overnight_range":   ov_range,
        "overnight_pct_atr": pct_atr,
        "day_type_bias":     bias,
        "breakout_favored":  bias == "expansion",
        "meanrev_favored":   bias == "rotation",
    }


# ── VIX term structure ────────────────────────────────────────────────────────

_vix3m_cache: Optional[dict] = None
_vvix_cache:  Optional[dict] = None


def _load_vix_extended(ticker: str, period: str = "90d") -> dict[date, float]:
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        result: dict[date, float] = {}
        for ts, row in hist.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        return result
    except Exception:
        return {}


def _get_cached_extended(ticker: str, cache_attr: str, d: date) -> Optional[float]:
    import sys
    module = sys.modules[__name__]
    cache = getattr(module, cache_attr, None)
    if cache is None:
        loaded = _load_vix_extended(ticker)
        setattr(module, cache_attr, loaded)
        cache = loaded
    if not cache:
        return None
    if d in cache:
        return cache[d]
    for lag in range(1, 6):
        key = d - timedelta(days=lag)
        if key in cache:
            return cache[key]
    return None


def get_vix_term_structure(vix_spot: float, vix3m: float) -> dict:
    """
    Compare spot VIX to 3-month VIX.

    Returns:
      ratio       : float
      structure   : "deep_contango" | "contango" | "flat" | "backwardation" | "deep_backwardation"
      mean_rev_ok : bool  — False in backwardation (mean-rev dangerous)
      size_mult   : float — 1.0 / 0.75 / 0.5 / 0.0 (skip)
    """
    if vix3m is None or vix3m <= 0:
        return {"ratio": 1.0, "structure": "contango", "mean_rev_ok": True, "size_mult": 1.0}

    ratio = vix_spot / vix3m

    if ratio < 0.85:
        return {"ratio": ratio, "structure": "deep_contango",        "mean_rev_ok": True,  "size_mult": 1.0}
    elif ratio < 1.0:
        return {"ratio": ratio, "structure": "contango",             "mean_rev_ok": True,  "size_mult": 1.0}
    elif ratio < 1.08:
        return {"ratio": ratio, "structure": "flat",                 "mean_rev_ok": True,  "size_mult": 0.75}
    elif ratio < 1.15:
        return {"ratio": ratio, "structure": "backwardation",        "mean_rev_ok": False, "size_mult": 0.5}
    else:
        return {"ratio": ratio, "structure": "deep_backwardation",   "mean_rev_ok": False, "size_mult": 0.0}


def get_vvix_regime(vvix: float) -> dict:
    """
    VVIX = vol of VIX = vol-of-vol.

    Returns:
      level    : "low" | "normal" | "elevated" | "extreme"
      skip_day : bool  — True if VVIX > 130
      size_mult: float
    """
    if vvix is None or vvix <= 0:
        return {"level": "normal", "skip_day": False, "size_mult": 1.0}
    if vvix > 130:
        return {"level": "extreme",  "skip_day": True,  "size_mult": 0.0}
    elif vvix > 110:
        return {"level": "elevated", "skip_day": False, "size_mult": 0.5}
    elif vvix > 90:
        return {"level": "normal",   "skip_day": False, "size_mult": 0.75}
    return {"level": "low",          "skip_day": False, "size_mult": 1.0}


# ── Open type classification ──────────────────────────────────────────────────

def classify_open_type(today_df: pd.DataFrame, atr: float, lookback_bars: int = 3) -> dict:
    """
    Classify opening type from first 3 bars after 9:30 AM (CME auction market theory).

    Open Drive (OD)         : straight directional move, no pullback → trend day
    Open Test Drive (OTD)   : tests one direction, then drives opposite → trend day
    Open Rejection Reverse  : extends one way, strong rejection back → reversal day
    Open Auction (OA)       : oscillates near open price → range day
    Open Auction Drive (OAD): auctions then breaks late → mixed/IB day

    Returns:
      open_type      : str
      initial_dir    : "long" | "short" | "neutral"
      drive_strength : float — magnitude as % of ATR
      day_type_hint  : "trend" | "range" | "reversal" | "mixed"
    """
    default = {"open_type": "unknown", "initial_dir": "neutral",
               "drive_strength": 0.0, "day_type_hint": "mixed"}

    est_idx = today_df.index.tz_convert(EST)
    rth = today_df[(est_idx.hour == 9) & (est_idx.minute >= 30)]
    if len(rth) < lookback_bars:
        return default

    first_bars  = rth.iloc[:lookback_bars]
    bar0_open   = float(first_bars.iloc[0]["Open"])
    bar0_high   = float(first_bars.iloc[0]["High"])
    bar0_low    = float(first_bars.iloc[0]["Low"])
    last_close  = float(first_bars.iloc[-1]["Close"])

    all_high = float(first_bars["High"].max())
    all_low  = float(first_bars["Low"].min())
    range_15m = all_high - all_low

    if atr <= 0:
        return default

    drive_pct = range_15m / atr
    initial_dir = "long" if last_close > bar0_open else ("short" if last_close < bar0_open else "neutral")
    net_move = last_close - bar0_open

    # Open Drive: price moves strongly in one direction (>15% ATR) without reversing
    upper_probe = all_high - bar0_open
    lower_probe = bar0_open - all_low
    dominant_side = max(upper_probe, lower_probe)
    opposing_side = min(upper_probe, lower_probe)

    if dominant_side > atr * 0.12 and opposing_side < atr * 0.04:
        open_type    = "open_drive"
        day_type     = "trend"

    # Open Rejection Reverse: price extends one way then slams back through open
    elif (upper_probe > atr * 0.08 and last_close < bar0_open - atr * 0.04) or \
         (lower_probe > atr * 0.08 and last_close > bar0_open + atr * 0.04):
        open_type    = "open_rejection"
        day_type     = "reversal"

    # Open Test Drive: first bar pokes one way, then resolves the other direction
    elif abs(net_move) > atr * 0.06 and opposing_side > atr * 0.03:
        open_type    = "open_test_drive"
        day_type     = "trend"
        initial_dir  = "long" if net_move > 0 else "short"

    # Open Auction: price oscillates close to open, no clear direction
    elif range_15m < atr * 0.10 and abs(net_move) < atr * 0.03:
        open_type    = "open_auction"
        day_type     = "range"

    # Open Auction Drive: initial balance then breaks (IB-type)
    else:
        open_type    = "open_auction_drive"
        day_type     = "mixed"

    return {
        "open_type":      open_type,
        "initial_dir":    initial_dir,
        "drive_strength": drive_pct,
        "day_type_hint":  day_type,
    }


# ── 0DTE expiry day context ───────────────────────────────────────────────────

EXPIRY_DAYS = {
    0: ["QQQ_w"],
    1: ["QQQ"],
    2: ["SPX", "NDX"],
    3: ["QQQ_w"],
    4: ["SPX", "NDX", "QQQ"],
}


def get_expiry_context(today: date) -> dict:
    """
    Returns gamma expiry context for today.

    Returns:
      is_expiry_day    : bool
      expiry_products  : list[str]
      gamma_pin_risk   : "high" | "medium" | "low"
      recommended_bias : "mean_rev" | "breakout" | "neutral"
    """
    dow      = today.weekday()
    products = EXPIRY_DAYS.get(dow, [])
    is_exp   = bool(products)

    if any(p in products for p in ["NDX", "SPX"]):
        pin_risk = "high"
        bias     = "mean_rev"
    elif products:
        pin_risk = "medium"
        bias     = "neutral"
    else:
        pin_risk = "low"
        bias     = "neutral"

    return {
        "is_expiry_day":   is_exp,
        "expiry_products": products,
        "gamma_pin_risk":  pin_risk,
        "recommended_bias": bias,
    }


# ── Legacy strategy gates (kept for compatibility) ────────────────────────────

def orb_ok(vix: float) -> bool:
    return True  # ATR filter in quant_orb.py handles quality now

def ib_ok(vix: float) -> bool:
    return True  # ATR filter in quant_ib.py handles quality now

def vwap_reversion_ok(vix: float) -> bool:
    return vix < 25

def gap_fill_ok(vix: float) -> bool:
    return True
