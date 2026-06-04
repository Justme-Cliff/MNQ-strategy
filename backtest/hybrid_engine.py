"""
Hybrid Engine — Base Quant Strategies + Full 20-Point Institutional Scoring.

Philosophy:
  Base trade signals are kept intact.
  Institutional signals score each trade 0-20 and map to contract size.
  Hard blocks prevent the worst trades; soft scoring rewards the best ones.

Confidence score (0-20 points + memory bonus):
  +1  TSMOM aligned with signal direction (or exempt)
  +1  GEX bias favors this strategy type
  +1  ES lead-lag confirms direction
  +1  HMM 5-state regime (strong_bull/bull=1; neutral partial; stress/bear=0)
  +1  CVD divergence confirms (or no divergence)
  +1  Overnight range type matches strategy type
  +1  VIX term structure supports strategy type
  +1  XLK/SPY sector bias aligned
  +1  DXY+TNX macro not a strong headwind
  +1  NQ/ES spread not extended against signal
  +1  Session conviction matches strategy type
  +1  Open type hint matches strategy type
  +1  RVOL 1.5-2.5x (institutional participation confirmed)
  +1  Opening Candle Continuation matches signal direction
  +1  No opposing absorption at entry level
  +1  Kyle's lambda informed flow aligned
  +1  SMH semiconductor RS confirming signal direction
  +1  COT not at extreme against signal direction
  +1  Entry near confirmed AVWAP level (support/resistance)
  +1  Daily breadth not opposing signal
  +1  (memory bonus) strategy recently performing well

Contract sizing:
  score >= 19  ->  2 MNQ contracts  (strong institutional consensus)
  score 6-18   ->  1 MNQ contract   (standard size)
  score <= 5   ->  SKIP             (insufficient backing)
  Kelly check  ->  further caps 2-lot if recent WR below threshold

Two-target exit system:
  T1: 1x risk -> exit 50%, lock P&L
  T2: trail remaining 50% with 3x intraday ATR Chandelier OR original target

Hard blocks (any one blocks regardless of score):
  BNS jump detected
  OFI z-score opposing
  HAR extreme vol forecast (skip day)
  VVIX > 130
  VIX deep backwardation
  Macro strong headwind + mean-rev long
  RVOL thin (< 0.8x)
  CVD buying/selling climax opposing signal
  Strong absorption opposing signal
  VPIN > 0.65 on mean-reversion strategies
  Gap too large (> 1.2x ATR) for gap_fill
  Monday medium/large gap (> 0.7x ATR)
  10:00-10:15 AM economic data release window (no entries)
  11:00-11:15 AM London close window (no mean-rev entries)
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
from strategy.inst_ofi     import get_ofi_zscore, get_cvd_divergence, get_cvd_climax
from strategy.inst_hmm     import get_hmm_gate
from strategy.inst_gex     import compute_gex_proxy, load_vxn
from strategy.inst_tsmom   import get_session_tsmom, get_session_conviction, get_occ_signal, TSMOM_EXEMPT
from strategy.inst_leadlag import check_es_confirmation, get_nq_es_spread_signal
from strategy.inst_sectors import get_tech_sector_bias, load_sector_data
from strategy.inst_macro   import get_macro_bias, load_macro_data
from strategy.inst_rvol       import compute_rvol
from strategy.inst_absorption import detect_absorption
from strategy.inst_lambda     import get_lambda_signal
from strategy.inst_va_rule    import detect_va_rule_signal, VASignal
from strategy.inst_vpin       import get_vpin_gate
from strategy.inst_cot        import get_cot_bias, load_cot_data
from strategy.inst_avwap      import get_avwap_levels
from strategy.inst_breadth    import get_breadth_bias, load_breadth_data
from strategy.inst_sectors    import get_smh_lead_signal, load_smh_data
from strategy.inst_kelly      import kelly_contracts
from strategy.bot_memory      import get_conf_adjustment

EST = ZoneInfo("America/New_York")

MNQ_PER_POINT  = 2.0
MAX_RISK_PTS   = 25.0
MAX_TRADES_DAY = 3
MAX_DAILY_LOSS = 150.0

MEAN_REV_STRATS = {"vwap_rev", "vwap_pm", "fvg", "ib_breakout", "va_rule"}
BREAKOUT_STRATS = {"orb", "gap_fill"}

OFI_HARD_BLOCK_Z        = 2.0
CHANDELIER_MULT         = 3.0
ABSORPTION_BLOCK_THRESH = 0.4
GAP_LARGE_ATR_MULT      = 1.2   # gap > 1.2x ATR = skip gap_fill always
GAP_MONDAY_ATR_MULT     = 0.7   # Monday gap > 0.7x ATR = skip


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


# ── VIX helpers ───────────────────────────────────────────────────────────────

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


# ── Intraday ATR helper ───────────────────────────────────────────────────────

def _bar_atr(df: pd.DataFrame, bar_idx: int, window: int = 14) -> float:
    """14-bar True Range average from 5-min bars — used for Chandelier trail."""
    start = max(0, bar_idx - window)
    w = df.iloc[start: bar_idx + 1]
    if len(w) < 2:
        return 5.0
    h = w["High"].values.astype(float)
    l = w["Low"].values.astype(float)
    c = w["Close"].values.astype(float)
    prev_c = np.empty_like(c)
    prev_c[0] = float(df.iloc[max(0, start - 1)]["Close"]) if start > 0 else c[0]
    prev_c[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    return max(1.0, float(np.mean(tr[-min(window, len(tr)):])))


# ── Two-Target Exit System ────────────────────────────────────────────────────

def _simulate_trade(
    df: pd.DataFrame,
    signal_bar_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    n_contracts: int = 1,
    max_hour: int = 12,
) -> tuple[float, float, str]:
    """
    Two-target exit system (ORDER_FLOW_UPGRADE_PLAN Module A).

    T1: 1x risk distance from entry -> exit 50% of position, lock that P&L.
    T2: trail remaining 50% with 3x intraday ATR Chandelier stop, or hit
        original target first.

    Original stop holds until T1 is hit.
    After T1: stop is at minimum entry; Chandelier trails higher (long) / lower (short).

    This fixes the 44% breakeven trade problem: 26/59 trades were $0 wins
    despite averaging 15.7x favorable excursion. Now T1 locks in 1R on 50%.
    """
    per_pt_half = MNQ_PER_POINT * n_contracts * 0.5  # 50% of position value

    risk_pts = abs(entry - stop)
    if risk_pts < 1.0:
        return entry, 0.0, "WIN"

    t1_target = (entry + risk_pts) if direction == "long" else (entry - risk_pts)

    # Compute intraday ATR for Chandelier trail (from bars around signal)
    intraday_atr = _bar_atr(df, signal_bar_idx)

    t1_hit     = False
    t1_pnl     = 0.0
    curr_stop  = stop
    trail_anch = entry  # tracks highest high (long) or lowest low (short) since T1

    for i in range(signal_bar_idx, min(signal_bar_idx + 300, len(df))):
        row   = df.iloc[i]
        high  = float(row["High"])
        low   = float(row["Low"])
        close = float(row["Close"])

        ts_est = df.index[i].astimezone(EST)
        if ts_est.hour >= max_hour:
            # Session end: exit remaining position at close
            if t1_hit:
                remain_pts = (close - entry) if direction == "long" else (entry - close)
                total = t1_pnl + remain_pts * per_pt_half
                return close, total, "WIN" if total > 0 else "LOSS"
            pts = (close - entry) if direction == "long" else (entry - close)
            pnl = pts * per_pt_half * 2
            return close, pnl, "WIN" if pnl > 0 else "LOSS"

        if not t1_hit:
            # Phase 1: original stop holds, watch for T1 hit
            if direction == "long":
                hit_orig = high >= target
                hit_t1   = high >= t1_target
                hit_stop = low  <= curr_stop

                if hit_orig and not hit_stop:
                    # Full target hit before stop — both T1 and T2 profit
                    full_reward = (target - entry) * per_pt_half * 2
                    return target, full_reward, "WIN"
                if hit_t1:
                    t1_pnl    = risk_pts * per_pt_half
                    t1_hit    = True
                    trail_anch = max(high, t1_target)
                    curr_stop  = max(entry, trail_anch - CHANDELIER_MULT * intraday_atr)
                    if hit_orig:
                        remain = (target - entry) * per_pt_half
                        return target, t1_pnl + remain, "WIN"
                elif hit_stop:
                    pts = curr_stop - entry
                    pnl = pts * per_pt_half * 2
                    return curr_stop, pnl, "LOSS" if pnl < 0 else "WIN"
            else:  # short
                hit_orig = low  <= target
                hit_t1   = low  <= t1_target
                hit_stop = high >= curr_stop

                if hit_orig and not hit_stop:
                    full_reward = (entry - target) * per_pt_half * 2
                    return target, full_reward, "WIN"
                if hit_t1:
                    t1_pnl    = risk_pts * per_pt_half
                    t1_hit    = True
                    trail_anch = min(low, t1_target)
                    curr_stop  = min(entry, trail_anch + CHANDELIER_MULT * intraday_atr)
                    if hit_orig:
                        remain = (entry - target) * per_pt_half
                        return target, t1_pnl + remain, "WIN"
                elif hit_stop:
                    pts = entry - curr_stop
                    pnl = pts * per_pt_half * 2
                    return curr_stop, pnl, "LOSS" if pnl < 0 else "WIN"

        else:
            # Phase 2: T1 hit, trail remaining 50% with Chandelier
            if direction == "long":
                trail_anch = max(trail_anch, high)
                new_trail  = trail_anch - CHANDELIER_MULT * intraday_atr
                curr_stop  = max(curr_stop, new_trail)
                curr_stop  = max(curr_stop, entry)   # never below entry after T1

                hit_tgt  = high >= target
                hit_stop_trail = low <= curr_stop

                if hit_tgt:
                    remain = (target - entry) * per_pt_half
                    return target, t1_pnl + remain, "WIN"
                elif hit_stop_trail:
                    remain = (curr_stop - entry) * per_pt_half
                    total  = t1_pnl + remain
                    return curr_stop, total, "WIN" if total > 0 else "LOSS"
            else:  # short
                trail_anch = min(trail_anch, low)
                new_trail  = trail_anch + CHANDELIER_MULT * intraday_atr
                curr_stop  = min(curr_stop, new_trail)
                curr_stop  = min(curr_stop, entry)   # never above entry after T1

                hit_tgt  = low <= target
                hit_stop_trail = high >= curr_stop

                if hit_tgt:
                    remain = (entry - target) * per_pt_half
                    return target, t1_pnl + remain, "WIN"
                elif hit_stop_trail:
                    remain = (entry - curr_stop) * per_pt_half
                    total  = t1_pnl + remain
                    return curr_stop, total, "WIN" if total > 0 else "LOSS"

    # End of data
    last = float(df["Close"].iloc[-1])
    if t1_hit:
        remain_pts = (last - entry) if direction == "long" else (entry - last)
        total = t1_pnl + remain_pts * per_pt_half
        return last, total, "WIN" if total > 0 else "LOSS"
    pts = (last - entry) if direction == "long" else (entry - last)
    pnl = pts * per_pt_half * 2
    return last, pnl, "LOSS" if pnl < 0 else "WIN"


# ── Confidence scorer (0–16 points) ──────────────────────────────────────────

def _score_trade(
    strategy:     str,
    sig,
    today_df:     pd.DataFrame,
    local_bar_pos: int,
    df:           pd.DataFrame,
    es_df:        pd.DataFrame,
    hmm:          dict,
    gex:          dict,
    tsmom:        dict,
    market:       dict,
    sector:       dict,
    macro:        dict,
    nq_es_spread: dict,
    occ:          dict,
    # New context passed pre-loaded — zero network calls here
    cot:          dict = None,
    breadth:      dict = None,
    smh_signal:   dict = None,
    smh_vxn:      float = 20.0,
) -> tuple[int, dict]:
    """Score a trade 0-20 using all institutional signals."""
    if cot is None:
        cot = {}
    if breadth is None:
        breadth = {}
    if smh_signal is None:
        smh_signal = {}

    bd: dict[str, int] = {}
    atr = market.get("atr", 0.0)

    # 1. TSMOM
    if strategy in TSMOM_EXEMPT:
        bd["tsmom"] = 1
    elif not tsmom.get("available", False):
        bd["tsmom"] = 1
    elif tsmom["bias"] == sig.direction or tsmom["bias"] == "neutral":
        bd["tsmom"] = 1
    else:
        bd["tsmom"] = 0

    # 2. GEX
    bias = gex.get("bias", "neutral")
    if bias == "neutral":
        bd["gex"] = 1
    elif bias == "mean_rev" and strategy in MEAN_REV_STRATS:
        bd["gex"] = 1
    elif bias == "breakout" and strategy in BREAKOUT_STRATS:
        bd["gex"] = 1
    else:
        bd["gex"] = 0

    # 3. ES lead-lag
    try:
        bd["es"] = 1 if check_es_confirmation(es_df, df, sig.signal_bar_idx, sig.direction) else 0
    except Exception:
        bd["es"] = 1

    # 4. HMM 5-state regime
    state = hmm.get("state", "unavailable")
    if state in ("unavailable", "strong_bull", "bull"):
        bd["hmm"] = 1
    elif state == "neutral":
        bd["hmm"] = 1 if strategy in MEAN_REV_STRATS else 0
    elif state == "stress":
        bd["hmm"] = 1 if strategy in BREAKOUT_STRATS else 0
    elif state == "bear":
        bd["hmm"] = 1 if (sig.direction == "short" and strategy in BREAKOUT_STRATS) else 0
    else:
        bd["hmm"] = 1

    # 5. CVD divergence
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

    # 6. Overnight range
    ov = market.get("overnight", {})
    if ov.get("day_type_bias") == "expansion" and strategy in BREAKOUT_STRATS:
        bd["overnight"] = 1
    elif ov.get("day_type_bias") == "rotation" and strategy in MEAN_REV_STRATS:
        bd["overnight"] = 1
    elif ov.get("day_type_bias") in ("neutral", None) or not ov:
        bd["overnight"] = 1
    else:
        bd["overnight"] = 0

    # 7. VIX term structure
    vix_term = market.get("vix_term", {})
    structure = vix_term.get("structure", "contango")
    if structure in ("deep_contango", "contango", "flat"):
        bd["vix_term"] = 1
    elif structure in ("backwardation", "deep_backwardation") and strategy in BREAKOUT_STRATS:
        bd["vix_term"] = 1
    else:
        bd["vix_term"] = 0 if strategy in MEAN_REV_STRATS else 1

    # 8. XLK sector bias
    if not sector.get("available", False) or sector.get("bias") == "neutral":
        bd["sector"] = 1
    elif sig.direction == "long" and sector.get("long_favored", False):
        bd["sector"] = 1
    elif sig.direction == "short" and sector.get("short_favored", False):
        bd["sector"] = 1
    else:
        bd["sector"] = 0

    # 9. Macro DXY+TNX
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

    # 10. NQ/ES spread
    if not nq_es_spread.get("available", False) or nq_es_spread.get("signal") == "neutral":
        bd["nq_es_spread"] = 1
    elif sig.direction == "long" and nq_es_spread.get("nq_favor_long", False):
        bd["nq_es_spread"] = 1
    elif sig.direction == "short" and nq_es_spread.get("nq_favor_short", False):
        bd["nq_es_spread"] = 1
    else:
        bd["nq_es_spread"] = 0

    # 11. Session conviction
    conviction = get_session_conviction(tsmom)
    if conviction["expected_range"] == "trending" and strategy in BREAKOUT_STRATS:
        bd["conviction"] = 1
    elif conviction["expected_range"] == "rotating" and strategy in MEAN_REV_STRATS:
        bd["conviction"] = 1
    else:
        bd["conviction"] = 1  # neutral -> no penalty

    # 12. Open type
    hint = market.get("open_type", {}).get("day_type_hint", "mixed")
    if hint == "trend" and strategy in BREAKOUT_STRATS:
        bd["open_type"] = 1
    elif hint == "trend" and strategy in MEAN_REV_STRATS:
        bd["open_type"] = 0
    elif hint in ("range", "reversal") and strategy in MEAN_REV_STRATS:
        bd["open_type"] = 1
    else:
        bd["open_type"] = 1  # mixed -> no penalty

    # 13. RVOL — institutional participation
    try:
        today = today_df.index[0].astimezone(EST).date()
        rvol_data = compute_rvol(df, today, local_bar_pos)
        regime = rvol_data.get("regime", "normal")
        if regime in ("high", "normal"):
            bd["rvol"] = 1
        elif regime == "climax" and strategy in BREAKOUT_STRATS:
            bd["rvol"] = 0  # potential exhaustion on breakout = caution
        elif regime == "thin":
            bd["rvol"] = 0
        else:
            bd["rvol"] = 1
    except Exception:
        bd["rvol"] = 1

    # 14. OCC — opening candle continuation
    occ_dir = occ.get("direction", "neutral")
    if occ_dir == sig.direction:
        bd["occ"] = 1
    elif occ_dir == "neutral" or not occ.get("available", False):
        bd["occ"] = 1
    else:
        bd["occ"] = 0

    # 15. Absorption — no opposing at entry level
    try:
        abs_data = detect_absorption(today_df, local_bar_pos, atr)
        if not abs_data["absorbed"]:
            bd["absorption"] = 1
        elif abs_data["direction"] == "sell_side" and sig.direction == "short":
            bd["absorption"] = 1  # aligned: selling absorption at resistance = good for short
        elif abs_data["direction"] == "buy_side" and sig.direction == "long":
            bd["absorption"] = 1  # aligned: buying absorption at support = good for long
        else:
            bd["absorption"] = 0  # opposing absorption = friction
    except Exception:
        bd["absorption"] = 1

    # 16. Kyle's lambda — informed flow intensity
    try:
        lam = get_lambda_signal(today_df, local_bar_pos, sig.direction)
        bd["lambda"] = 1 if lam.get("aligned", True) else 0
    except Exception:
        bd["lambda"] = 1

    # 17. SMH semiconductor lead signal
    if not smh_signal.get("available", False):
        bd["smh"] = 1   # unavailable = no penalty
    elif smh_signal.get("long_boost", False) and sig.direction == "long":
        bd["smh"] = 1
    elif smh_signal.get("short_boost", False) and sig.direction == "short":
        bd["smh"] = 1
    elif smh_signal.get("signal") == "neutral":
        bd["smh"] = 1
    else:
        bd["smh"] = 0   # semis diverging from signal direction

    # 18. COT regime — not at extreme against signal direction
    if not cot.get("available", False):
        bd["cot"] = 1
    elif sig.direction == "long" and not cot.get("long_ok", True):
        bd["cot"] = 0   # COT says crowd is max long = fade risk
    elif sig.direction == "short" and cot.get("short_boost", False):
        bd["cot"] = 1   # COT supports short
    else:
        bd["cot"] = 1

    # 19. AVWAP proximity — entry near confirmed institutional cost basis
    try:
        today  = today_df.index[0].astimezone(EST).date()
        avwap  = get_avwap_levels(df, today, float(sig.entry), atr)
        if avwap["near_avwap"]:
            if avwap["avwap_support"] and sig.direction == "long":
                bd["avwap"] = 1   # entering from AVWAP support = ideal
            elif avwap["avwap_resist"] and sig.direction == "short":
                bd["avwap"] = 1   # entering from AVWAP resistance = ideal
            else:
                bd["avwap"] = 1   # near AVWAP but not directional = neutral
        else:
            bd["avwap"] = 1       # not near any AVWAP = no signal, no penalty
        if avwap.get("confluence", False):
            bd["avwap"] = 1       # confluence zone = always give point
    except Exception:
        bd["avwap"] = 1

    # 20. Daily breadth — $ADDN or QQQ/IWM RS not opposing signal
    if not breadth.get("available", False):
        bd["breadth"] = 1
    elif breadth.get("breadth_bias") == "bullish" and sig.direction == "long":
        bd["breadth"] = 1
    elif breadth.get("breadth_bias") == "bearish" and sig.direction == "short":
        bd["breadth"] = 1
    elif breadth.get("breadth_bias") == "neutral":
        bd["breadth"] = 1
    elif breadth.get("breadth_bias") == "bearish" and sig.direction == "long":
        bd["breadth"] = 0   # broad market selling + long signal = headwind
    else:
        bd["breadth"] = 1

    # Memory bonus
    mem_adj = get_conf_adjustment(strategy)
    bd["memory"] = max(0, min(1, 1 + mem_adj))

    score = sum(bd.values())
    return score, bd


# ── Hard-block check ──────────────────────────────────────────────────────────

def _time_window_ok(signal_bar_idx: int, df: pd.DataFrame, strategy: str) -> tuple[bool, str]:
    """Block entries during economic data release and London close windows."""
    try:
        ts_est = df.index[signal_bar_idx].astimezone(EST)
        mins   = ts_est.hour * 60 + ts_est.minute

        # 10:00-10:04 AM: first bar at 10 AM often has release spike — skip that bar only
        if mins == 600:
            return False, "data_release_window"

        # 11:00-11:04 AM: London close turbulence — skip first bar for mean-rev only
        if strategy in MEAN_REV_STRATS and mins == 660:
            return False, "london_close_window"

    except Exception:
        pass
    return True, ""


def _is_hard_blocked(
    strategy:      str,
    sig,
    today_df:      pd.DataFrame,
    local_bar_pos: int,
    df:            pd.DataFrame,
    today:         date,
    market:        dict,
    macro:         dict,
) -> tuple[bool, str]:
    atr = market.get("atr", 0.0)

    # BNS jump
    if bns_jump_flag(today_df, local_bar_pos):
        return True, "bns_jump"

    # OFI opposing
    ofi_z = get_ofi_zscore(today_df, local_bar_pos)
    if sig.direction == "long" and ofi_z < -OFI_HARD_BLOCK_Z:
        return True, "ofi_opposing"
    if sig.direction == "short" and ofi_z > OFI_HARD_BLOCK_Z:
        return True, "ofi_opposing"

    # CVD distribution on mean-rev longs
    try:
        cvd = get_cvd_divergence(today_df, local_bar_pos)
        if (strategy in MEAN_REV_STRATS and sig.direction == "long"
                and cvd["divergence"] == "bearish" and cvd["strength"] > 0.3):
            return True, "cvd_distribution"
    except Exception:
        pass

    # VVIX crisis
    if market.get("vvix_regime", {}).get("skip_day", False):
        return True, "vvix_extreme"

    # VIX deep backwardation
    if market.get("vix_term", {}).get("structure") == "deep_backwardation":
        return True, "vix_backwardation"

    # Macro strong headwind + mean-rev long
    if (macro.get("combined") == "strong_headwind"
            and sig.direction == "long"
            and strategy in MEAN_REV_STRATS):
        return True, "macro_headwind"

    # RVOL thin — no institutional participation
    try:
        rvol_data = compute_rvol(df, today, local_bar_pos)
        if rvol_data.get("regime") == "thin":
            return True, "rvol_thin"
    except Exception:
        pass

    # CVD climax opposing signal
    try:
        climax = get_cvd_climax(today_df, local_bar_pos, atr)
        rev_dir = climax.get("reversal_dir", "none")
        if rev_dir == "short" and sig.direction == "long":
            return True, "cvd_buying_climax"
        if rev_dir == "long" and sig.direction == "short":
            return True, "cvd_selling_climax"
    except Exception:
        pass

    # Strong absorption opposing signal direction
    try:
        abs_data = detect_absorption(today_df, local_bar_pos, atr)
        if abs_data["absorbed"] and abs_data["strength"] > ABSORPTION_BLOCK_THRESH:
            if abs_data["direction"] == "sell_side" and sig.direction == "long":
                return True, "absorption_resistance"
            if abs_data["direction"] == "buy_side" and sig.direction == "short":
                return True, "absorption_support"
    except Exception:
        pass

    # VPIN > 0.65 on mean-reversion strategies: high informed flow kills mean-rev
    try:
        if strategy in MEAN_REV_STRATS:
            vpin_g = get_vpin_gate(today_df, local_bar_pos, strategy)
            if vpin_g.get("gate_active", False):
                return True, "vpin_high"
    except Exception:
        pass

    # Gap too large: gap_fill on gaps > 1.2x ATR have only 8.2% fill rate
    try:
        if strategy == "gap_fill" and hasattr(sig, "gap_ratio"):
            if sig.gap_ratio > GAP_LARGE_ATR_MULT:
                return True, "gap_too_large"
            if today.weekday() == 0 and sig.gap_ratio > GAP_MONDAY_ATR_MULT:
                return True, "monday_large_gap"
    except Exception:
        pass

    return False, ""


# ── Main hybrid backtest ──────────────────────────────────────────────────────

def run_hybrid_backtest(
    interval: str = "5m",
    period:   str = "60d",
    df:       pd.DataFrame | None = None,   # pass pre-loaded data (e.g. from Databento)
) -> list[HybridTrade]:
    if df is not None:
        df = label_sessions(df, interval=interval)
        print(f"[HYB] Using pre-loaded data: {len(df)} bars | "
              f"{df.index[0].date()} -> {df.index[-1].date()}")
    else:
        print(f"[HYB] Loading NQ data ({period}/{interval}) ...")
        df = load_nq(interval=interval, period=period)
        df = label_sessions(df, interval=interval)
        print(f"[HYB] {len(df)} bars | {df.index[0].date()} -> {df.index[-1].date()}")

    print("[HYB] Loading ES data ...")
    es_df = load_es(interval=interval, period=period)
    print(f"[HYB] ES: {len(es_df)} bars" if not es_df.empty else "[HYB] ES unavailable")

    print("[HYB] Loading VIX / VIX3M / VVIX / VXN ...")
    vix_cache   = _load_vix(period="90d")
    vix3m_cache = _load_extended_vix("^VIX3M", "90d")
    vvix_cache  = _load_extended_vix("^VVIX",  "90d")
    vxn_cache   = load_vxn(period="90d")
    print(f"[HYB] VIX: {len(vix_cache)}d | VIX3M: {len(vix3m_cache)}d | VVIX: {len(vvix_cache)}d")

    print("[HYB] Loading sector (XLK/SPY/SMH) and macro (DXY/TNX) data ...")
    xlk_closes, spy_closes = load_sector_data(period="90d")
    dxy_closes, tnx_closes = load_macro_data(period="90d")
    smh_closes             = load_smh_data(period="90d")
    print(f"[HYB] XLK:{len(xlk_closes)}d  DXY:{len(dxy_closes)}d  SMH:{len(smh_closes)}d")

    print("[HYB] Loading COT + breadth data ...")
    cot_df               = load_cot_data()
    qqq_closes, iwm_closes, addn_series = load_breadth_data(period="60d")
    cot_available = cot_df is not None and not cot_df.empty
    print(f"[HYB] COT: {'OK' if cot_available else 'UNAVAILABLE'}  "
          f"QQQ:{len(qqq_closes)}d  ADDN:{len(addn_series) if addn_series is not None else 0}d")

    est_idx   = df.index.tz_convert(EST)
    all_dates = sorted(set(est_idx.date))
    trades:   list[HybridTrade] = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    hard_block_counts: dict[str, int] = {}

    print(f"[HYB] Scanning {len(all_dates)} days ...")

    from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, SpinnerColumn
    _progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("[green]{task.fields[trades]} trades"),
        TextColumn("•"),
        TimeRemainingColumn(),
    )
    _task = _progress.add_task("Scanning...", total=len(all_dates), trades=0)
    _progress.start()

    for today in all_dates:
        _progress.update(_task, advance=1, trades=len(trades),
                         description=f"{today}")
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

        if market["vvix_regime"]["skip_day"]:
            continue
        if market["vix_term"]["structure"] == "deep_backwardation":
            continue

        hmm    = get_hmm_gate(df, today)
        gex    = compute_gex_proxy(vix_cache, vxn_cache, today)
        tsmom  = get_session_tsmom(today_df)
        sector = get_tech_sector_bias(today, xlk_closes, spy_closes)
        macro  = get_macro_bias(today, dxy_closes, tnx_closes)
        nq_es_spread = get_nq_es_spread_signal(df, es_df, today)

        # Per-day pre-computed context (all cached — zero network calls during signal eval)
        occ    = get_occ_signal(today_df)
        cot    = get_cot_bias(today, _df=cot_df)
        breadth = get_breadth_bias(today, qqq_closes, iwm_closes, addn_series)
        smh_sig = get_smh_lead_signal(today, smh_closes, spy_closes, vxn=(vix or 20.0))

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

            # HAR stop multiplier — va_rule is mean-reversion; the VA edge IS the stop,
            # so never widen it further (widening a wide VA stop creates asymmetric losses)
            effective_mult = 1.0 if strategy == "va_rule" else stop_mult
            if sig.direction == "long":
                adjusted_stop = sig.entry - (sig.entry - sig.stop) * effective_mult
            else:
                adjusted_stop = sig.entry + (sig.stop - sig.entry) * effective_mult

            # Hard blocks
            blocked, block_reason = _is_hard_blocked(
                strategy, sig, today_df, local_pos, df, today, market, macro
            )
            if blocked:
                hard_block_counts[block_reason] = hard_block_counts.get(block_reason, 0) + 1
                return False

            # Time window hard block (data releases + London close)
            time_ok, time_reason = _time_window_ok(sig.signal_bar_idx, df, strategy)
            if not time_ok:
                hard_block_counts[time_reason] = hard_block_counts.get(time_reason, 0) + 1
                return False

            # 20-point confidence scoring
            score, breakdown = _score_trade(
                strategy, sig, today_df, local_pos,
                df, es_df, hmm, gex, tsmom, market, sector, macro, nq_es_spread, occ,
                cot=cot, breadth=breadth, smh_signal=smh_sig, smh_vxn=(vix or 20.0),
            )

            # Skip weak setups (threshold scaled with new 20-point max)
            if score <= 5:
                return False
            # FVG needs stronger confirmation — the fill mechanism is fragile
            if strategy == "fvg" and score < 17:
                return False
            # va_rule has a variable-width stop (the VA edge) — require more
            # institutional backing than other strategies before taking the risk
            if strategy == "va_rule" and score < 18:
                return False

            # Score-based contract size (2-lot at score >= 19 out of 21 max)
            n_contracts = 2 if score >= 19 else 1
            # va_rule uses a variable-width stop (the VA edge); never double size
            if strategy == "va_rule":
                n_contracts = 1

            # Kelly guard: only reduce size if we have 40+ trades and recent
            # performance is genuinely poor (protects against drawdown streaks).
            # Rarely activates in 60d backtest; mainly useful in live monitor.
            if len(trades) >= 40:
                kelly_size = kelly_contracts(trades)
                n_contracts = min(n_contracts, kelly_size)

            # Strategy-specific target extensions for T2
            effective_target = sig.target
            if strategy == "orb" and hasattr(sig, "orb_range") and sig.orb_range > 0:
                ext = sig.entry + sig.orb_range * 3.0 if sig.direction == "long" \
                      else sig.entry - sig.orb_range * 3.0
                effective_target = max(sig.target, ext) if sig.direction == "long" \
                                   else min(sig.target, ext)
            elif strategy == "ib_breakout" and hasattr(sig, "ib_range") and sig.ib_range > 0:
                ext = sig.entry + sig.ib_range * 2.5 if sig.direction == "long" \
                      else sig.entry - sig.ib_range * 2.5
                effective_target = max(sig.target, ext) if sig.direction == "long" \
                                   else min(sig.target, ext)

            exit_p, pnl, outcome = _simulate_trade(
                df, sig.signal_bar_idx,
                sig.direction, sig.entry, adjusted_stop, effective_target,
                n_contracts=n_contracts, max_hour=max_hour,
            )
            reward_pts = abs(effective_target - sig.entry)
            rr = reward_pts / risk_pts if risk_pts > 0 else 0

            trades.append(HybridTrade(
                date=today, day_name=day_names[dow],
                strategy=strategy, direction=sig.direction,
                entry=sig.entry, stop=adjusted_stop, target=effective_target,
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

        # ── Priority 2: FVG — REMOVED ─────────────────────────────────────────
        # 10-yr data: 52.6% WR, +$51 on 97 trades (breakeven).
        # 2-yr data: 40% WR, -$78 on 10 trades (losing).
        # OHLCV-only FVG detection lacks the order-flow confirmation needed
        # to reliably identify which gaps institutions will return to fill.

        # ── Priority 3: ORB ───────────────────────────────────────────────────
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

        # ── Priority 5: AM VWAP Reversion ────────────────────────────────────
        # Require directional HMM — VWAP reversion only has edge when there is
        # an established regime to revert to (not sideways / neutral HMM).
        _rev_hmm = hmm.get("state", "unavailable")
        if _can_trade() and market["vwap_ok"]:
            for vs in detect_vwap(df, today, vix, atr, max_signals=MAX_TRADES_DAY - trades_today):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    # Require confirmed directional regime — no bypass for unavailable.
                    # Without regime data we can't know if there's a trend to revert to.
                    _rev_ok = (
                        (vs.direction == "long"  and _rev_hmm in ("bull", "strong_bull")) or
                        (vs.direction == "short" and _rev_hmm in ("bear", "stress"))
                    )
                    if _rev_ok:
                        _try_hybrid("vwap_rev", vs,
                                    f"dev={vs.deviation_pts:.1f}pts ({vs.deviation_std:.1f}s)")

        # ── Priority 6: PM VWAP Reversion — REMOVED ──────────────────────────
        # 10-year data: 48.7% WR, -$105 P&L over 113 trades.
        # PM session has lower institutional volume; VWAP loses its anchor.

        # ── Priority 7: AM VWAP Bounce ────────────────────────────────────────
        if _can_trade() and market["vwap_ok"]:
            for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"],
                                         max_signals=MAX_TRADES_DAY - trades_today):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_hybrid("vwap_bounce", vs,
                                f"VWAP bounce {trend['direction']} dev={vs.deviation_pts:.1f}pts")

        # ── Priority 8: PM VWAP Bounce ────────────────────────────────────────
        if _can_trade() and market["vwap_ok"]:
            for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"],
                                         max_signals=MAX_TRADES_DAY - trades_today,
                                         start_min=13*60+30, end_min=15*60+30):
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try_hybrid("vwap_bounce_pm", vs,
                                f"PM VWAP bounce {trend['direction']}",
                                max_hour=16)

        # ── Priority 9: 80% Value Area Rule ───────────────────────────────────
        if _can_trade() and vix_ok:
            va_sig = detect_va_rule_signal(df, today, atr)
            if va_sig and direction_allowed(va_sig.direction, trend, strict=False):
                _try_hybrid("va_rule", va_sig,
                            f"VA rule type={va_sig.setup_type} "
                            f"vah-val={abs(va_sig.va_target_edge - va_sig.va_entry_edge):.0f}pts")

    _progress.stop()
    run_hybrid_backtest._hard_blocks = hard_block_counts
    return trades


run_hybrid_backtest._hard_blocks = {}
