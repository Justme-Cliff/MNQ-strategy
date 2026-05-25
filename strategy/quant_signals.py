"""
Quantitative signal helpers — additional confluence points and flexible RR computation.

Three quant scoring points (on top of the 12-point ICT score):
  +1  RSI divergence at the sweep bar (momentum confirms reversal)
  +1  High relative volume at sweep (>1.5x 20-bar avg → institutional participation)
  +1  VWAP extended position (price beyond 1σ band in signal direction)

Flexible RR ladder (compute_trade_rr):
  Base 3:1, upgraded by score, signal type, day-of-week, and quant bonus.
  Maximum 5:1. Snapped to nearest 0.5 increment.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


# ── RSI ───────────────────────────────────────────────────────────────────────

def _compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder RSI from a close price array."""
    delta = np.diff(closes.astype(float), prepend=np.nan)
    gain  = np.where(delta > 0,  delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_g = np.full_like(closes, np.nan, dtype=float)
    avg_l = np.full_like(closes, np.nan, dtype=float)
    if len(closes) <= period:
        return avg_g  # not enough data
    avg_g[period] = np.mean(gain[1:period + 1])
    avg_l[period] = np.mean(loss[1:period + 1])
    for j in range(period + 1, len(closes)):
        avg_g[j] = (avg_g[j - 1] * (period - 1) + gain[j]) / period
        avg_l[j] = (avg_l[j - 1] * (period - 1) + loss[j]) / period
    rs  = np.where(avg_l == 0, 100.0, avg_g / avg_l)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi[:period] = np.nan
    return rsi


def rsi_divergence(
    df: pd.DataFrame,
    sweep_bar: int,
    direction: str,
    period: int = 14,
    lookback: int = 25,
) -> bool:
    """
    True when RSI shows classic divergence at the sweep bar.

    Bullish divergence (long setup): price makes a lower low vs a prior low in
    the lookback window, but RSI is higher → momentum not confirming the new low.

    Bearish divergence (short setup): price makes a higher high vs a prior high,
    but RSI is lower → momentum fading at the new high.
    """
    start = max(0, sweep_bar - lookback)
    closes = df["Close"].iloc[start:sweep_bar + 1].values
    lows   = df["Low"].iloc[start:sweep_bar + 1].values
    highs  = df["High"].iloc[start:sweep_bar + 1].values

    if len(closes) < period + 4:
        return False

    rsi = _compute_rsi(closes, period)
    sweep_rsi = rsi[-1]
    if np.isnan(sweep_rsi):
        return False

    if direction == "long":
        sweep_low = lows[-1]
        # Find prior local low in the lookback (excluding last few bars)
        window_lows = lows[:-3]
        window_rsi  = rsi[:-3]
        valid = ~np.isnan(window_rsi)
        if not np.any(valid):
            return False
        prior_idx = np.nanargmin(np.where(valid, window_lows, np.inf))
        prior_low = window_lows[prior_idx]
        prior_rsi = window_rsi[prior_idx]
        # Bullish divergence: price lower low BUT RSI higher
        return sweep_low < prior_low and sweep_rsi > prior_rsi

    else:  # short
        sweep_high = highs[-1]
        window_highs = highs[:-3]
        window_rsi   = rsi[:-3]
        valid = ~np.isnan(window_rsi)
        if not np.any(valid):
            return False
        prior_idx  = np.nanargmax(np.where(valid, window_highs, -np.inf))
        prior_high = window_highs[prior_idx]
        prior_rsi  = window_rsi[prior_idx]
        # Bearish divergence: price higher high BUT RSI lower
        return sweep_high > prior_high and sweep_rsi < prior_rsi


# ── Relative Volume ───────────────────────────────────────────────────────────

def high_relative_volume(
    df: pd.DataFrame,
    bar_idx: int,
    lookback: int = 20,
    threshold: float = 1.5,
) -> bool:
    """
    True when the sweep bar's volume is at least `threshold` × the 20-bar average.
    Confirms institutional participation at the sweep point.
    Returns False gracefully when Volume column is absent or all zeros.
    """
    if "Volume" not in df.columns:
        return False
    start = max(0, bar_idx - lookback)
    avg_vol = df["Volume"].iloc[start:bar_idx].mean()
    if avg_vol <= 0 or np.isnan(avg_vol):
        return False
    sweep_vol = float(df["Volume"].iloc[bar_idx])
    return sweep_vol >= avg_vol * threshold


# ── VWAP position ─────────────────────────────────────────────────────────────

def vwap_extended(
    price: float,
    vwap_upper1: float | None,
    vwap_lower1: float | None,
    direction: str,
) -> bool:
    """
    True when price is beyond the ±1σ VWAP band in the signal direction.
    Long: price < VWAP−1σ → deep value zone, mean-reversion edge stacks.
    Short: price > VWAP+1σ → extended zone, reversion to VWAP supports the short.
    """
    if vwap_upper1 is None or vwap_lower1 is None:
        return False
    if direction == "long":
        return price < vwap_lower1
    return price > vwap_upper1


# ── Composite quant bonus ─────────────────────────────────────────────────────

def quant_bonus_score(
    df: pd.DataFrame,
    sweep_bar: int,
    signal_dir: str,
    price: float,
    vwap_upper1: float | None = None,
    vwap_lower1: float | None = None,
) -> int:
    """
    Returns 0–3 bonus points from quantitative filters.
    Used to upgrade the RR target — does NOT affect the ICT minimum score threshold.

    +1  RSI divergence confirms momentum reversal at sweep
    +1  High relative volume (>1.5× avg) confirms institutional sweep
    +1  Price in extended VWAP zone (beyond ±1σ) adds mean-reversion edge
    """
    bonus = 0
    if rsi_divergence(df, sweep_bar, signal_dir):
        bonus += 1
    if high_relative_volume(df, sweep_bar):
        bonus += 1
    if vwap_extended(price, vwap_upper1, vwap_lower1, signal_dir):
        bonus += 1
    return bonus


# ── Flexible RR ───────────────────────────────────────────────────────────────

def compute_trade_rr(
    score: int,
    signal_type: str,
    day_of_week: int,
    quant_bonus: int = 0,
) -> float:
    """
    Compute the reward-to-risk target for a setup.

    Base: 3.0 (minimum — every trade targets at least 3:1)

    Score upgrades (ICT 12-point score):
      score ≥ 11  → +1.0  (near-perfect confluence)
      score ≥  8  → +0.5  (strong confluence)

    Signal-type adjustment:
      weekly sweep        → +1.0  (large structural move, plenty of room)
      midnight / pdh_pdl  → +0.5  (significant structural level)
      premarket           → cap 3.5 (pre-market range is tight; TP2 capped)
      silver_bullet       → cap 4.0 (time-window signal, sustained but bounded)

    Day-of-week (ICT Power of Three):
      Monday (Accumulation) or Wednesday (Distribution) → +0.5
      (institutional moves on these days are the most sustained)

    Quant bonus:
      +0.25 per quant point, max 3 points used  (max +0.75)

    Global cap: 5.0
    Output snapped to nearest 0.5 increment for clean TP levels.
    """
    rr = 3.0

    # Score upgrade
    if score >= 11:
        rr += 1.0
    elif score >= 8:
        rr += 0.5

    # Signal type upgrade
    _signal_upgrades = {"weekly": 1.0, "midnight": 0.5, "pdh_pdl": 0.5}
    _signal_caps     = {"premarket": 3.5, "silver_bullet": 4.0}
    rr += _signal_upgrades.get(signal_type, 0.0)

    # Day of week upgrade
    if day_of_week in (0, 2):   # Monday=0, Wednesday=2
        rr += 0.5

    # Quant bonus
    rr += min(quant_bonus, 3) * 0.25

    # Apply per-signal caps
    if signal_type in _signal_caps:
        rr = min(rr, _signal_caps[signal_type])

    # Global cap + snap to 0.5
    rr = min(rr, 5.0)
    return round(rr * 2) / 2
