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
from datetime import date
from zoneinfo import ZoneInfo

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

def classify_market_full(df: pd.DataFrame, today: date, vix: float) -> dict:
    """
    Full market state dictionary used by the adaptive engine.

    Keys:
      atr          : float — adaptive ATR (max of 5d and 20d)
      atr_5        : float
      atr_20       : float
      vix_regime   : "low" | "normal" | "elevated" | "high"
      vol_regime   : "compressed" | "normal" | "elevated" | "crisis"
      ema_trend    : dict from get_ema_trend()
      vwap_ok      : bool — VWAP reversion allowed?
      orb_ok       : bool — ORB allowed? (any regime now — ATR filter handles quality)
      ib_ok        : bool — IB allowed?
      fvg_ok       : bool — FVG allowed? (always True — works in all regimes)
    """
    atr5  = get_daily_atr(df, today, lookback=5)
    atr20 = get_daily_atr(df, today, lookback=20)
    atr   = max(atr5, atr20)

    vix_regime  = classify_regime(vix)
    vol_regime  = get_volatility_regime(df, today)
    ema_trend   = get_ema_trend(df, today)
    trend_dir   = ema_trend["direction"]

    # VWAP reversion: any trend direction (direction_allowed handles alignment),
    # VIX < 25 and not in crisis volatility regime
    vwap_ok = (
        vol_regime in ("normal", "compressed", "elevated")
        and vix < 25
    )

    # ORB: valid in all regimes — ATR-normalized range is the quality gate
    orb_ok = True

    # IB: valid in all regimes
    ib_ok = True

    return {
        "atr":        atr,
        "atr_5":      atr5,
        "atr_20":     atr20,
        "vix":        vix,
        "vix_regime": vix_regime,
        "vol_regime": vol_regime,
        "ema_trend":  ema_trend,
        "vwap_ok":    vwap_ok,
        "orb_ok":     orb_ok,
        "ib_ok":      ib_ok,
        "fvg_ok":     True,
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
