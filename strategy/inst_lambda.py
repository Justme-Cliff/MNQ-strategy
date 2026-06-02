"""
Kyle's Lambda Proxy — Informed Flow Intensity.

Albert Kyle (1985): price impact per unit volume (lambda) is proportional to
the fraction of informed trading in the market.

  lambda_bar = (close - open) / volume   (signed per-bar proxy)

High rolling z-score of |lambda| = institutional urgency, price discovery.
Low lambda = noise trading or absorption.

Complements OFI (volume-weighted close position) by measuring price EFFICIENCY
per unit volume — a distinct signal from raw volume direction.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def compute_lambda_series(today_df: pd.DataFrame) -> pd.Series:
    """Per-bar Kyle's lambda proxy: (close - open) / volume."""
    closes = today_df["Close"].values.astype(float)
    opens  = today_df["Open"].values.astype(float)
    vols   = today_df["Volume"].values.astype(float)
    vols_safe = np.where(vols == 0, 1.0, vols)
    return pd.Series((closes - opens) / vols_safe, index=today_df.index)


def get_lambda_signal(
    today_df: pd.DataFrame,
    bar_pos: int,
    signal_direction: str,
    window: int = 20,
) -> dict:
    """
    Rolling z-score of Kyle's lambda.

    Returns:
      lambda_val : float — current bar lambda
      z_score    : float — z vs rolling window history
      regime     : "informed" | "neutral" | "noise"
      aligned    : bool  — True if lambda direction matches signal direction
    """
    _default = {"lambda_val": 0.0, "z_score": 0.0, "regime": "neutral", "aligned": True}

    try:
        if bar_pos < 4:
            return _default

        lam = compute_lambda_series(today_df)
        w   = lam.iloc[max(0, bar_pos - window): bar_pos + 1]

        if len(w) < 4:
            return _default

        std = float(w.std())
        if std < 1e-12:
            return _default

        cur_lam = float(lam.iloc[bar_pos])
        z = (cur_lam - float(w.mean())) / std

        if abs(z) > 2.0:
            regime = "informed"
        elif abs(z) > 1.0:
            regime = "neutral"
        else:
            regime = "noise"

        aligned = (
            (z > 0.5 and signal_direction == "long") or
            (z < -0.5 and signal_direction == "short") or
            abs(z) < 0.5
        )

        return {
            "lambda_val": cur_lam,
            "z_score":    z,
            "regime":     regime,
            "aligned":    aligned,
        }

    except Exception:
        return _default
