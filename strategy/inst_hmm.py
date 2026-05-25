"""
Hidden Markov Model regime gate.

3-state GaussianHMM on daily [log_return, realized_vol] features.
States sorted by mean log_return → labeled "bear" / "volatile" / "bull".

Gate: skip_day = True if bear_state_prob > 0.55.
Research: Sharpe improves 1.16 → 1.76 with HMM gating on NQ/ES futures.
Requires: pip install hmmlearn
"""
from __future__ import annotations
import io
import sys
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from datetime import date
from zoneinfo import ZoneInfo
from typing import Optional

EST = ZoneInfo("America/New_York")

try:
    from hmmlearn.hmm import GaussianHMM
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False

BEAR_THRESHOLD = 0.55   # skip day if bear probability exceeds this


def _build_features(df: pd.DataFrame, today: date, lookback_days: int = 60) -> Optional[np.ndarray]:
    """Build [log_return, realized_vol] feature matrix from 5m bars."""
    est_idx = df.index.tz_convert(EST)
    df2 = df.copy()
    df2["_date"] = est_idx.date

    past = df2[df2["_date"] < today]
    if past.empty:
        return None

    daily_close = past.groupby("_date")["Close"].last().sort_index()

    past = past.copy()
    past["_log_ret"] = np.log(past["Close"] / past["Close"].shift(1).clip(lower=1e-8))
    daily_rv = past.groupby("_date")["_log_ret"].std().sort_index()

    idx = daily_close.index.intersection(daily_rv.index)
    if len(idx) < 20:
        return None

    closes = daily_close.loc[idx].tail(lookback_days)
    rvs    = daily_rv.loc[idx].tail(lookback_days)

    log_ret = np.log(closes / closes.shift(1)).dropna()
    rv_aligned = rvs.loc[log_ret.index]

    if len(log_ret) < 15:
        return None

    X = np.column_stack([log_ret.values, rv_aligned.fillna(0).values])
    return X


def _train(df: pd.DataFrame, today: date, lookback_days: int = 60):
    """Train 3-state GaussianHMM. Returns (model, order) or (None, None)."""
    if not HMM_AVAILABLE:
        return None, None

    X = _build_features(df, today, lookback_days)
    if X is None or len(X) < 15:
        return None, None

    try:
        # Scale features to unit variance for better convergence
        X_std = X.std(axis=0)
        X_std[X_std == 0] = 1.0
        X_scaled = X / X_std

        # Redirect stdout to suppress hmmlearn's print-based convergence messages
        _old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            model = GaussianHMM(n_components=3, covariance_type="diag",
                                n_iter=500, random_state=42, tol=1e-5)
            model.fit(X_scaled)
        finally:
            sys.stdout = _old_stdout

        # Store scale so we can transform test data
        model._x_std = X_std
        # Sort states by mean log_return ascending: 0=bear, 1=volatile, 2=bull
        order = np.argsort(model.means_[:, 0])
        return model, order
    except Exception:
        return None, None


def get_hmm_gate(df: pd.DataFrame, today: date, bear_threshold: float = BEAR_THRESHOLD) -> dict:
    """
    Compute HMM regime probabilities for today.

    Returns:
      skip_day  : bool  — True if HMM says we are in bear state
      bear_prob : float — probability of bear state
      bull_prob : float
      vol_prob  : float
      state     : str   — "bull" | "volatile" | "bear" | "unavailable"
    """
    default = {"skip_day": False, "bear_prob": 0.0, "bull_prob": 1.0, "vol_prob": 0.0, "state": "unavailable"}

    if not HMM_AVAILABLE:
        return default

    model, order = _train(df, today, lookback_days=60)
    if model is None:
        return default

    # Use lookback + 1 to include the last point (represents "today" regime)
    X = _build_features(df, today, lookback_days=61)
    if X is None or len(X) < 5:
        return default

    try:
        # Apply the same scaling used during training
        x_std = getattr(model, "_x_std", np.ones(X.shape[1]))
        X_scaled = X / x_std

        posteriors = model.predict_proba(X_scaled)
        last_probs = posteriors[-1]    # raw state probabilities for last day

        # Remap to sorted order: order[0]=bear state index, order[2]=bull state index
        bear_prob = float(last_probs[order[0]])
        vol_prob  = float(last_probs[order[1]])
        bull_prob = float(last_probs[order[2]])

        state_idx = int(np.argmax(last_probs))
        rank = int(np.where(order == state_idx)[0][0])
        state = ["bear", "volatile", "bull"][rank]

        return {
            "skip_day":  bear_prob > bear_threshold,
            "bear_prob": bear_prob,
            "bull_prob": bull_prob,
            "vol_prob":  vol_prob,
            "state":     state,
        }
    except Exception:
        return default
