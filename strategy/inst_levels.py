"""
Key Institutional Price Levels — PDH/PDL/PMH/PML.

Previous Day High/Low and Premarket High/Low are the most-watched reference
levels by professional trading desks. Every Bloomberg terminal shows them.
Every algo has them as inputs.

Two playable setups:
  PDH/PDL Rejection  — price pokes above PDH then closes back below → short
  PDH/PDL Retest     — price breaks above PDH, pulls back to it → long continuation

All computable from existing OHLCV — no new data feed needed.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

EST = ZoneInfo("America/New_York")


@dataclass
class KeyLevels:
    pdh: float          # prior day high (RTH 9:30–16:00)
    pdl: float          # prior day low
    pmh: float          # premarket high (08:00–09:30)
    pml: float          # premarket low
    prior_close: float  # prior day closing price


@dataclass
class PDLevelSignal:
    direction:      str    # "long" or "short"
    entry:          float
    stop:           float
    target:         float
    level_type:     str    # "pdh_reject"|"pdl_reject"|"pdh_retest"|"pdl_retest"|"pmh_react"|"pml_react"
    level_price:    float
    signal_bar_idx: int


def get_key_levels(df: pd.DataFrame, today: date) -> Optional[KeyLevels]:
    """
    Extract PDH/PDL from prior RTH session and PMH/PML from today's premarket.
    Returns None if insufficient data.
    """
    est_idx = df.index.tz_convert(EST)
    df2 = df.copy()
    df2["_date"] = est_idx.date
    df2["_hour"] = est_idx.hour
    df2["_min"]  = est_idx.minute

    # Prior RTH session — last trading day before today
    prior_days = sorted(set(d for d in df2["_date"].unique() if d < today))
    if not prior_days:
        return None
    prior_day = prior_days[-1]

    prior_rth = df2[
        (df2["_date"] == prior_day) &
        (df2["_hour"] >= 9) &
        ((df2["_hour"] < 16) | ((df2["_hour"] == 9) & (df2["_min"] >= 30)))
    ]
    if prior_rth.empty:
        return None

    pdh = float(prior_rth["High"].max())
    pdl = float(prior_rth["Low"].min())
    prior_close = float(prior_rth["Close"].iloc[-1])

    # Premarket today: 08:00–09:29 ET
    pm_bars = df2[
        (df2["_date"] == today) &
        (
            (df2["_hour"] == 8) |
            ((df2["_hour"] == 9) & (df2["_min"] < 30))
        )
    ]

    pmh = float(pm_bars["High"].max())  if not pm_bars.empty else 0.0
    pml = float(pm_bars["Low"].min())   if not pm_bars.empty else 0.0

    return KeyLevels(
        pdh=pdh, pdl=pdl,
        pmh=pmh, pml=pml,
        prior_close=prior_close,
    )


def detect_pd_level_signals(
    df: pd.DataFrame,
    today: date,
    atr: float,
    levels: KeyLevels,
) -> list[PDLevelSignal]:
    """
    Scan today's bars (9:35–11:30 AM) for PDH/PDL/PMH/PML reaction setups.

    PDH Rejection: price pokes above PDH then bar closes back below → short
    PDH Retest:    price broke above PDH on prior bar, pulls back to touch PDH → long
    PDL symmetric.
    PMH/PML: same logic.
    """
    if not levels or atr <= 0:
        return []

    est_idx = df.index.tz_convert(EST)
    today_mask = est_idx.date == today
    today_df = df[today_mask].copy().reset_index()

    signals: list[PDLevelSignal] = []
    used_types: set[str] = set()

    POKE_BUFFER = max(2.0, atr * 0.01)   # how far above PDH counts as a "poke"
    RETEST_TOL  = max(3.0, atr * 0.015)  # how close to PDH counts as a retest

    check_levels = [
        ("pdh", levels.pdh, "pdh_reject", "pdh_retest"),
        ("pdl", levels.pdl, "pdl_reject", "pdl_retest"),
    ]
    if levels.pmh > 0:
        check_levels.append(("pmh", levels.pmh, "pmh_react", "pmh_react"))
    if levels.pml > 0:
        check_levels.append(("pml", levels.pml, "pml_react", "pml_react"))

    for i, row in today_df.iterrows():
        ts = row["index"] if "index" in row else today_df.iloc[i].name
        try:
            dt = ts.astimezone(EST)
        except Exception:
            continue
        mins = dt.hour * 60 + dt.minute
        if mins < 9 * 60 + 35:
            continue
        if mins >= 11 * 60 + 30:
            break

        high  = float(row["High"])
        low   = float(row["Low"])
        close = float(row["Close"])
        open_ = float(row["Open"])

        global_idx = df.index.get_loc(ts) if ts in df.index else i

        for name, lvl, reject_type, retest_type in check_levels:
            if lvl <= 0:
                continue

            # PDH / PMH rejection short: price pokes above then closes back below
            if name in ("pdh", "pmh") and reject_type not in used_types:
                if high > lvl + POKE_BUFFER and close < lvl:
                    stop   = high + max(2.0, atr * 0.02)
                    target = lvl - atr * 0.08
                    if stop - close < atr * 0.5 and close > target:
                        used_types.add(reject_type)
                        signals.append(PDLevelSignal(
                            direction="short", entry=close,
                            stop=stop, target=target,
                            level_type=reject_type, level_price=lvl,
                            signal_bar_idx=global_idx,
                        ))

            # PDL / PML rejection long: price pokes below then closes back above
            if name in ("pdl", "pml") and reject_type not in used_types:
                if low < lvl - POKE_BUFFER and close > lvl:
                    stop   = low - max(2.0, atr * 0.02)
                    target = lvl + atr * 0.08
                    if close - stop < atr * 0.5 and close < target:
                        used_types.add(reject_type)
                        signals.append(PDLevelSignal(
                            direction="long", entry=close,
                            stop=stop, target=target,
                            level_type=reject_type, level_price=lvl,
                            signal_bar_idx=global_idx,
                        ))

            # PDH retest long: prior bar broke above PDH, now pulling back to test it
            if name == "pdh" and retest_type not in used_types and i > 0:
                prev_close = float(today_df.iloc[i - 1]["Close"])
                if prev_close > lvl and abs(low - lvl) <= RETEST_TOL:
                    stop   = lvl - max(3.0, atr * 0.02)
                    target = lvl + atr * 0.10
                    if close - stop < atr * 0.5 and close < target:
                        used_types.add(retest_type)
                        signals.append(PDLevelSignal(
                            direction="long", entry=close,
                            stop=stop, target=target,
                            level_type=retest_type, level_price=lvl,
                            signal_bar_idx=global_idx,
                        ))

            # PDL retest short
            if name == "pdl" and retest_type not in used_types and i > 0:
                prev_close = float(today_df.iloc[i - 1]["Close"])
                if prev_close < lvl and abs(high - lvl) <= RETEST_TOL:
                    stop   = lvl + max(3.0, atr * 0.02)
                    target = lvl - atr * 0.10
                    if stop - close < atr * 0.5 and close > target:
                        used_types.add(retest_type)
                        signals.append(PDLevelSignal(
                            direction="short", entry=close,
                            stop=stop, target=target,
                            level_type=retest_type, level_price=lvl,
                            signal_bar_idx=global_idx,
                        ))

    return signals


def level_proximity_score(price: float, levels: KeyLevels, atr: float) -> dict:
    """
    Returns how close the signal entry is to a key institutional level.
    Used in confidence scoring: +1 when signal fires near PDH/PDL/PMH/PML.
    """
    if not levels or atr <= 0:
        return {"nearest_level": "", "distance_pts": 999.0, "is_at_level": False}

    tol = max(5.0, atr * 0.03)
    candidates = [
        ("PDH", levels.pdh),
        ("PDL", levels.pdl),
    ]
    if levels.pmh > 0:
        candidates.append(("PMH", levels.pmh))
    if levels.pml > 0:
        candidates.append(("PML", levels.pml))

    nearest_name = ""
    nearest_dist = float("inf")
    for name, lvl in candidates:
        d = abs(price - lvl)
        if d < nearest_dist:
            nearest_dist = d
            nearest_name = name

    return {
        "nearest_level": nearest_name,
        "distance_pts":  nearest_dist,
        "is_at_level":   nearest_dist <= tol,
    }
