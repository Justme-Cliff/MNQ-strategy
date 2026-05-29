"""
Hybrid Engine — Base Quant Strategies + Full 12-Point Institutional Scoring.

Philosophy:
  The base system's trade signals are kept intact.
  Institutional signals score each trade 0–12 and map to contract size.
  Hard blocks prevent the worst trades; soft scoring rewards the best ones.

Confidence score (0–12 points):
  +1  TSMOM aligned with signal direction (or exempt)
  +1  GEX bias favors this strategy type
  +1  ES lead-lag confirms direction
  +1  HMM state is bull or volatile
  +1  CVD divergence confirms (or no divergence)
  +1  Overnight range type matches strategy type
  +1  VIX term structure supports strategy type
  +1  XLK sector bias aligned
  +1  DXY+TNX macro not a strong headwind
  +1  NQ/ES spread not extended against signal
  +1  Session conviction matches strategy type
  +1  Open type hint matches strategy type
  +1  (memory bonus) strategy recently performing well

Contract sizing:
  score 10-12  →  2 MNQ contracts  (full institutional consensus)
  score 7-9    →  1 MNQ contract   (strong signal, standard size)
  score 4-6    →  1 MNQ contract   (no size but still trade)
  score ≤ 3   →  SKIP             (weak setup, no institutional backing)

Hard blocks (any one blocks regardless of score):
  BNS jump detected
  OFI z-score |z| > 2.0 opposing
  HAR extreme vol forecast (skip day)
  VVIX > 130 (vol-of-vol crisis)
  VIX deep backwardation (size_mult = 0)
  Macro strong headwind + mean-rev long signal
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
from strategy.quant_vwap import detect_all as detect_vwap, detect_bounce as detect_vwap_bounce
from strategy.quant_fvg  import detect as detect_fvg

from strategy.inst_harv    import bns_jump_flag, har_forecast
from strategy.inst_ofi     import get_ofi_zscore, get_cvd_divergence
from strategy.inst_hmm     import get_hmm_gate
from strategy.inst_gex     import compute_gex_proxy, load_vxn
from strategy.inst_tsmom   import get_session_tsmom, get_session_conviction, TSMOM_EXEMPT
from strategy.inst_leadlag import check_es_confirmation, get_nq_es_spread_signal
from strategy.inst_sectors import get_tech_sector_bias, load_sector_data
from strategy.inst_macro   import get_macro_bias, load_macro_data
from strategy.bot_memory   import get_conf_adjustment

EST = ZoneInfo("America/New_York")

MNQ_PER_POINT  = 2.0
MAX_RISK_PTS   = 25.0
MAX_TRADES_DAY = 3
MAX_DAILY_LOSS = 150.0

MEAN_REV_STRATS = {"vwap_rev", "vwap_pm", "fvg", "ib_breakout"}
BREAKOUT_STRATS = {"orb", "gap_fill"}

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
    score:         int   = 0
    score_breakdown: dict = field(default_factory=dict)
    hmm_state:     str   = "unavailable"
    gex_bias:      str   = "neutral"
    tsmom_bias:    str   = "neutral"
    signal_detail: str   = ""
    stop_mult:     float = 1.0


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


def _load_extended_vix(ticker: str, period: str = "90d") -> dict[date, float]:
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        result: dict[date, float] = {}
        for ts, row in hist.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        return result
    except Exception:
        return {}


def _get_ext_vix(cache: dict, d: date) -> Optional[float]:
    if not cache:
        return None
    if d in cache:
        return cache[d]
    for lag in range(1, 6):
        key = d - timedelta(days=lag)
        if key in cache:
            return cache[key]
    return None


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
    max_hour: int = 12,
) -> tuple[float, float, str]:
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

        if df.index[i].astimezone(EST).hour >= max_hour:
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


# ── Confidence scorer (0–12 points) ──────────────────────────────────────────

def _score_trade(
    strategy:   str,
    sig,
    today_df:   pd.DataFrame,
    local_bar_pos: int,
    df:         pd.DataFrame,
    es_df:      pd.DataFrame,
    hmm:        dict,
    gex:        dict,
    tsmom:      dict,
    market:     dict,
    sector:     dict,
    macro:      dict,
    nq_es_spread: dict,
) -> tuple[int, dict]:
    """Score a trade 0–12 using all institutional signals."""
    bd: dict[str, int] = {}

    # 1. TSMOM: first 30-min momentum aligned?
    if strategy in TSMOM_EXEMPT:
        bd["tsmom"] = 1
    elif not tsmom.get("available", False):
        bd["tsmom"] = 1
    elif tsmom["bias"] == sig.direction:
        bd["tsmom"] = 1
    elif tsmom["bias"] == "neutral":
        bd["tsmom"] = 1
    else:
        bd["tsmom"] = 0

    # 2. GEX ratio: gamma regime favors strategy type?
    bias = gex.get("bias", "neutral")
    if bias == "neutral":
        bd["gex"] = 1
    elif bias == "mean_rev" and strategy in MEAN_REV_STRATS:
        bd["gex"] = 1
    elif bias == "breakout" and strategy in BREAKOUT_STRATS:
        bd["gex"] = 1
    else:
        bd["gex"] = 0

    # 3. ES lead-lag: ES confirms signal direction?
    try:
        es_ok = check_es_confirmation(es_df, df, sig.signal_bar_idx, sig.direction)
        bd["es"] = 1 if es_ok else 0
    except Exception:
        bd["es"] = 1

    # 4. HMM: regime state supports this trade?
    state = hmm.get("state", "unavailable")
    if state == "unavailable":
        bd["hmm"] = 1
    elif state == "bull":
        bd["hmm"] = 1
    elif state == "volatile":
        bd["hmm"] = 1 if strategy in BREAKOUT_STRATS else 0
    elif state == "bear":
        bd["hmm"] = 1 if (sig.direction == "short" and strategy in BREAKOUT_STRATS) else 0
    else:
        bd["hmm"] = 1

    # 5. CVD divergence: cumulative delta confirms direction?
    try:
        cvd = get_cvd_divergence(today_df, local_bar_pos)
        div = cvd.get("divergence", "none")
        if div == "none":
            bd["cvd"] = 1
        elif div == "bearish" and sig.direction == "short":
            bd["cvd"] = 1
        elif div == "bullish" and sig.direction == "long":
            bd["cvd"] = 1
        else:
            bd["cvd"] = 0
    except Exception:
        bd["cvd"] = 1

    # 6. Overnight range: day type matches strategy type?
    ov = market.get("overnight", {})
    if ov.get("day_type_bias") == "expansion" and strategy in BREAKOUT_STRATS:
        bd["overnight"] = 1
    elif ov.get("day_type_bias") == "rotation" and strategy in MEAN_REV_STRATS:
        bd["overnight"] = 1
    elif ov.get("day_type_bias") == "neutral":
        bd["overnight"] = 1
    elif not ov:
        bd["overnight"] = 1
    else:
        bd["overnight"] = 0

    # 7. VIX term structure: contango/backwardation aligns with strategy?
    vix_term = market.get("vix_term", {})
    structure = vix_term.get("structure", "contango")
    if structure in ("deep_contango", "contango", "flat"):
        bd["vix_term"] = 1   # calm = all strategies fine
    elif structure in ("backwardation", "deep_backwardation") and strategy in BREAKOUT_STRATS:
        bd["vix_term"] = 1   # stress = only breakouts
    elif structure in ("backwardation", "deep_backwardation") and strategy in MEAN_REV_STRATS:
        bd["vix_term"] = 0   # stress + mean-rev = bad combo
    else:
        bd["vix_term"] = 1

    # 8. XLK sector bias: tech flow aligned with signal direction?
    if not sector.get("available", False):
        bd["sector"] = 1
    elif sig.direction == "long" and sector.get("long_favored", False):
        bd["sector"] = 1
    elif sig.direction == "short" and sector.get("short_favored", False):
        bd["sector"] = 1
    elif sector.get("bias") == "neutral":
        bd["sector"] = 1
    else:
        bd["sector"] = 0

    # 9. Macro DXY+TNX: no strong headwind for this signal direction?
    if not macro.get("available", False):
        bd["macro"] = 1
    elif macro.get("combined") == "strong_headwind" and sig.direction == "long":
        bd["macro"] = 0
    elif macro.get("combined") == "tailwind" and sig.direction == "long":
        bd["macro"] = 1
    elif macro.get("short_favored", False) and sig.direction == "short":
        bd["macro"] = 1
    else:
        bd["macro"] = 1

    # 10. NQ/ES spread: NQ fairly priced relative to ES?
    if not nq_es_spread.get("available", False):
        bd["nq_es_spread"] = 1
    elif sig.direction == "long" and nq_es_spread.get("nq_favor_long", False):
        bd["nq_es_spread"] = 1
    elif sig.direction == "short" and nq_es_spread.get("nq_favor_short", False):
        bd["nq_es_spread"] = 1
    elif nq_es_spread.get("signal") == "neutral":
        bd["nq_es_spread"] = 1
    else:
        bd["nq_es_spread"] = 0

    # 11. Session conviction: first 30-min magnitude predicts day type
    conviction = get_session_conviction(tsmom)
    if conviction["expected_range"] == "trending" and strategy in BREAKOUT_STRATS:
        bd["conviction"] = 1
    elif conviction["expected_range"] == "rotating" and strategy in MEAN_REV_STRATS:
        bd["conviction"] = 1
    else:
        bd["conviction"] = 1   # neutral → give point (no penalty)

    # 12. Open type: opening drive type matches strategy?
    open_type = market.get("open_type", {})
    hint = open_type.get("day_type_hint", "mixed")
    if hint == "trend" and strategy in BREAKOUT_STRATS:
        bd["open_type"] = 1
    elif hint == "trend" and strategy in MEAN_REV_STRATS:
        bd["open_type"] = 0
    elif hint == "range" and strategy in MEAN_REV_STRATS:
        bd["open_type"] = 1
    elif hint == "reversal" and strategy in MEAN_REV_STRATS:
        bd["open_type"] = 1
    elif hint == "mixed":
        bd["open_type"] = 1
    else:
        bd["open_type"] = 1

    # Memory bonus: apply per-strategy confidence adjustment from real trade history
    mem_adj = get_conf_adjustment(strategy)
    bd["memory"] = max(0, min(1, 1 + mem_adj))  # clamp to 0-1; default 1 neutral

    score = sum(bd.values())
    return score, bd


# ── Hard-block check ──────────────────────────────────────────────────────────

def _is_hard_blocked(
    strategy:     str,
    sig,
    today_df:     pd.DataFrame,
    local_bar_pos: int,
    market:       dict,
    macro:        dict,
) -> tuple[bool, str]:
    # BNS jump: fat-tail risk
    if bns_jump_flag(today_df, local_bar_pos):
        return True, "bns_jump"

    # OFI: strong opposing institutional flow
    ofi_z = get_ofi_zscore(today_df, local_bar_pos)
    if sig.direction == "long" and ofi_z < -OFI_HARD_BLOCK_Z:
        return True, "ofi_opposing"
    if sig.direction == "short" and ofi_z > OFI_HARD_BLOCK_Z:
        return True, "ofi_opposing"

    # CVD: strong bearish divergence → hard block on mean-rev longs
    try:
        cvd = get_cvd_divergence(today_df, local_bar_pos)
        if (strategy in MEAN_REV_STRATS and sig.direction == "long"
                and cvd["divergence"] == "bearish" and cvd["strength"] > 0.3):
            return True, "cvd_distribution"
    except Exception:
        pass

    # VVIX: vol-of-vol crisis
    vvix_regime = market.get("vvix_regime", {})
    if vvix_regime.get("skip_day", False):
        return True, "vvix_extreme"

    # VIX deep backwardation: skip everything
    vix_term = market.get("vix_term", {})
    if vix_term.get("structure") == "deep_backwardation":
        return True, "vix_backwardation"

    # Macro strong headwind + mean-rev long = dangerous
    if (macro.get("combined") == "strong_headwind"
            and sig.direction == "long"
            and strategy in MEAN_REV_STRATS):
        return True, "macro_headwind"

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

    print("[HYB] Loading VIX / VIX3M / VVIX / VXN ...")
    vix_cache  = _load_vix(period="90d")
    vix3m_cache = _load_extended_vix("^VIX3M", "90d")
    vvix_cache  = _load_extended_vix("^VVIX",  "90d")
    vxn_cache   = load_vxn(period="90d")
    print(f"[HYB] VIX: {len(vix_cache)}d | VIX3M: {len(vix3m_cache)}d | VVIX: {len(vvix_cache)}d")

    print("[HYB] Loading sector (XLK/SPY) and macro (DXY/TNX) data ...")
    xlk_closes, spy_closes = load_sector_data(period="90d")
    dxy_closes, tnx_closes = load_macro_data(period="90d")
    print(f"[HYB] XLK:{len(xlk_closes)}d  DXY:{len(dxy_closes)}d")

    est_idx   = df.index.tz_convert(EST)
    all_dates = sorted(set(est_idx.date))
    trades:   list[HybridTrade] = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    hard_block_counts: dict[str, int] = {}

    print(f"[HYB] Scanning {len(all_dates)} days ...")

    for today in all_dates:
        dow = today.weekday()
        if dow >= 5:
            continue

        vix   = _get_vix(vix_cache, today)
        vix3m = _get_ext_vix(vix3m_cache, today)
        vvix  = _get_ext_vix(vvix_cache, today)

        today_mask = est_idx.date == today
        today_df   = df[today_mask].copy()

        market = classify_market_full(df, today, vix, vix3m=vix3m, vvix=vvix, today_df=today_df)
        atr    = market["atr"]
        trend  = market["ema_trend"]

        # Skip day if vol regime blocks all trading
        if market["vvix_regime"]["skip_day"]:
            continue
        if market["vix_term"]["structure"] == "deep_backwardation":
            continue

        # Day-level institutional context
        hmm    = get_hmm_gate(df, today)
        gex    = compute_gex_proxy(vix_cache, vxn_cache, today)
        tsmom  = get_session_tsmom(today_df)
        sector = get_tech_sector_bias(today, xlk_closes, spy_closes)
        macro  = get_macro_bias(today, dxy_closes, tnx_closes)
        nq_es_spread = get_nq_es_spread_signal(df, es_df, today)

        # HAR vol forecast — key fix: now actually wired up
        har = har_forecast(df, today)
        if har["skip_day"]:
            continue
        stop_mult = har["stop_mult"]

        trades_today = 0
        daily_pnl    = 0.0
        used_strats: set[str] = set()

        def _can_trade() -> bool:
            return trades_today < MAX_TRADES_DAY and daily_pnl > -MAX_DAILY_LOSS

        def _local_pos(sig) -> int:
            try:
                signal_ts = df.index[sig.signal_bar_idx]
                diffs = [abs((ts - signal_ts).total_seconds()) for ts in today_df.index]
                return int(np.argmin(diffs))
            except Exception:
                return min(sig.signal_bar_idx, len(today_df) - 1)

        def _try_hybrid(strategy: str, sig, detail: str = "", max_hour: int = 12) -> bool:
            nonlocal trades_today, daily_pnl

            if sig is None or not _can_trade():
                return False

            risk_pts = abs(sig.entry - sig.stop)
            if risk_pts < 1.0:
                return False

            local_pos = _local_pos(sig)

            # Apply HAR stop multiplier to widen/narrow stops based on vol forecast
            if sig.direction == "long":
                adjusted_stop = sig.entry - (sig.entry - sig.stop) * stop_mult
            else:
                adjusted_stop = sig.entry + (sig.stop - sig.entry) * stop_mult

            # Hard blocks
            blocked, block_reason = _is_hard_blocked(
                strategy, sig, today_df, local_pos, market, macro
            )
            if blocked:
                hard_block_counts[block_reason] = hard_block_counts.get(block_reason, 0) + 1
                return False

            # 12-point confidence scoring
            score, breakdown = _score_trade(
                strategy, sig, today_df, local_pos,
                df, es_df, hmm, gex, tsmom, market, sector, macro, nq_es_spread,
            )

            # Skip very weak setups
            if score <= 3:
                return False

            n_contracts = 2 if score >= 10 else 1

            be_mult = 2.0 if strategy == "orb" else 1.0
            exit_p, pnl, outcome = _simulate_trade(
                df, sig.signal_bar_idx,
                sig.direction, sig.entry, adjusted_stop, sig.target,
                n_contracts=n_contracts, be_mult=be_mult, max_hour=max_hour,
            )
            reward_pts = abs(sig.target - sig.entry)
            rr = reward_pts / risk_pts if risk_pts > 0 else 0

            trades.append(HybridTrade(
                date=today, day_name=day_names[dow],
                strategy=strategy, direction=sig.direction,
                entry=sig.entry, stop=adjusted_stop, target=sig.target,
                exit_price=exit_p, pnl=pnl, outcome=outcome,
                risk_pts=risk_pts, reward_pts=reward_pts, rr=rr,
                vix=vix, regime=market["vix_regime"],
                trend_dir=trend["direction"],
                n_contracts=n_contracts,
                score=score,
                score_breakdown=breakdown,
                hmm_state=hmm["state"],
                gex_bias=gex["bias"],
                tsmom_bias=tsmom["bias"],
                signal_detail=detail,
                stop_mult=stop_mult,
            ))
            trades_today += 1
            daily_pnl    += pnl
            used_strats.add(strategy)
            return True

        vix_ok = vix < 25

        # ── Priority 1: Gap Fill ──────────────────────────────────────────────
        if _can_trade():
            gap = detect_gap(df, today, atr, dow=dow)
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

        # ── Priority 6: PM VWAP Reversion ─────────────────────────────────────
        if _can_trade() and market["vwap_ok"]:
            remaining = MAX_TRADES_DAY - trades_today
            for vs in detect_vwap(df, today, vix, atr, max_signals=remaining,
                                  start_min=13*60+30, end_min=15*60+30):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_hybrid("vwap_pm", vs,
                                f"PM dev={vs.deviation_pts:.1f}pts ({vs.deviation_std:.1f}s)",
                                max_hour=16)

        # ── Priority 7: AM VWAP Bounce ────────────────────────────────────────
        if _can_trade() and market["vwap_ok"]:
            remaining = MAX_TRADES_DAY - trades_today
            for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"],
                                         max_signals=remaining):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_hybrid("vwap_bounce", vs,
                                f"VWAP bounce {trend['direction']} dev={vs.deviation_pts:.1f}pts")

        # ── Priority 8: PM VWAP Bounce ────────────────────────────────────────
        if _can_trade() and market["vwap_ok"]:
            remaining = MAX_TRADES_DAY - trades_today
            for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"],
                                         max_signals=remaining,
                                         start_min=13*60+30, end_min=15*60+30):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_hybrid("vwap_bounce_pm", vs,
                                f"PM VWAP bounce {trend['direction']}",
                                max_hour=16)

    run_hybrid_backtest._hard_blocks = hard_block_counts
    return trades


run_hybrid_backtest._hard_blocks = {}
