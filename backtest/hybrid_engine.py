"""
Hybrid Engine — Base Quant Strategies + Institutional Confidence Scoring.

Philosophy:
  The base system's trade signals are kept intact.
  Institutional signals score each trade 0–4 and map to contract size.
  Only BNS jumps and strongly opposing OFI are hard blocks.

Confidence score (0–4 points):
  +1  TSMOM aligned with signal direction (or strategy is exempt)
  +1  GEX bias favors this strategy type
  +1  ES lead-lag confirms direction
  +1  HMM state is bull or volatile (not bear during mean-rev trade)

Contract sizing:
  score >= 3  →  2 MNQ contracts  (institutional consensus)
  score 0–2   →  1 MNQ contract   (base sizing)

Hard blocks (always skip regardless of score):
  BNS jump detected at signal bar  — fat-tail risk, stops blow through
  OFI z-score |z| > 2.0 opposing  — strong institutional flow contra signal

This keeps the base system's 19 trades but doubles the size on high-conviction
setups. An ORB with TSMOM + ES + GEX all agreeing gets 2 lots → 2× P&L.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

from backtest.data_loader import load_nq, load_es, label_sessions
from strategy.quant_regime import classify_market_full, direction_allowed
from strategy.quant_gap  import detect as detect_gap
from strategy.quant_orb  import detect as detect_orb
from strategy.quant_ib   import detect as detect_ib
from strategy.quant_vwap import detect_all as detect_vwap
from strategy.quant_fvg  import detect as detect_fvg

from strategy.inst_harv    import bns_jump_flag
from strategy.inst_ofi     import get_ofi_zscore
from strategy.inst_hmm     import get_hmm_gate
from strategy.inst_gex     import compute_gex_proxy, load_vxn
from strategy.inst_tsmom   import get_session_tsmom, TSMOM_EXEMPT
from strategy.inst_leadlag import check_es_confirmation

EST = ZoneInfo("America/New_York")

MNQ_PER_POINT  = 2.0
MAX_RISK_PTS   = 25.0
MAX_TRADES_DAY = 2
MAX_DAILY_LOSS = 100.0

MEAN_REV_STRATS   = {"vwap_rev", "fvg", "ib_breakout"}
BREAKOUT_STRATS   = {"orb", "gap_fill"}

# Hard-block OFI threshold — stronger opposing flow than inst_engine uses
OFI_HARD_BLOCK_Z = 2.0


@dataclass
class HybridTrade:
    date:          date
    day_name:      str
    strategy:      str
    direction:     str
    entry:         float
    stop:          float
    target:        float
    exit_price:    float
    pnl:           float
    outcome:       str
    risk_pts:      float
    reward_pts:    float
    rr:            float
    vix:           float
    regime:        str
    trend_dir:     str   = ""
    n_contracts:   int   = 1
    # Confidence breakdown
    score:         int   = 0      # 0–4
    tsmom_pt:      int   = 0
    gex_pt:        int   = 0
    es_pt:         int   = 0
    hmm_pt:        int   = 0
    # Context
    hmm_state:     str   = "unavailable"
    gex_bias:      str   = "neutral"
    tsmom_bias:    str   = "neutral"
    signal_detail: str   = ""


# ── VIX helper ────────────────────────────────────────────────────────────────

def _load_vix(period: str = "90d") -> dict[date, float]:
    try:
        vix = yf.Ticker("^VIX").history(period=period, interval="1d", auto_adjust=True)
        if vix.empty:
            return {}
        result: dict[date, float] = {}
        for ts, row in vix.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        return result
    except Exception:
        return {}


def _get_vix(cache: dict, d: date) -> float:
    if d in cache:
        return cache[d]
    for lag in range(1, 6):
        if d - timedelta(days=lag) in cache:
            return cache[d - timedelta(days=lag)]
    return 18.0


# ── Trade simulation ──────────────────────────────────────────────────────────

def _simulate_trade(
    df: pd.DataFrame,
    signal_bar_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    n_contracts: int = 1,
    be_mult: float = 1.0,
) -> tuple[float, float, str]:
    """Simulate with trailing stop: stop moves to breakeven once be_mult×risk profit reached."""
    per_pt = MNQ_PER_POINT * n_contracts

    if direction == "long":
        risk_pts   = entry - stop
        reward_pts = target - entry
    else:
        risk_pts   = stop - entry
        reward_pts = entry - target

    current_stop = stop
    at_breakeven = False

    for i in range(signal_bar_idx, min(signal_bar_idx + 200, len(df))):
        row   = df.iloc[i]
        high  = float(row["High"])
        low   = float(row["Low"])
        close = float(row["Close"])
        open_ = float(row["Open"])

        if df.index[i].astimezone(EST).hour >= 12:
            pnl = (close - entry) * per_pt if direction == "long" \
                  else (entry - close) * per_pt
            return close, pnl, "LOSS" if pnl < 0 else "WIN"

        if direction == "long":
            if not at_breakeven and high >= entry + risk_pts * be_mult:
                current_stop = entry
                at_breakeven = True
            hit_stop   = low  <= current_stop
            hit_target = high >= target
            if hit_stop and hit_target:
                if close >= open_:
                    return target, reward_pts * per_pt, "WIN"
                pnl = (current_stop - entry) * per_pt
                return current_stop, pnl, "LOSS" if pnl < 0 else "WIN"
            elif hit_target:
                return target, reward_pts * per_pt, "WIN"
            elif hit_stop:
                pnl = (current_stop - entry) * per_pt
                return current_stop, pnl, "LOSS" if pnl < 0 else "WIN"
        else:
            if not at_breakeven and low <= entry - risk_pts * be_mult:
                current_stop = entry
                at_breakeven = True
            hit_stop   = high >= current_stop
            hit_target = low  <= target
            if hit_stop and hit_target:
                if close <= open_:
                    return target, reward_pts * per_pt, "WIN"
                pnl = (entry - current_stop) * per_pt
                return current_stop, pnl, "LOSS" if pnl < 0 else "WIN"
            elif hit_target:
                return target, reward_pts * per_pt, "WIN"
            elif hit_stop:
                pnl = (entry - current_stop) * per_pt
                return current_stop, pnl, "LOSS" if pnl < 0 else "WIN"

    last = float(df["Close"].iloc[-1])
    pnl  = (last - entry) * per_pt if direction == "long" \
           else (entry - last) * per_pt
    return last, pnl, "LOSS" if pnl < 0 else "WIN"


# ── Confidence scorer ─────────────────────────────────────────────────────────

def _score_trade(
    strategy: str,
    sig,
    today_df: pd.DataFrame,
    local_bar_pos: int,
    df: pd.DataFrame,
    es_df: pd.DataFrame,
    hmm: dict,
    gex: dict,
    tsmom: dict,
) -> tuple[int, dict]:
    """
    Score a trade signal 0–4 using institutional signals.
    Returns (score, breakdown_dict).
    Breakdown dict contains individual point values for reporting.
    """
    breakdown = {"tsmom": 0, "gex": 0, "es": 0, "hmm": 0}

    # ── TSMOM: +1 if session momentum aligns (or strategy is exempt) ──────────
    if strategy in TSMOM_EXEMPT:
        breakdown["tsmom"] = 1   # gap_fill is exempt → always gets the point
    elif not tsmom.get("available", False):
        breakdown["tsmom"] = 1   # not yet computed (early signal) → neutral, give point
    elif tsmom["bias"] == sig.direction:
        breakdown["tsmom"] = 1   # aligned
    elif tsmom["bias"] == "neutral":
        breakdown["tsmom"] = 1   # no momentum signal → not opposing → give point
    # else: opposing → 0

    # ── GEX: +1 if GEX favors this strategy type ─────────────────────────────
    bias = gex.get("bias", "neutral")
    if bias == "neutral":
        breakdown["gex"] = 1     # no gamma skew → no headwind
    elif bias == "mean_rev" and strategy in MEAN_REV_STRATS:
        breakdown["gex"] = 1     # dealers are pinning → mean-rev works
    elif bias == "breakout" and strategy in BREAKOUT_STRATS:
        breakdown["gex"] = 1     # dealers chasing → breakout works
    # else: opposing → 0

    # ── ES lead-lag: +1 if ES confirms direction ──────────────────────────────
    try:
        global_idx = sig.signal_bar_idx
        es_ok = check_es_confirmation(es_df, df, global_idx, sig.direction)
        breakdown["es"] = 1 if es_ok else 0
    except Exception:
        breakdown["es"] = 1      # unavailable → neutral, give point

    # ── HMM: +1 if market regime supports this trade ─────────────────────────
    state = hmm.get("state", "unavailable")
    if state == "unavailable":
        breakdown["hmm"] = 1     # can't penalize when model not trained yet
    elif state == "bull":
        breakdown["hmm"] = 1     # bull → all trades favored
    elif state == "volatile":
        # Volatile: good for breakouts, mixed for mean-rev
        breakdown["hmm"] = 1 if strategy in BREAKOUT_STRATS else 0
    elif state == "bear":
        # Bear: only short breakouts are favored
        if sig.direction == "short" and strategy in BREAKOUT_STRATS:
            breakdown["hmm"] = 1
        else:
            breakdown["hmm"] = 0

    score = sum(breakdown.values())
    return score, breakdown


# ── Hard-block check ──────────────────────────────────────────────────────────

def _is_hard_blocked(
    strategy: str,
    sig,
    today_df: pd.DataFrame,
    local_bar_pos: int,
) -> tuple[bool, str]:
    """
    Returns (blocked, reason). Only the clearest danger signals block a trade.
    """
    # BNS jump: fat-tail move at signal bar
    if bns_jump_flag(today_df, local_bar_pos):
        return True, "bns_jump"

    # OFI: institutional flow strongly opposing the trade
    ofi_z = get_ofi_zscore(today_df, local_bar_pos)
    if sig.direction == "long" and ofi_z < -OFI_HARD_BLOCK_Z:
        return True, "ofi_opposing"
    if sig.direction == "short" and ofi_z > OFI_HARD_BLOCK_Z:
        return True, "ofi_opposing"

    return False, ""


# ── Main hybrid backtest ──────────────────────────────────────────────────────

def run_hybrid_backtest(interval: str = "5m", period: str = "60d") -> list[HybridTrade]:
    print(f"[HYB] Loading NQ data ({period}/{interval}) ...")
    df = load_nq(interval=interval, period=period)
    df = label_sessions(df, interval=interval)
    print(f"[HYB] {len(df)} bars | {df.index[0].date()} → {df.index[-1].date()}")

    print("[HYB] Loading ES data ...")
    es_df = load_es(interval=interval, period=period)
    print(f"[HYB] ES: {len(es_df)} bars" if not es_df.empty else "[HYB] ES unavailable")

    print("[HYB] Loading VIX + VXN ...")
    vix_cache = _load_vix(period="90d")
    vxn_cache = load_vxn(period="90d")
    print(f"[HYB] VIX: {len(vix_cache)} days | VXN: {len(vxn_cache)} days")

    est_idx   = df.index.tz_convert(EST)
    all_dates = sorted(set(est_idx.date))
    trades:   list[HybridTrade] = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    hard_block_counts: dict[str, int] = {"bns_jump": 0, "ofi_opposing": 0}

    print(f"[HYB] Scanning {len(all_dates)} days ...")

    for today in all_dates:
        dow = today.weekday()
        if dow >= 5:
            continue

        vix    = _get_vix(vix_cache, today)
        market = classify_market_full(df, today, vix)
        atr    = market["atr"]
        trend  = market["ema_trend"]

        # Day-level institutional context (informational only — no hard blocks)
        hmm = get_hmm_gate(df, today)
        gex = compute_gex_proxy(vix_cache, vxn_cache, today)

        today_mask = est_idx.date == today
        today_df   = df[today_mask].copy()
        tsmom      = get_session_tsmom(today_df)

        trades_today = 0
        daily_pnl    = 0.0
        used_strats: set[str] = set()

        def _can_trade() -> bool:
            return trades_today < MAX_TRADES_DAY and daily_pnl > -MAX_DAILY_LOSS

        def _local_pos(sig) -> int:
            """Map global signal bar idx to local today_df position."""
            try:
                signal_ts = df.index[sig.signal_bar_idx]
                diffs = [abs((ts - signal_ts).total_seconds()) for ts in today_df.index]
                return int(np.argmin(diffs))
            except Exception:
                return min(sig.signal_bar_idx, len(today_df) - 1)

        def _try_hybrid(strategy: str, sig, detail: str = "") -> bool:
            nonlocal trades_today, daily_pnl

            if sig is None or not _can_trade():
                return False

            risk_pts = abs(sig.entry - sig.stop)
            if risk_pts < 1.0:
                return False

            local_pos = _local_pos(sig)

            # Hard-block check (BNS jump / strong opposing OFI)
            blocked, block_reason = _is_hard_blocked(strategy, sig, today_df, local_pos)
            if blocked:
                hard_block_counts[block_reason] = hard_block_counts.get(block_reason, 0) + 1
                return False

            # Confidence score → contract size
            score, breakdown = _score_trade(
                strategy, sig, today_df, local_pos,
                df, es_df, hmm, gex, tsmom,
            )
            n_contracts = 2 if score >= 3 else 1

            be_mult = 2.0 if strategy == "orb" else 1.0
            exit_p, pnl, outcome = _simulate_trade(
                df, sig.signal_bar_idx,
                sig.direction, sig.entry, sig.stop, sig.target,
                n_contracts=n_contracts, be_mult=be_mult,
            )
            reward_pts = abs(sig.target - sig.entry)
            rr = reward_pts / risk_pts if risk_pts > 0 else 0

            trades.append(HybridTrade(
                date=today, day_name=day_names[dow],
                strategy=strategy, direction=sig.direction,
                entry=sig.entry, stop=sig.stop, target=sig.target,
                exit_price=exit_p, pnl=pnl, outcome=outcome,
                risk_pts=risk_pts, reward_pts=reward_pts, rr=rr,
                vix=vix, regime=market["vix_regime"],
                trend_dir=trend["direction"],
                n_contracts=n_contracts,
                score=score,
                tsmom_pt=breakdown["tsmom"],
                gex_pt=breakdown["gex"],
                es_pt=breakdown["es"],
                hmm_pt=breakdown["hmm"],
                hmm_state=hmm["state"],
                gex_bias=gex["bias"],
                tsmom_bias=tsmom["bias"],
                signal_detail=detail,
            ))
            trades_today += 1
            daily_pnl    += pnl
            used_strats.add(strategy)
            return True

        vix_ok = vix < 25   # raised from 22 — mildly elevated VIX ok in strong trend

        # ── Priority 1: Gap Fill ──────────────────────────────────────────────
        if _can_trade():
            gap = detect_gap(df, today, atr, dow=dow)   # Monday filter + premarket bias
            if gap and direction_allowed(gap.direction, trend, strict=True):
                _try_hybrid("gap_fill", gap,
                            f"gap={gap.gap_size:.1f}pts ({gap.gap_ratio:.2f}xATR)")

        # ── Priority 2: FVG ───────────────────────────────────────────────────
        if _can_trade() and vix_ok and trend["direction"] == "neutral" and dow != 0:
            fvg = detect_fvg(df, today, atr, trend["direction"])
            if fvg and direction_allowed(fvg.direction, trend, strict=True):
                _try_hybrid("fvg", fvg,
                            f"zone={fvg.zone_size:.1f}pts trend={trend['direction']}")

        # ── Priority 3: ORB (pullback entry) ─────────────────────────────────
        if _can_trade() and vix_ok:
            orb = detect_orb(df, today, atr, dow)
            if orb:
                if orb.direction == "short":
                    ok = trend["direction"] == "strong_bear"
                else:
                    ok = trend["direction"] in ("strong_bull", "neutral")
                if ok:
                    _try_hybrid("orb", orb,
                                f"ORB={orb.orb_range:.0f}pts ({orb.atr_ratio:.2f}xATR) [{orb.entry_type}]")

        # ── Priority 4: IB Breakout ───────────────────────────────────────────
        if _can_trade() and vix_ok and dow != 0 and "orb" not in used_strats:
            if trend["direction"] == "neutral":
                ib = detect_ib(df, today, atr)
                if ib and direction_allowed(ib.direction, trend, strict=True):
                    _try_hybrid("ib_breakout", ib,
                                f"IB={ib.ib_range:.0f}pts ({ib.atr_ratio:.2f}xATR)")

        # ── Priority 5: AM VWAP Reversion ─────────────────────────────────────
        if _can_trade() and market["vwap_ok"]:
            remaining = MAX_TRADES_DAY - trades_today
            for vs in detect_vwap(df, today, vix, atr, max_signals=remaining):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_hybrid("vwap_rev", vs,
                                f"dev={vs.deviation_pts:.1f}pts ({vs.deviation_std:.1f}s)")

        # ── Priority 6: PM VWAP Reversion (1:30–3:30 PM) ────────────────────
        if _can_trade() and market["vwap_ok"]:
            remaining = MAX_TRADES_DAY - trades_today
            for vs in detect_vwap(df, today, vix, atr, max_signals=remaining,
                                  start_min=13*60+30, end_min=15*60+30):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_hybrid("vwap_pm", vs,
                                f"PM dev={vs.deviation_pts:.1f}pts ({vs.deviation_std:.1f}s)")

    run_hybrid_backtest._hard_blocks = hard_block_counts
    return trades


run_hybrid_backtest._hard_blocks = {}
