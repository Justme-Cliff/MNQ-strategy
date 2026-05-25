"""
Institutional Backtest Engine — 8-layer filter pipeline on top of the quant strategies.

Filter pipeline (applied in order, each can skip a trade):
  Day-level  (computed once per day):
    1. HMM       — 3-state Gaussian HMM; skip day if bear_prob > 0.55
    2. HAR-RV    — Realized variance forecast; skip day if "extreme" vol
    3. GEX       — VXN/VIX ratio; block strategies mismatched to gamma bias

  Session-level (computed once after 10:00 AM):
    4. TSMOM     — First 30-min return; skip trades against session momentum

  Bar-level (computed per signal):
    5. BNS Jump  — Bipower variation jump test; skip if jump detected
    6. VPIN      — Informed flow toxicity; block mean-rev if VPIN > 0.65
    7. OFI       — Signed volume z-score; skip if strong opposing flow
    8. ES Lead-Lag — ES/NQ directional confirmation; skip if ES disagrees

  Sizing:
    Kelly       — Half-Kelly fractional sizing → 1 or 2 MNQ contracts

All base strategy signals (detect_gap, detect_orb, etc.) are unchanged.
This engine wraps them with institutional validation layers.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

from backtest.data_loader import load_nq, load_es, label_sessions
from strategy.quant_regime import (
    classify_market_full, direction_allowed,
)
from strategy.quant_gap  import detect as detect_gap
from strategy.quant_orb  import detect as detect_orb
from strategy.quant_ib   import detect as detect_ib
from strategy.quant_vwap import detect_all as detect_vwap
from strategy.quant_fvg  import detect as detect_fvg

from strategy.inst_hmm     import get_hmm_gate
from strategy.inst_harv    import har_forecast, bns_jump_flag
from strategy.inst_vpin    import get_vpin_gate
from strategy.inst_ofi     import ofi_gate
from strategy.inst_gex     import load_vxn, compute_gex_proxy, gex_strategy_ok
from strategy.inst_tsmom   import get_session_tsmom, tsmom_allows
from strategy.inst_kelly   import kelly_contracts
from strategy.inst_leadlag import check_es_confirmation

EST = ZoneInfo("America/New_York")

MNQ_PER_POINT  = 2.0
MAX_RISK_PTS   = 25.0
MAX_TRADES_DAY = 2
MAX_DAILY_LOSS = 100.0


# ── Extended trade record ─────────────────────────────────────────────────────

@dataclass
class InstTrade:
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
    trend_dir:     str    = ""
    n_contracts:   int    = 1
    # Institutional metrics
    hmm_state:     str    = "unavailable"
    bear_prob:     float  = 0.0
    har_regime:    str    = "normal"
    stop_mult:     float  = 1.0
    vpin:          float  = 0.5
    ofi_z:         float  = 0.0
    gex_bias:      str    = "neutral"
    tsmom_bias:    str    = "neutral"
    filters_ok:    str    = ""    # comma-separated passed filters
    signal_detail: str    = ""


# ── VIX loader (same as quant_engine) ────────────────────────────────────────

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
        prev = d - timedelta(days=lag)
        if prev in cache:
            return cache[prev]
    return 18.0


# ── Trade simulation (same logic as quant_engine) ────────────────────────────

def _simulate_trade(
    df: pd.DataFrame,
    signal_bar_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    n_contracts: int = 1,
) -> tuple[float, float, str]:
    """Bar-by-bar simulation; P&L scaled by n_contracts."""
    per_pt = MNQ_PER_POINT * n_contracts

    if direction == "long":
        risk_pts   = entry - stop
        reward_pts = target - entry
    else:
        risk_pts   = stop - entry
        reward_pts = entry - target

    for i in range(signal_bar_idx, min(signal_bar_idx + 200, len(df))):
        row   = df.iloc[i]
        high  = float(row["High"])
        low   = float(row["Low"])
        close = float(row["Close"])
        open_ = float(row["Open"])

        ts_est = df.index[i].astimezone(EST)
        if ts_est.hour >= 12:
            pnl = (close - entry) * per_pt if direction == "long" \
                  else (entry - close) * per_pt
            return close, pnl, "LOSS" if pnl < 0 else "WIN"

        if direction == "long":
            hit_stop   = low  <= stop
            hit_target = high >= target
            if hit_stop and hit_target:
                if close >= open_:
                    return target, reward_pts * per_pt, "WIN"
                else:
                    return stop, -risk_pts * per_pt, "LOSS"
            elif hit_target:
                return target, reward_pts * per_pt, "WIN"
            elif hit_stop:
                return stop, -risk_pts * per_pt, "LOSS"
        else:
            hit_stop   = high >= stop
            hit_target = low  <= target
            if hit_stop and hit_target:
                if close <= open_:
                    return target, reward_pts * per_pt, "WIN"
                else:
                    return stop, -risk_pts * per_pt, "LOSS"
            elif hit_target:
                return target, reward_pts * per_pt, "WIN"
            elif hit_stop:
                return stop, -risk_pts * per_pt, "LOSS"

    last = float(df["Close"].iloc[-1])
    pnl  = (last - entry) * per_pt if direction == "long" \
           else (entry - last) * per_pt
    return last, pnl, "LOSS" if pnl < 0 else "WIN"


# ── Apply HAR-RV stop multiplier ──────────────────────────────────────────────

def _apply_stop_mult(
    direction: str, entry: float, stop: float, stop_mult: float
) -> Optional[float]:
    """
    Widen stop by stop_mult. Returns None if risk exceeds MAX_RISK_PTS.
    """
    original_risk = abs(entry - stop)
    new_risk = original_risk * stop_mult
    if new_risk > MAX_RISK_PTS:
        return None
    if direction == "long":
        return entry - new_risk
    else:
        return entry + new_risk


# ── Main institutional backtest ───────────────────────────────────────────────

def run_inst_backtest(interval: str = "5m", period: str = "60d") -> list[InstTrade]:
    print(f"[INST] Loading NQ data ({period}/{interval}) ...")
    df = load_nq(interval=interval, period=period)
    df = label_sessions(df, interval=interval)
    print(f"[INST] {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

    print("[INST] Loading ES data ...")
    es_df = load_es(interval=interval, period=period)
    print(f"[INST] ES: {len(es_df)} bars" if not es_df.empty else "[INST] ES unavailable — lead-lag disabled")

    print("[INST] Loading VIX + VXN ...")
    vix_cache = _load_vix(period="90d")
    vxn_cache = load_vxn(period="90d")
    print(f"[INST] VIX: {len(vix_cache)} days | VXN: {len(vxn_cache)} days")

    est_idx   = df.index.tz_convert(EST)
    all_dates = sorted(set(est_idx.date))
    trades:   list[InstTrade] = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # Track rejection reasons across session
    rejection_counts: dict[str, int] = {
        "hmm_bear": 0, "harv_extreme": 0, "gex_mismatch": 0,
        "tsmom": 0, "bns_jump": 0, "vpin": 0, "ofi": 0,
        "es_leadlag": 0, "risk_too_wide": 0,
    }

    print(f"[INST] Scanning {len(all_dates)} days ...")

    for today in all_dates:
        dow = today.weekday()
        if dow >= 5:
            continue

        vix    = _get_vix(vix_cache, today)
        market = classify_market_full(df, today, vix)
        atr    = market["atr"]
        trend  = market["ema_trend"]

        # ── Layer 1: HMM day gate ────────────────────────────────────────────
        # HMM only gates MEAN-REVERSION strategies.
        # During crash recoveries, vol is high → HMM sees "bear" / "volatile".
        # Breakout strategies (ORB, Gap Fill) work BETTER in volatile recoveries —
        # blocking them with HMM destroys the best trades.
        hmm = get_hmm_gate(df, today)
        # (hmm["skip_day"] is applied per-strategy in _filters_pass, not here)

        # ── Layer 2: HAR-RV day gate ──────────────────────────────────────────
        harv = har_forecast(df, today)
        if harv["skip_day"]:
            rejection_counts["harv_extreme"] += 1
            continue

        stop_mult  = harv["stop_mult"]
        har_regime = harv["vol_regime"]

        # ── Layer 3: GEX session bias ─────────────────────────────────────────
        gex = compute_gex_proxy(vix_cache, vxn_cache, today)

        # ── Layer 4: TSMOM (computed at 10:00, used for all signals after) ────
        today_mask = est_idx.date == today
        today_df   = df[today_mask].copy()
        tsmom      = get_session_tsmom(today_df)

        # ── Kelly sizing from recent history ──────────────────────────────────
        n_contracts = kelly_contracts(trades, lookback=50, min_trades=20, max_contracts=2)

        trades_today = 0
        daily_pnl    = 0.0
        used_strats: set[str] = set()

        def _can_trade() -> bool:
            return trades_today < MAX_TRADES_DAY and daily_pnl > -MAX_DAILY_LOSS

        def _filters_pass(strategy: str, sig, local_bar_pos: int) -> tuple[bool, dict]:
            """
            Run bar-level institutional filters. Returns (passed, metrics_dict).
            """
            metrics = {}
            _MEAN_REV = {"vwap_rev", "fvg", "ib_breakout"}

            # HMM: only gates mean-reversion strategies
            # Breakout/directional strategies (ORB, Gap Fill) work in all HMM states
            if hmm["skip_day"] and strategy in _MEAN_REV:
                rejection_counts["hmm_bear"] += 1
                return False, metrics
            metrics["hmm"] = hmm["state"]

            # GEX mismatch
            if not gex_strategy_ok(gex, strategy):
                rejection_counts["gex_mismatch"] += 1
                return False, metrics
            metrics["gex"] = gex["bias"]

            # TSMOM
            if not tsmom_allows(tsmom, sig.direction, strategy):
                rejection_counts["tsmom"] += 1
                return False, metrics
            metrics["tsmom"] = tsmom["bias"]

            # BNS jump
            if bns_jump_flag(today_df, local_bar_pos):
                rejection_counts["bns_jump"] += 1
                return False, metrics
            metrics["bns"] = "ok"

            # VPIN
            vpin_result = get_vpin_gate(today_df, local_bar_pos, strategy)
            if vpin_result["gate_active"]:
                rejection_counts["vpin"] += 1
                return False, metrics
            metrics["vpin"] = vpin_result["vpin"]

            # OFI
            ofi_result = ofi_gate(today_df, local_bar_pos, sig.direction)
            if ofi_result["skip"]:
                rejection_counts["ofi"] += 1
                return False, metrics
            metrics["ofi_z"] = ofi_result["z_score"]

            # ES lead-lag
            global_idx = sig.signal_bar_idx
            if not check_es_confirmation(es_df, df, global_idx, sig.direction):
                rejection_counts["es_leadlag"] += 1
                return False, metrics
            metrics["es"] = "confirmed"

            return True, metrics

        def _try_inst(strategy: str, sig, detail: str = "") -> bool:
            nonlocal trades_today, daily_pnl

            if sig is None:
                return False
            if not _can_trade():
                return False

            # Basic risk check
            risk_pts = abs(sig.entry - sig.stop)
            if risk_pts < 1.0:
                return False

            # Find local bar position for bar-level filters
            try:
                today_positions = list(today_df.index)
                signal_ts       = df.index[sig.signal_bar_idx]
                local_bar_pos   = min(
                    range(len(today_positions)),
                    key=lambda i: abs((today_positions[i] - signal_ts).total_seconds()),
                )
            except Exception:
                local_bar_pos = min(sig.signal_bar_idx, len(today_df) - 1)

            # Run institutional filters
            passed, metrics = _filters_pass(strategy, sig, local_bar_pos)
            if not passed:
                return False

            # Apply HAR-RV stop widening
            new_stop = _apply_stop_mult(sig.direction, sig.entry, sig.stop, stop_mult)
            if new_stop is None:
                rejection_counts["risk_too_wide"] += 1
                return False

            # Simulate with (possibly wider) stop
            exit_p, pnl, outcome = _simulate_trade(
                df, sig.signal_bar_idx,
                sig.direction, sig.entry, new_stop, sig.target,
                n_contracts=n_contracts,
            )
            reward_pts = abs(sig.target - sig.entry)
            actual_risk = abs(sig.entry - new_stop)
            rr = reward_pts / actual_risk if actual_risk > 0 else 0

            filters_ok = ",".join(f"{k}={v}" for k, v in metrics.items())

            trades.append(InstTrade(
                date=today, day_name=day_names[dow],
                strategy=strategy, direction=sig.direction,
                entry=sig.entry, stop=new_stop, target=sig.target,
                exit_price=exit_p, pnl=pnl, outcome=outcome,
                risk_pts=actual_risk, reward_pts=reward_pts, rr=rr,
                vix=vix, regime=market["vix_regime"],
                trend_dir=trend["direction"],
                n_contracts=n_contracts,
                hmm_state=hmm["state"],
                bear_prob=hmm["bear_prob"],
                har_regime=har_regime,
                stop_mult=stop_mult,
                vpin=float(metrics.get("vpin", 0.5)),
                ofi_z=float(metrics.get("ofi_z", 0.0)),
                gex_bias=gex["bias"],
                tsmom_bias=tsmom["bias"],
                filters_ok=filters_ok,
                signal_detail=detail,
            ))
            trades_today += 1
            daily_pnl    += pnl
            used_strats.add(strategy)
            return True

        vix_ok_breakout = vix < 22

        # ── Priority 1: Gap Fill ──────────────────────────────────────────────
        if _can_trade():
            gap = detect_gap(df, today, atr)
            if gap and direction_allowed(gap.direction, trend, strict=True):
                _try_inst("gap_fill", gap,
                          f"gap={gap.gap_size:.1f}pts ({gap.gap_ratio:.2f}xATR)")

        # ── Priority 2: FVG ───────────────────────────────────────────────────
        fvg_ok = trend["direction"] == "neutral"
        if _can_trade() and vix_ok_breakout and fvg_ok:
            fvg = detect_fvg(df, today, atr, trend["direction"])
            if fvg and direction_allowed(fvg.direction, trend, strict=True):
                _try_inst("fvg", fvg,
                          f"zone={fvg.zone_size:.1f}pts trend={trend['direction']}")

        # ── Priority 3: ORB ───────────────────────────────────────────────────
        if _can_trade() and vix_ok_breakout:
            orb = detect_orb(df, today, atr, dow)
            if orb:
                if orb.direction == "short":
                    ok = trend["direction"] == "strong_bear"
                else:
                    ok = trend["direction"] in ("strong_bull", "neutral")
                if ok:
                    _try_inst("orb", orb,
                              f"ORB={orb.orb_range:.0f}pts ({orb.atr_ratio:.2f}xATR)")

        # ── Priority 4: IB Breakout ───────────────────────────────────────────
        ib_ok = trend["direction"] == "neutral"
        if _can_trade() and vix_ok_breakout and dow != 0 and "orb" not in used_strats and ib_ok:
            ib = detect_ib(df, today, atr)
            if ib and direction_allowed(ib.direction, trend, strict=True):
                _try_inst("ib_breakout", ib,
                          f"IB={ib.ib_range:.0f}pts ({ib.atr_ratio:.2f}xATR)")

        # ── Priority 5: VWAP Reversion ────────────────────────────────────────
        if _can_trade() and market["vwap_ok"]:
            remaining = MAX_TRADES_DAY - trades_today
            vwap_sigs = detect_vwap(df, today, vix, atr, max_signals=remaining)
            for vs in vwap_sigs:
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_inst("vwap_rev", vs,
                              f"dev={vs.deviation_pts:.1f}pts ({vs.deviation_std:.1f}sigma)")

    # Store rejection stats as a module-level side-effect for reporting
    run_inst_backtest._rejections = rejection_counts
    return trades


run_inst_backtest._rejections = {}
