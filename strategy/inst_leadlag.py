"""
ES/NQ Lead-Lag Confirmation.

ES (S&P 500 futures) leads NQ by 1-3 bars on macro-driven moves.
NQ leads ES on tech-sector-specific moves.

For NQ signals in neutral/macro-driven environments:
  If ES is moving in the SAME direction over the last 1-3 bars → CONFIRM
  If ES is moving in the OPPOSITE direction → SKIP (divergence = risk)
  If ES is flat → neutral (don't block)

Implementation:
  MES=F data aligned by timestamp with MNQ=F.
  Use 3-bar window ending at signal bar.
  Threshold: ±2bps to filter noise.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

DIRECTION_THRESHOLD = 0.0002   # 2bps to confirm a move


def _es_recent_direction(es_df: pd.DataFrame, es_pos: int, lookback_bars: int = 3) -> str:
    """Net direction of ES over `lookback_bars` bars ending at es_pos."""
    start = max(0, es_pos - lookback_bars + 1)
    end   = min(es_pos + 1, len(es_df))
    if start >= end:
        return "neutral"

    window    = es_df.iloc[start:end]
    open_p    = float(window.iloc[0]["Open"])
    close_p   = float(window.iloc[-1]["Close"])

    if open_p < 1.0:
        return "neutral"

    pct = (close_p - open_p) / open_p

    if pct > DIRECTION_THRESHOLD:
        return "long"
    if pct < -DIRECTION_THRESHOLD:
        return "short"
    return "neutral"


def check_es_confirmation(
    es_df: pd.DataFrame,
    mnq_df: pd.DataFrame,
    mnq_bar_idx: int,
    signal_direction: str,
    lookback_bars: int = 3,
) -> bool:
    """
    Returns True if ES confirms the NQ signal (or if ES data is unavailable).

    es_df:            5-min MES=F bars (UTC index), or empty DataFrame
    mnq_df:           5-min MNQ=F bars used in backtest
    mnq_bar_idx:      global bar index of the signal in mnq_df
    signal_direction: "long" or "short"
    lookback_bars:    how many ES bars to look back
    """
    if es_df is None or es_df.empty:
        return True    # can't penalize when data absent

    try:
        signal_ts = mnq_df.index[mnq_bar_idx]
    except IndexError:
        return True

    # Find nearest ES bar to the signal timestamp
    try:
        diffs  = (es_df.index - signal_ts).abs()
        es_pos = int(diffs.argmin())
    except Exception:
        return True

    # If the nearest ES bar is more than 2 bars away, alignment is unreliable
    nearest_ts = es_df.index[es_pos]
    delta_secs = abs((nearest_ts - signal_ts).total_seconds())
    if delta_secs > 600:    # 10 minutes = 2 bars at 5m
        return True

    es_dir = _es_recent_direction(es_df, es_pos, lookback_bars)

    if es_dir == "neutral":
        return True     # ES flat → don't block

    return es_dir == signal_direction
