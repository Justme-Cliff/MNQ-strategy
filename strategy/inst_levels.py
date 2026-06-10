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

    Entry: open of the NEXT bar after the signal bar (consistent with all other strategies).
    Stop/Target: sized to produce >= 3:1 R:R — rejection uses poke-high + buffer as stop,
    and targets atr * 0.25 extension (comfortably 3:1 on a typical 8-10pt rejection stop).
    """
    if not levels or atr <= 0:
        return []

    est_idx = df.index.tz_convert(EST)
    today_mask = est_idx.date == today
    today_df = df[today_mask].copy().reset_index()

    signals: list[PDLevelSignal] = []
    used_types: set[str] = set()

    POKE_BUFFER = max(2.0, atr * 0.01)    # how far above PDH counts as a "poke"
    MAX_POKE    = min(20.0, atr * 0.025)  # poke larger than this = failed breakout, not rejection
    RETEST_TOL  = max(3.0, atr * 0.015)  # how close to PDH counts as a retest
    STOP_BUF    = max(2.0, min(5.0, atr * 0.005))  # buffer above rejection high (small, ATR-aware)
    MAX_RISK    = 25.0                    # prop firm stop cap

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

        # Need a next bar for entry
        if i + 1 >= len(today_df):
            continue

        high  = float(row["High"])
        low   = float(row["Low"])

        next_row   = today_df.iloc[i + 1]
        next_ts    = next_row["index"] if "index" in next_row else next_row.name
        try:
            entry_bar_global = df.index.get_loc(next_ts)
        except Exception:
            continue
        entry_open = float(next_row["Open"])

        for name, lvl, reject_type, retest_type in check_levels:
            if lvl <= 0:
                continue

            # PDH / PMH rejection short: poke above level, closes back below
            # Only valid when the poke is small — a 100-pt overshoot is a failed
            # breakout, not a rejection, and requires a 100+ pt stop (untradeable).
            if name in ("pdh", "pmh") and reject_type not in used_types:
                poke_size = high - lvl
                if POKE_BUFFER <= poke_size <= MAX_POKE and float(row["Close"]) < lvl:
                    stop   = high + STOP_BUF
                    entry  = entry_open
                    risk   = stop - entry
                    if risk <= 0 or risk > MAX_RISK:
                        continue
                    # Target: at least 3× risk below entry
                    target = entry - max(atr * 0.12, risk * 3.0)
                    if entry <= target:  # already at or past target
                        continue
                    used_types.add(reject_type)
                    signals.append(PDLevelSignal(
                        direction="short", entry=entry,
                        stop=stop, target=target,
                        level_type=reject_type, level_price=lvl,
                        signal_bar_idx=entry_bar_global,
                    ))

            # PDL / PML rejection long: poke below level, closes back above
            if name in ("pdl", "pml") and reject_type not in used_types:
                poke_size = lvl - low
                if POKE_BUFFER <= poke_size <= MAX_POKE and float(row["Close"]) > lvl:
                    stop   = low - STOP_BUF
                    entry  = entry_open
                    risk   = entry - stop
                    if risk <= 0 or risk > MAX_RISK:
                        continue
                    target = entry + max(atr * 0.12, risk * 3.0)
                    if entry >= target:
                        continue
                    used_types.add(reject_type)
                    signals.append(PDLevelSignal(
                        direction="long", entry=entry,
                        stop=stop, target=target,
                        level_type=reject_type, level_price=lvl,
                        signal_bar_idx=entry_bar_global,
                    ))

            # PDH retest long: prior bar broke above PDH, now pulls back to test it
            if name == "pdh" and retest_type not in used_types and i > 0:
                prev_close = float(today_df.iloc[i - 1]["Close"])
                if prev_close > lvl and abs(low - lvl) <= RETEST_TOL:
                    entry  = entry_open
                    stop   = lvl - STOP_BUF
                    risk   = entry - stop
                    if risk <= 0 or risk > MAX_RISK:
                        continue
                    target = entry + max(atr * 0.10, risk * 3.0)
                    if entry >= target:
                        continue
                    used_types.add(retest_type)
                    signals.append(PDLevelSignal(
                        direction="long", entry=entry,
                        stop=stop, target=target,
                        level_type=retest_type, level_price=lvl,
                        signal_bar_idx=entry_bar_global,
                    ))

            # PDL retest short: prior bar broke below PDL, now pulls back to test it
            if name == "pdl" and retest_type not in used_types and i > 0:
                prev_close = float(today_df.iloc[i - 1]["Close"])
                if prev_close < lvl and abs(high - lvl) <= RETEST_TOL:
                    entry  = entry_open
                    stop   = lvl + STOP_BUF
                    risk   = stop - entry
                    if risk <= 0 or risk > MAX_RISK:
                        continue
                    target = entry - max(atr * 0.10, risk * 3.0)
                    if entry <= target:
                        continue
                    used_types.add(retest_type)
                    signals.append(PDLevelSignal(
                        direction="short", entry=entry,
                        stop=stop, target=target,
                        level_type=retest_type, level_price=lvl,
                        signal_bar_idx=entry_bar_global,
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
