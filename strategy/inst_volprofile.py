"""
Volume Profile — Session POC, VAH, VAL, Naked VPOC.

Volume Profile is not a technical indicator — it's a record of where actual
contracts traded. Banks and prop desks use these levels as mechanical references:
  POC (Point of Control) — price with highest volume = fair value
  VAH/VAL (Value Area)   — top/bottom of 70% volume range = institutional support/resistance
  Naked VPOC             — prior session POC never revisited = price magnet

Documented edge: VAH/VAL tested 90-93% of sessions on NQ. POC reversion on
range days ~65% WR at 2:1 R:R.

No new data needed — computed from existing OHLCV bars.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

EST = ZoneInfo("America/New_York")

VALUE_AREA_PCT  = 0.70    # 70% of volume defines the value area
BUCKET_PTS      = 2.0     # 2-point buckets (standard for NQ)
NAKED_TOLERANCE = 3.0     # pts — a VPOC is "touched" if price comes within this


@dataclass
class VolumeProfileLevels:
    poc:          float           # price of highest-volume bucket
    vah:          float           # value area high (top of 70% volume)
    val:          float           # value area low
    naked_vpocs:  list[float] = field(default_factory=list)  # unvisited prior POCs
    session_date: Optional[date] = None


def _build_profile(session_df: pd.DataFrame, bucket_pts: float = BUCKET_PTS) -> dict[float, float]:
    """
    Build price → volume map from OHLCV bars.
    Distributes each bar's volume uniformly across High-Low range buckets.
    """
    profile: dict[float, float] = {}
    for _, row in session_df.iterrows():
        high  = float(row["High"])
        low   = float(row["Low"])
        vol   = float(row["Volume"])
        rng   = high - low

        if rng < bucket_pts or vol <= 0:
            # Doji bar — put all volume at close price bucket
            bucket = round(float(row["Close"]) / bucket_pts) * bucket_pts
            profile[bucket] = profile.get(bucket, 0.0) + vol
            continue

        # Distribute volume uniformly across all buckets in the bar range
        n_buckets = max(1, int(rng / bucket_pts))
        vol_per_bucket = vol / n_buckets
        lo_bucket = round(low  / bucket_pts) * bucket_pts
        hi_bucket = round(high / bucket_pts) * bucket_pts
        b = lo_bucket
        while b <= hi_bucket + 1e-6:
            profile[b] = profile.get(b, 0.0) + vol_per_bucket
            b += bucket_pts

    return profile


def _compute_levels_from_profile(profile: dict[float, float]) -> tuple[float, float, float]:
    """Return (POC, VAH, VAL) from a price→volume profile dict."""
    if not profile:
        return 0.0, 0.0, 0.0

    total_vol = sum(profile.values())
    target_vol = total_vol * VALUE_AREA_PCT

    # POC = highest-volume bucket
    poc = max(profile, key=profile.get)

    # Expand outward from POC until 70% of volume is included
    sorted_prices = sorted(profile.keys())
    poc_idx = sorted_prices.index(poc)
    included_vol = profile[poc]
    lo_idx = poc_idx
    hi_idx = poc_idx

    while included_vol < target_vol:
        expand_up   = hi_idx < len(sorted_prices) - 1
        expand_down = lo_idx > 0

        if not expand_up and not expand_down:
            break

        up_vol   = profile[sorted_prices[hi_idx + 1]] if expand_up   else -1
        down_vol = profile[sorted_prices[lo_idx - 1]] if expand_down else -1

        if up_vol >= down_vol:
            hi_idx      += 1
            included_vol += profile[sorted_prices[hi_idx]]
        else:
            lo_idx      -= 1
            included_vol += profile[sorted_prices[lo_idx]]

    return poc, sorted_prices[hi_idx], sorted_prices[lo_idx]


def compute_session_profile(
    df: pd.DataFrame,
    session_date: date,
    bucket_pts: float = BUCKET_PTS,
) -> Optional[VolumeProfileLevels]:
    """Compute Volume Profile for a specific session date."""
    est_idx = df.index.tz_convert(EST)
    mask = est_idx.date == session_date
    session_df = df[mask]

    if len(session_df) < 5:
        return None

    profile = _build_profile(session_df, bucket_pts)
    if not profile:
        return None

    poc, vah, val = _compute_levels_from_profile(profile)
    return VolumeProfileLevels(poc=poc, vah=vah, val=val, session_date=session_date)


def get_prior_session_levels(
    df: pd.DataFrame,
    today: date,
) -> Optional[VolumeProfileLevels]:
    """Return prior session's POC/VAH/VAL — the main intraday reference."""
    est_idx = df.index.tz_convert(EST)
    all_dates = sorted(set(d for d in est_idx.date if d < today))
    if not all_dates:
        return None
    return compute_session_profile(df, all_dates[-1])


def get_naked_vpocs(
    df: pd.DataFrame,
    today: date,
    lookback_sessions: int = 20,
    max_naked: int = 3,
) -> list[float]:
    """
    Find POCs from the last N sessions that price has NEVER traded back to.
    These are price magnets — add them to the live monitor level list.
    """
    est_idx = df.index.tz_convert(EST)
    all_dates = sorted(set(d for d in est_idx.date if d < today))
    if len(all_dates) < 2:
        return []

    session_dates = all_dates[-lookback_sessions:]
    today_df = df[est_idx.date == today] if any(est_idx.date == today) else pd.DataFrame()

    naked: list[float] = []
    for session_date in reversed(session_dates[:-1]):  # skip most recent — it's the reference
        profile_levels = compute_session_profile(df, session_date)
        if profile_levels is None:
            continue

        poc = profile_levels.poc
        # Check if any subsequent session (up to today) touched this POC
        subsequent_dates = [d for d in all_dates if d > session_date]
        touched = False
        for sub_date in subsequent_dates:
            sub_df = df[est_idx.date == sub_date]
            if sub_df.empty:
                continue
            sub_low  = float(sub_df["Low"].min())
            sub_high = float(sub_df["High"].max())
            if sub_low <= poc + NAKED_TOLERANCE and sub_high >= poc - NAKED_TOLERANCE:
                touched = True
                break

        if not touched:
            naked.append(poc)
            if len(naked) >= max_naked:
                break

    return naked


def proximity_to_va_edge(
    price: float,
    levels: VolumeProfileLevels,
    tolerance_pts: float = 5.0,
) -> str:
    """
    Returns proximity classification for confidence scoring.
    Used to add +1 confidence point when a signal fires near a VP level.
    """
    if not levels:
        return "none"

    if abs(price - levels.poc) <= tolerance_pts:
        return "at_poc"
    if abs(price - levels.vah) <= tolerance_pts:
        return "at_vah"
    if abs(price - levels.val) <= tolerance_pts:
        return "at_val"
    if levels.val <= price <= levels.vah:
        return "inside_va"
    return "outside_va"
