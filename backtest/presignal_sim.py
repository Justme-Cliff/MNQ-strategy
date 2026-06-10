"""
Pre-signal resting-order simulator — "can this strategy fire EARLY (rest an order
at a known level) without losing win rate?"

For each strategy we express the entry as a resting order at a price level known
in advance, fill it on first touch (stop for breakouts, limit for retests/fades/
bounces), apply the same SL/TP family, and simulate the outcome. We then compare
the resting (early) win rate to the rules-confirmed engine.

This is the gate: arm early ONLY the strategies whose resting WR holds. Pure fades
are expected to bleed WR here — that's the point of measuring instead of guessing.

Run: python3 -m backtest.presignal_sim
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

from backtest.data_loader import load_nq, label_sessions
from backtest.quant_engine import _simulate_trade, _load_vix, _get_vix
from strategy.quant_regime import (
    get_atr_adaptive, get_ema_trend, session_vwap, vwap_std_bands, direction_allowed,
)
from strategy.inst_levels import get_key_levels

EST = ZoneInfo("America/New_York")
MAX_RISK = 25.0
SESS_END_MIN = 12 * 60   # noon


def _mins(ts) -> int:
    dt = ts.astimezone(EST)
    return dt.hour * 60 + dt.minute


def _gidx(df, ts):
    return df.index.get_loc(ts)


def _fill_resting(today_df, arm_pos: int, level: float, side: str, otype: str) -> int | None:
    """First bar at/after arm_pos that touches `level`. stop=break-through, limit=trade-into."""
    H = today_df["High"].values.astype(float)
    L = today_df["Low"].values.astype(float)
    for i in range(arm_pos, len(today_df)):
        if _mins(today_df.index[i]) >= SESS_END_MIN:
            return None
        if otype == "stop":
            if side == "long" and H[i] >= level:  return i
            if side == "short" and L[i] <= level: return i
        else:  # limit
            if side == "long" and L[i] <= level:  return i
            if side == "short" and H[i] >= level: return i
    return None


def _record(df, today_df, fill_pos, side, entry, stop, target, strat, out):
    if abs(entry - stop) < 1.0 or abs(entry - stop) > MAX_RISK + 0.5:
        return
    gidx = _gidx(df, today_df.index[fill_pos])
    _, pnl, outcome = _simulate_trade(df, gidx, side, entry, stop, target, max_hour=12)
    out.append((strat, side, outcome, pnl))


def simulate_day(df, today: date, atr: float, trend: str, vix: float, out: list):
    est = df.index.tz_convert(EST)
    today_df = df[est.date == today].copy()
    if len(today_df) < 8 or atr <= 0:
        return
    tmins = np.array([_mins(ts) for ts in today_df.index])

    # ── ORB: buy/sell-STOP at the 5-min opening range ────────────────────────
    orb_pos = next((i for i, m in enumerate(tmins) if m == 9 * 60 + 30), None)
    if orb_pos is not None:
        orb_hi = float(today_df["High"].iloc[orb_pos]); orb_lo = float(today_df["Low"].iloc[orb_pos])
        rng = orb_hi - orb_lo
        if rng >= max(3.0, atr * 0.025) and rng <= atr * 0.50:
            arm = orb_pos + 1
            if trend in ("strong_bull", "bull", "neutral"):
                fp = _fill_resting(today_df, arm, orb_hi, "long", "stop")
                if fp is not None:
                    stop = orb_hi - min(rng * 0.5, MAX_RISK); risk = orb_hi - stop
                    _record(df, today_df, fp, "long", orb_hi, stop, orb_hi + min(rng, risk * 3), "orb", out)
            if trend in ("strong_bear", "bear"):
                fp = _fill_resting(today_df, arm, orb_lo, "short", "stop")
                if fp is not None:
                    stop = orb_lo + min(rng * 0.5, MAX_RISK); risk = stop - orb_lo
                    _record(df, today_df, fp, "short", orb_lo, stop, orb_lo - min(rng, risk * 3), "orb", out)

    # ── IB: buy/sell-STOP at the 9:30-9:55 initial balance ───────────────────
    ib_mask = (tmins >= 9 * 60 + 30) & (tmins <= 9 * 60 + 55)
    if ib_mask.sum() >= 4:
        ib_hi = float(today_df["High"].values[ib_mask].max()); ib_lo = float(today_df["Low"].values[ib_mask].min())
        rng = ib_hi - ib_lo
        if rng >= max(5.0, atr * 0.05) and rng <= atr * 0.65:
            arm = next((i for i, m in enumerate(tmins) if m >= 10 * 60), None)
            if arm is not None:
                if trend in ("strong_bull", "bull", "neutral"):
                    fp = _fill_resting(today_df, arm, ib_hi, "long", "stop")
                    if fp is not None:
                        stop = ib_hi - min(rng * 0.5, MAX_RISK); risk = ib_hi - stop
                        _record(df, today_df, fp, "long", ib_hi, stop, ib_hi + rng * 1.5, "ib_breakout", out)
                if trend in ("strong_bear", "bear"):
                    fp = _fill_resting(today_df, arm, ib_lo, "short", "stop")
                    if fp is not None:
                        stop = ib_lo + min(rng * 0.5, MAX_RISK); risk = stop - ib_lo
                        _record(df, today_df, fp, "short", ib_lo, stop, ib_lo - rng * 1.5, "ib_breakout", out)

    # ── PDH/PDL ───────────────────────────────────────────────────────────────
    kl = get_key_levels(df, today)
    if kl and kl.pdh > 0 and kl.pdl > 0:
        buf = max(3.0, atr * 0.05)
        # RETEST (continuation): after price breaks the level, rest a LIMIT back at it
        broke_hi = broke_lo = None
        H = today_df["High"].values.astype(float); L = today_df["Low"].values.astype(float)
        for i in range(len(today_df)):
            if _mins(today_df.index[i]) >= SESS_END_MIN: break
            if broke_hi is None and H[i] > kl.pdh: broke_hi = i
            if broke_lo is None and L[i] < kl.pdl: broke_lo = i
        if broke_hi is not None and trend in ("strong_bull", "bull", "neutral"):
            fp = _fill_resting(today_df, broke_hi + 1, kl.pdh, "long", "limit")
            if fp is not None:
                stop = kl.pdh - buf; _record(df, today_df, fp, "long", kl.pdh, stop, kl.pdh + (kl.pdh - stop) * 3, "pd_retest", out)
        if broke_lo is not None and trend in ("strong_bear", "bear"):
            fp = _fill_resting(today_df, broke_lo + 1, kl.pdl, "short", "limit")
            if fp is not None:
                stop = kl.pdl + buf; _record(df, today_df, fp, "short", kl.pdl, stop, kl.pdl - (stop - kl.pdl) * 3, "pd_retest", out)
        # REJECTION (fade): rest a LIMIT at the level anticipating a reversal
        arm0 = next((i for i, m in enumerate(tmins) if m >= 9 * 60 + 35), 0)
        fp = _fill_resting(today_df, arm0, kl.pdh, "short", "limit")
        if fp is not None:
            stop = kl.pdh + buf; _record(df, today_df, fp, "short", kl.pdh, stop, kl.pdh - (stop - kl.pdh) * 3, "pd_reject", out)
        fp = _fill_resting(today_df, arm0, kl.pdl, "long", "limit")
        if fp is not None:
            stop = kl.pdl - buf; _record(df, today_df, fp, "long", kl.pdl, stop, kl.pdl + (kl.pdl - stop) * 3, "pd_reject", out)

    # ── VWAP bounce (trend continuation) & reversion (fade) — limit at level ─
    if vix < 25:
        vwap = session_vwap(today_df)
        _, upper, lower = vwap_std_bands(today_df, n_std=1.5)
        sd = max(8.0, atr * 0.06)
        for i in range(len(today_df)):
            m = tmins[i]
            if m < 9 * 60 + 45 or m >= SESS_END_MIN: continue
            lo = float(today_df["Low"].iloc[i]); hi = float(today_df["High"].iloc[i])
            vw = float(vwap.iloc[i]); lb = float(lower.iloc[i]); ub = float(upper.iloc[i])
            # bounce: dip to VWAP in trend
            if trend in ("bull", "strong_bull") and lo <= vw <= hi:
                _record(df, today_df, i, "long", vw, vw - sd * 0.5, vw + max(12.0, atr * 0.08), "vwap_bounce", out); break
        for i in range(len(today_df)):
            m = tmins[i]
            if m < 9 * 60 + 45 or m >= SESS_END_MIN: continue
            lo = float(today_df["Low"].iloc[i]); vw = float(vwap.iloc[i]); lb = float(lower.iloc[i])
            if lo <= lb:   # reversion long at lower band
                _record(df, today_df, i, "long", lb, lb - sd, vw, "vwap_rev", out); break


def run(period="60d"):
    df = label_sessions(load_nq(interval="5m", period=period), interval="5m")
    vix_cache = _load_vix("90d")
    est = df.index.tz_convert(EST)
    days = sorted(set(d for d in est.date if d.weekday() < 5))
    out: list = []
    for d in days:
        atr = get_atr_adaptive(df, d)
        trend = get_ema_trend(df, d)["direction"]
        vix = _get_vix(vix_cache, d)
        simulate_day(df, d, atr, trend, vix, out)
    return out


if __name__ == "__main__":
    res = run("60d")
    by = defaultdict(list)
    for strat, side, outcome, pnl in res:
        by[strat].append((outcome, pnl))
    print("=" * 60)
    print("RESTING-ORDER (fire-early) backtest — 60d, 9:30-noon")
    print("=" * 60)
    print(f"{'strategy':<14} {'trades':>6} {'WR':>6} {'PnL':>9}")
    tot_w = tot = 0
    for s in sorted(by):
        rows = by[s]; w = sum(1 for o, _ in rows if o == "WIN")
        tot_w += w; tot += len(rows)
        print(f"{s:<14} {len(rows):>6} {w/len(rows)*100:>5.0f}% {sum(p for _, p in rows):>+8.0f}")
    if tot:
        print("-" * 40)
        print(f"{'TOTAL':<14} {tot:>6} {tot_w/tot*100:>5.0f}%")
    print("\n(compare each to the rules-confirmed engine; arm early only those that hold WR)")
