"""
Hidden Markov Model regime gate.

5-state GaussianHMM on daily [log_return, range_ratio, realized_vol] features.
Ang & Bekaert (2002, RFS): multivariate HMM outperforms univariate on equity indices.

States (sorted by mean log_return):
  0: bear       — negative returns, wide ranges, high vol
  1: stress     — flat/negative, elevated vol, large swings
  2: neutral    — mean-reverting, normal ranges
  3: bull       — positive returns, normal vol
  4: strong_bull — strong positive returns, compressed vol

Gate: skip_day = True if bear OR stress probability > threshold.
Scoring: strong_bull gives full confirmation; neutral/stress gives partial.
Requires: pip install hmmlearn
"""
from __future__ import annotations
import io
import sys
import json
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

EST = ZoneInfo("America/New_York")

# Disk cache so 10-year backtests don't re-train HMM every run
_HMM_CACHE_FILE = Path(__file__).parent.parent / ".cache" / "hmm_states.json"
_hmm_disk_cache: dict[str, dict] = {}

def _load_hmm_cache():
    global _hmm_disk_cache
    if _HMM_CACHE_FILE.exists() and not _hmm_disk_cache:
        try:
            _hmm_disk_cache = json.loads(_HMM_CACHE_FILE.read_text())
        except Exception:
            _hmm_disk_cache = {}

def _save_hmm_cache():
    try:
        _HMM_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HMM_CACHE_FILE.write_text(json.dumps(_hmm_disk_cache))
    except Exception:
        pass

try:
    from hmmlearn.hmm import GaussianHMM
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False

BEAR_THRESHOLD   = 0.55   # skip if bear prob > this
STRESS_THRESHOLD = 0.60   # skip if stress prob > this (both bear+stress)
N_STATES         = 5      # strong_bull, bull, neutral, stress, bear


def _build_features(df: pd.DataFrame, today: date, lookback_days: int = 60) -> Optional[np.ndarray]:
    """Build [log_return, range_ratio, realized_vol] feature matrix from 5m bars."""
    est_idx = df.index.tz_convert(EST)
    df2 = df.copy()
    df2["_date"] = est_idx.date

    past = df2[df2["_date"] < today]
    if past.empty:
        return None

    daily_close = past.groupby("_date")["Close"].last().sort_index()
    daily_high  = past.groupby("_date")["High"].max().sort_index()
    daily_low   = past.groupby("_date")["Low"].min().sort_index()

    past = past.copy()
    past["_log_ret"] = np.log(past["Close"] / past["Close"].shift(1).clip(lower=1e-8))
    daily_rv = past.groupby("_date")["_log_ret"].std().sort_index()

    idx = daily_close.index.intersection(daily_rv.index)
    if len(idx) < 20:
        return None

    closes = daily_close.loc[idx].tail(lookback_days)
    highs  = daily_high.loc[idx].tail(lookback_days)
    lows   = daily_low.loc[idx].tail(lookback_days)
    rvs    = daily_rv.loc[idx].tail(lookback_days)

    log_ret = np.log(closes / closes.shift(1)).dropna()
    common_idx = log_ret.index

    rv_aligned   = rvs.loc[common_idx].fillna(0)
    high_aligned = highs.loc[common_idx]
    low_aligned  = lows.loc[common_idx]

    # Range ratio: daily range / 20-session rolling avg range
    # Use pandas rolling mean (safe for any length — avoids np.convolve boundary issues)
    import pandas as _pd
    ranges_series = _pd.Series((high_aligned - low_aligned).values)
    avg_range = ranges_series.rolling(20, min_periods=5).mean().bfill().fillna(1.0).values
    avg_range = np.where(avg_range < 1e-8, 1e-8, avg_range)
    range_ratio = ranges_series.values / avg_range

    if len(log_ret) < 15:
        return None

    X = np.column_stack([
        log_ret.values,
        range_ratio[-len(log_ret):],
        rv_aligned.values,
    ])
    return X


def _train(df: pd.DataFrame, today: date, lookback_days: int = 60):
    """Train 5-state GaussianHMM. Returns (model, order) or (None, None)."""
    if not HMM_AVAILABLE:
        return None, None

    X = _build_features(df, today, lookback_days)
    if X is None or len(X) < 20:
        return None, None

    try:
        X_std = X.std(axis=0)
        X_std[X_std == 0] = 1.0
        X_scaled = X / X_std

        _old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            model = GaussianHMM(n_components=N_STATES, covariance_type="diag",
                                n_iter=100, random_state=42, tol=1e-3)
            model.fit(X_scaled)
        finally:
            sys.stdout = _old_stdout

        model._x_std = X_std
        # Sort by mean log_return ascending: 0=bear...4=strong_bull
        order = np.argsort(model.means_[:, 0])
        return model, order
    except Exception:
        return None, None


def get_hmm_gate(df: pd.DataFrame, today: date, bear_threshold: float = BEAR_THRESHOLD) -> dict:
    """
    Compute 5-state HMM regime probabilities for today.

    Returns:
      skip_day     : bool  — True if in bear or stress state
      bear_prob    : float
      stress_prob  : float
      neutral_prob : float
      bull_prob    : float
      strong_prob  : float
      state        : str   — "strong_bull"|"bull"|"neutral"|"stress"|"bear"|"unavailable"
    """
    STATE_NAMES = ["bear", "stress", "neutral", "bull", "strong_bull"]
    default = {
        "skip_day": False,
        "bear_prob": 0.0, "stress_prob": 0.0, "neutral_prob": 0.0,
        "bull_prob": 1.0, "strong_prob": 0.0,
        # Keep backward-compat fields
        "vol_prob": 0.0,
        "state": "unavailable",
    }

    if not HMM_AVAILABLE:
        return default

    # Check disk cache first — avoids re-training on repeated 10-year runs
    _load_hmm_cache()
    _cache_key = str(today)
    if _cache_key in _hmm_disk_cache:
        return _hmm_disk_cache[_cache_key]

    model, order = _train(df, today, lookback_days=60)
    if model is None:
        return default

    X = _build_features(df, today, lookback_days=61)
    if X is None or len(X) < 5:
        return default

    try:
        x_std = getattr(model, "_x_std", np.ones(X.shape[1]))
        X_scaled = X / x_std

        posteriors = model.predict_proba(X_scaled)
        last_probs = posteriors[-1]

        # Remap raw probs to sorted order
        remapped = np.zeros(N_STATES)
        for sorted_rank, raw_idx in enumerate(order):
            remapped[sorted_rank] = float(last_probs[raw_idx])

        state_rank = int(np.argmax(remapped))
        state      = STATE_NAMES[state_rank]

        bear_p   = remapped[0]
        stress_p = remapped[1]
        neut_p   = remapped[2]
        bull_p   = remapped[3]
        sbull_p  = remapped[4]

        # Skip day if in bear OR strong stress regime
        skip = (bear_p > bear_threshold) or (stress_p > STRESS_THRESHOLD)

        result = {
            "skip_day":    skip,
            "bear_prob":   float(bear_p),
            "stress_prob": float(stress_p),
            "neutral_prob": float(neut_p),
            "bull_prob":   float(bull_p),
            "strong_prob": float(sbull_p),
            "vol_prob":    float(stress_p),   # backward compat alias
            "state":       state,
        }
        # Save to disk cache
        _hmm_disk_cache[_cache_key] = result
        _save_hmm_cache()
        return result
    except Exception:
        return default
