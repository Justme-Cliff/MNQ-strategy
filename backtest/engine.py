"""
Backtest engine — replays 5-minute MNQ bars through the full strategy pipeline.

Assumptions:
  - Limit orders fill at the entry price (no slippage)
  - Stop loss fills at stop price (no slippage on gaps)
  - TP1 at 1.5:1 → move stop to break-even, exit half
  - TP2 at 3:1   → exit remaining half
  - P&L uses MNQ = $2/point * contracts
  - Max 2 trades per day, max $50 risk per trade
  - Trade window: 9:30–11:30 AM EST only
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import yfinance as yf

from backtest.data_loader import load_nq, label_sessions
from strategy.asia_range import build_asia_ranges
from strategy.fvg_detector import find_fvgs, get_active_fvg
from strategy.mss_detector import detect_mss
from strategy.vwap import compute_vwap
from strategy.confluence_scorer import score_setup
from strategy.london_session import get_london_action, is_london_aligned
from strategy.order_block import find_order_block
from strategy.smart_filter import SmartFilter
from strategy.market_context import (
    get_weekly_levels,
    check_smt_divergence,
    check_news_calendar,
    compute_ote_zone,
    price_in_ote,
)
from risk.position_sizer import calculate_size, calculate_targets
from config import (
    MIN_CONFLUENCE_SCORE,
    MAX_TRADES_PER_DAY,
    MAX_DAILY_LOSS,
    MAX_STOP_POINTS,
    MNQ_DOLLARS_PER_POINT,
    STARTING_BALANCE,
    TRAILING_MAX_DRAWDOWN,
    TRADE_END_HOUR,
    TRADE_END_MIN,
    SWEEP_TIMEOUT_MINUTES,
)

EST = ZoneInfo("America/New_York")


@dataclass
class BacktestTrade:
    date: date
    direction: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    exit_price: float
    contracts: int
    pnl: float
    score: int
    outcome: str          # "WIN_TP2", "WIN_TP1_BE", "LOSS", "TIMEOUT"
    reason: str           # confluence breakdown
    signal_hour: int = 9
    day_of_week: int = 0  # 0=Mon, 4=Fri
    sweep_depth: float = 0.0
    asia_range_width: float = 0.0
    # New context fields
    vix_regime: str = "unknown"
    smt_confirmed: bool = True
    ote_used: bool = False
    news_penalty: int = 0
    setup_mode: str = "normal"   # normal | judas_reversal | post_claims


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    daily_pnl: dict = field(default_factory=dict)


def _build_prev_day_levels(df: pd.DataFrame) -> dict:
    """Compute previous trading day H/L keyed by the NEXT trading date."""
    est_idx = df.index.tz_convert(EST)
    daily: dict = {}
    for i, ts in enumerate(est_idx):
        d = ts.date()
        h = float(df["High"].iloc[i])
        l = float(df["Low"].iloc[i])
        mins = ts.hour * 60 + ts.minute
        if 9 * 60 + 30 <= mins < 16 * 60:
            if d not in daily:
                daily[d] = {"high": h, "low": l}
            else:
                daily[d]["high"] = max(daily[d]["high"], h)
                daily[d]["low"]  = min(daily[d]["low"],  l)
    dates = sorted(daily.keys())
    return {dates[i]: daily[dates[i - 1]] for i in range(1, len(dates))}


def _build_vix_cache(period: str = "60d") -> dict:
    """Download VIX daily history and return a date-keyed regime dict."""
    try:
        df = yf.Ticker("^VIX").history(period=period, interval="1d", auto_adjust=True)
        if df.empty:
            return {}
        cache = {}
        for ts, row in df.iterrows():
            vix = float(row["Close"])
            if vix < 15:
                regime, penalty = "low", 0
            elif vix < 20:
                regime, penalty = "medium", 0
            elif vix < 25:
                regime, penalty = "high", 1
            elif vix < 30:
                regime, penalty = "very_high", 2
            else:
                regime, penalty = "extreme", 3
            d = ts.date() if hasattr(ts, "date") else ts.to_pydatetime().date()
            cache[d] = {"vix": round(vix, 2), "regime": regime, "score_penalty": penalty}
        return cache
    except Exception:
        return {}


def _get_es_data(period: str = "60d", interval: str = "5m") -> pd.DataFrame | None:
    """Download ES futures data for SMT divergence checks."""
    try:
        df = yf.Ticker("ES=F").history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return None
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(EST)
        return df
    except Exception:
        return None


def _swing_origin(df: pd.DataFrame, sweep_bar: int, direction: str, lookback: int = 30) -> float:
    """
    Find the swing origin for OTE computation.
    Long setup: highest high in lookback bars before the sweep.
    Short setup: lowest low in lookback bars before the sweep.
    """
    start = max(0, sweep_bar - lookback)
    if direction == "long":
        return float(df["High"].iloc[start:sweep_bar].max()) if sweep_bar > start else float(df["High"].iloc[sweep_bar])
    else:
        return float(df["Low"].iloc[start:sweep_bar].min()) if sweep_bar > start else float(df["Low"].iloc[sweep_bar])


def run_backtest(interval: str = "5m", period: str = "60d") -> BacktestResult:
    print(f"Loading NQ data ({period} / {interval}) ...")
    df = load_nq(interval=interval, period=period)
    df = label_sessions(df, interval=interval)
    print(f"Loaded {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

    print("Loading ES data for SMT divergence ...")
    es_df = _get_es_data(period=period, interval=interval)
    print(f"  ES data: {'loaded' if es_df is not None else 'unavailable (SMT checks skipped)'}")

    print("Loading VIX regime cache ...")
    vix_cache = _build_vix_cache(period=period)
    print(f"  VIX data: {len(vix_cache)} days loaded")

    asia_ranges   = build_asia_ranges(df)
    vwap_series   = compute_vwap(df)
    prev_day_lvls = _build_prev_day_levels(df)
    print(f"Asia ranges built for {len(asia_ranges)} trading days")

    result = BacktestResult()
    smart = SmartFilter()
    balance = STARTING_BALANCE - 400
    peak_balance = STARTING_BALANCE
    floor = STARTING_BALANCE - TRAILING_MAX_DRAWDOWN

    trades_today    = 0
    daily_pnl_today = 0.0
    prev_date       = None

    sweep_done        = {"bullish": False, "bearish": False}
    mss_confirmed     = {"bullish": False, "bearish": False}
    sweep_bar         = {"bullish": None, "bearish": None}
    sweep_depth_val   = {"bullish": 0.0, "bearish": 0.0}
    sweep_detected_at = {"bullish": None, "bearish": None}   # EST datetime of sweep
    mss_strong_cache  = {"bullish": False, "bearish": False}
    mss_bar_idx_cache = {"bullish": None, "bearish": None}
    smt_cache         = {"bullish": {"confirmed": True, "divergent": False}, "bearish": {"confirmed": True, "divergent": False}}
    ote_cache         = {"bullish": {"valid": False}, "bearish": {"valid": False}}
    london_action = {"direction": "neutral", "swept_high": False, "swept_low": False,
                     "sweep_depth_high": 0.0, "sweep_depth_low": 0.0}

    # Per-day Judas Swing state (Tuesday)
    tuesday_first_sweep_dir: str | None = None
    tuesday_judas_confirmed: bool = False

    # Per-day context
    weekly_lvls   = {"prev_week_high": None, "prev_week_low": None}
    vix_today     = {"vix": None, "regime": "unknown", "score_penalty": 0}

    opening_range_open:  float | None = None
    opening_range_close: float | None = None
    opening_range_dir:   str = "neutral"

    closes = df["Close"]
    highs  = df["High"]
    lows   = df["Low"]

    for i, (ts, row) in enumerate(df.iterrows()):
        est_dt = ts.tz_convert(EST)
        trade_date = est_dt.date()
        mins = est_dt.hour * 60 + est_dt.minute

        # ── New day reset ──────────────────────────────────────────────────────
        if trade_date != prev_date:
            if prev_date is not None:
                peak_balance = max(peak_balance, balance)
                floor = peak_balance - TRAILING_MAX_DRAWDOWN
                result.daily_pnl[prev_date] = daily_pnl_today

            trades_today    = 0
            daily_pnl_today = 0.0
            sweep_done        = {"bullish": False, "bearish": False}
            mss_confirmed     = {"bullish": False, "bearish": False}
            sweep_bar         = {"bullish": None, "bearish": None}
            sweep_depth_val   = {"bullish": 0.0, "bearish": 0.0}
            sweep_detected_at = {"bullish": None, "bearish": None}
            mss_strong_cache  = {"bullish": False, "bearish": False}
            mss_bar_idx_cache = {"bullish": None, "bearish": None}
            smt_cache         = {"bullish": {"confirmed": True, "divergent": False}, "bearish": {"confirmed": True, "divergent": False}}
            ote_cache         = {"bullish": {"valid": False}, "bearish": {"valid": False}}
            tuesday_first_sweep_dir = None
            tuesday_judas_confirmed = False
            prev_date         = trade_date
            opening_range_open  = None
            opening_range_close = None
            opening_range_dir   = "neutral"
            smart.reset_day()

            # Per-day context
            weekly_lvls = get_weekly_levels(df, trade_date)
            vix_today   = vix_cache.get(trade_date, {"vix": None, "regime": "unknown", "score_penalty": 0})

            # London action for this trade date
            ar = asia_ranges.get(trade_date)
            if ar:
                london_action = get_london_action(df, trade_date, ar["high"], ar["low"])
            else:
                london_action = {"direction": "neutral", "swept_high": False, "swept_low": False,
                                 "sweep_depth_high": 0.0, "sweep_depth_low": 0.0}

        # ── Opening range tracking ─────────────────────────────────────────────
        if mins == 9 * 60 + 30 and opening_range_open is None:
            opening_range_open = float(closes.iloc[i])
        if 9 * 60 + 30 <= mins < 10 * 60:
            opening_range_close = float(closes.iloc[i])
        if mins == 10 * 60 and opening_range_open is not None and opening_range_dir == "neutral":
            if opening_range_close and opening_range_close > opening_range_open:
                opening_range_dir = "bullish"
            elif opening_range_close and opening_range_close < opening_range_open:
                opening_range_dir = "bearish"

        # Hard stop: hit floor
        if balance <= floor:
            break

        if not row["in_trade_window"]:
            continue

        if trades_today >= MAX_TRADES_PER_DAY:
            continue

        if daily_pnl_today <= -MAX_DAILY_LOSS:
            continue

        ar = asia_ranges.get(trade_date)
        if ar is None:
            continue
        asia_high = ar["high"]
        asia_low  = ar["low"]

        price = float(row["Close"])
        high  = float(row["High"])
        low   = float(row["Low"])
        vwap  = float(vwap_series.iloc[i]) if i < len(vwap_series) else None

        # ── News check (blackout windows) ──────────────────────────────────────
        news_check = check_news_calendar(est_dt)
        if news_check["skip"]:
            continue

        # ── Sweep timeout: reset detection if sweep sat 90 min without MSS ───
        for _d in ("bullish", "bearish"):
            if sweep_done[_d] and not mss_confirmed[_d] and sweep_detected_at[_d] is not None:
                elapsed = (est_dt - sweep_detected_at[_d]).total_seconds() / 60
                if elapsed >= SWEEP_TIMEOUT_MINUTES:
                    # Tuesday: first timed-out sweep is the Judas direction
                    if trade_date.weekday() == 1 and tuesday_first_sweep_dir is None:
                        tuesday_first_sweep_dir = _d
                        tuesday_judas_confirmed = True
                    # Full reset so fresh setup can be detected
                    sweep_done[_d]        = False
                    sweep_bar[_d]         = None
                    sweep_detected_at[_d] = None
                    smt_cache[_d]         = {"confirmed": True, "divergent": False}
                    ote_cache[_d]         = {"valid": False}
                    mss_strong_cache[_d]  = False
                    mss_bar_idx_cache[_d] = None

        # ── Detect sweeps ──────────────────────────────────────────────────────
        if not sweep_done["bullish"] and low < asia_low:
            depth = round(asia_low - low, 2)
            valid, _ = smart.is_sweep_valid(low, asia_low, "long")
            if valid:
                sweep_done["bullish"]     = True
                sweep_bar["bullish"]      = i
                sweep_detected_at["bullish"] = est_dt
                sweep_depth_val["bullish"]= depth
                smt_cache["bullish"]      = check_smt_divergence(df, es_df, i, "long")
                s_origin  = _swing_origin(df, i, "long")
                s_extreme = float(lows.iloc[i])
                ote_cache["bullish"]      = compute_ote_zone(s_origin, s_extreme, "long")

        if not sweep_done["bearish"] and high > asia_high:
            depth = round(high - asia_high, 2)
            valid, _ = smart.is_sweep_valid(high, asia_high, "short")
            if valid:
                sweep_done["bearish"]     = True
                sweep_bar["bearish"]      = i
                sweep_detected_at["bearish"] = est_dt
                sweep_depth_val["bearish"]= depth
                smt_cache["bearish"]      = check_smt_divergence(df, es_df, i, "short")
                s_origin  = _swing_origin(df, i, "short")
                s_extreme = float(highs.iloc[i])
                ote_cache["bearish"]      = compute_ote_zone(s_origin, s_extreme, "short")

        # ── Detect MSS after sweep ─────────────────────────────────────────────
        for direction in ("bullish", "bearish"):
            if not sweep_done[direction] or mss_confirmed[direction]:
                continue
            sb = sweep_bar[direction]
            if sb is None or i <= sb:
                continue
            mss_result = detect_mss(df, sb, direction, lookback=15)
            if mss_result["detected"] and mss_result["mss_bar_idx"] == i:
                mss_confirmed[direction] = True
                mss_strong_cache[direction]  = mss_result.get("is_strong", False)
                mss_bar_idx_cache[direction] = i

        # ── Score and enter ────────────────────────────────────────────────────
        for direction in ("bullish", "bearish"):
            if not sweep_done[direction] or not mss_confirmed[direction]:
                continue

            signal_dir = "long" if direction == "bullish" else "short"
            sb = sweep_bar[direction]
            if sb is None:
                continue

            fvgs       = find_fvgs(df, signal_dir, sb, i, min_size_points=2.0)
            fvg_active = get_active_fvg(fvgs, price, signal_dir) is not None

            london_ok    = is_london_aligned(london_action, signal_dir)
            pdl_ok       = prev_day_lvls.get(trade_date)
            pdh          = pdl_ok["high"] if pdl_ok else None
            pdl          = pdl_ok["low"]  if pdl_ok else None
            open_opposed = (
                (opening_range_dir == "bullish" and signal_dir == "short") or
                (opening_range_dir == "bearish" and signal_dir == "long")
            )
            mss_strong_flag = mss_strong_cache.get(direction, False)

            # OTE check
            ote_active = price_in_ote(price, ote_cache[direction])

            # SMT for this direction — hard-block divergent signals
            smt_result = smt_cache[direction]
            smt_ok = smt_result.get("confirmed", True)
            if smt_result.get("divergent") and not smt_ok:
                continue  # NQ diverges from ES = fake signal, skip

            # Judas reversal mode: Tuesday second sweep, opposite of confirmed fake
            judas_mode = (
                trade_date.weekday() == 1
                and tuesday_judas_confirmed
                and direction != tuesday_first_sweep_dir
            )
            # Post-claims mode: Thursday after 10 AM
            post_claims = (trade_date.weekday() == 3 and est_dt.hour >= 10)
            setup_mode = (
                "judas_reversal" if judas_mode
                else "post_claims" if post_claims
                else "normal"
            )

            confluence = score_setup(
                asia_sweep=True,
                mss_confirmed=True,
                fvg_active=fvg_active,
                price=price,
                vwap=vwap,
                direction=signal_dir,
                bar_hour=est_dt.hour,
                bar_minute=est_dt.minute,
                london_aligned=london_ok,
                pdh_pdl_confluence=False,
                opening_range_opposed=open_opposed,
                mss_strong=mss_strong_flag,
                prev_day_high=pdh,
                prev_day_low=pdl,
                sweep_price=(
                    float(lows.iloc[sb]) if signal_dir == "long"
                    else float(highs.iloc[sb])
                ),
                prev_week_high=weekly_lvls.get("prev_week_high"),
                prev_week_low=weekly_lvls.get("prev_week_low"),
                ote_zone=ote_active,
                smt_confirmed=smt_ok,
            )

            # Build market context for smart_filter
            market_ctx = {
                "news":   news_check,
                "vix":    vix_today,
                "smt":    smt_result,
                "weekly": weekly_lvls,
            }

            min_score = smart.min_score_required(
                est_dt.hour, est_dt.minute,
                day_of_week=trade_date.weekday(),
                london_aligned=london_ok,
                mss_strong=mss_strong_flag,
                sweep_depth=sweep_depth_val[direction],
                market_context=market_ctx,
                judas_reversal_mode=judas_mode,
            )
            # 99 = skip flag from news blackout
            if min_score >= 99 or confluence.score < min_score:
                continue

            # ── Entry ─────────────────────────────────────────────────────────
            mss_idx = mss_bar_idx_cache.get(direction)
            ob = None
            if mss_idx is not None:
                ob = find_order_block(df, sb, mss_idx, signal_dir)

            if ob and ob["stop_distance"] <= MAX_STOP_POINTS:
                limit_entry = ob["entry"]
                stop_level  = ob["stop"]
            else:
                if signal_dir == "long":
                    stop_level  = round(float(lows.iloc[max(0, sb):i+1].min()) - 1.0, 2)
                    limit_entry = round(stop_level + MAX_STOP_POINTS, 2)
                else:
                    stop_level  = round(float(highs.iloc[max(0, sb):i+1].max()) + 1.0, 2)
                    limit_entry = round(stop_level - MAX_STOP_POINTS, 2)

            meta = dict(
                signal_hour=est_dt.hour,
                day_of_week=trade_date.weekday(),
                sweep_depth=sweep_depth_val[direction],
                asia_range_width=round(asia_high - asia_low, 2),
                vix_regime=vix_today.get("regime", "unknown"),
                smt_confirmed=smt_ok,
                ote_used=ote_active,
                news_penalty=news_check.get("score_penalty", 0),
                setup_mode=setup_mode,
            )

            if signal_dir == "long":
                if low > limit_entry:
                    trade = _simulate_limit_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        limit_entry=limit_entry, stop=stop_level,
                        trade_date=trade_date, score=confluence.score, reason=confluence.reason,
                        meta=meta,
                    )
                else:
                    trade = _simulate_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        entry=limit_entry, stop=stop_level,
                        tp1=round(limit_entry + abs(limit_entry - stop_level) * 1.5, 2),
                        tp2=round(limit_entry + abs(limit_entry - stop_level) * 3.0, 2),
                        contracts=1, trade_date=trade_date, score=confluence.score, reason=confluence.reason,
                        meta=meta,
                    )
            else:
                if high < limit_entry:
                    trade = _simulate_limit_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        limit_entry=limit_entry, stop=stop_level,
                        trade_date=trade_date, score=confluence.score, reason=confluence.reason,
                        meta=meta,
                    )
                else:
                    trade = _simulate_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        entry=limit_entry, stop=stop_level,
                        tp1=round(limit_entry - abs(limit_entry - stop_level) * 1.5, 2),
                        tp2=round(limit_entry - abs(limit_entry - stop_level) * 3.0, 2),
                        contracts=1, trade_date=trade_date, score=confluence.score, reason=confluence.reason,
                        meta=meta,
                    )

            if trade is None:
                continue

            result.trades.append(trade)
            trades_today    += 1
            daily_pnl_today += trade.pnl
            balance         += trade.pnl

            mss_confirmed[direction] = False
            sweep_done[direction]    = False

            break

    if prev_date:
        result.daily_pnl[prev_date] = daily_pnl_today

    return result


def _simulate_trade(
    df: pd.DataFrame,
    start_idx: int,
    direction: str,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    contracts: int,
    trade_date: date,
    score: int,
    reason: str,
    meta: dict | None = None,
) -> BacktestTrade | None:
    meta = meta or {}
    closes   = df["Close"]
    highs    = df["High"]
    lows     = df["Low"]
    est_dates = df.index.tz_convert(EST)

    be_stop       = stop
    tp1_hit       = False
    half_contracts = contracts // 2 if contracts > 1 else 0
    remaining     = contracts

    for j in range(start_idx, min(start_idx + 200, len(df))):
        bar_date = est_dates[j].date()
        if bar_date != trade_date:
            exit_price = float(closes.iloc[j - 1])
            pnl = _calc_pnl(direction, entry, exit_price, remaining) + (
                _calc_pnl(direction, entry, tp1, half_contracts) if tp1_hit else 0
            )
            return BacktestTrade(
                date=trade_date, direction=direction, entry=entry, stop=stop,
                tp1=tp1, tp2=tp2, exit_price=exit_price, contracts=contracts,
                pnl=round(pnl, 2), score=score, outcome="TIMEOUT", reason=reason, **meta,
            )

        bar_low   = float(lows.iloc[j])
        bar_high  = float(highs.iloc[j])

        if direction == "long":
            if bar_low <= be_stop:
                exit_price = be_stop
                pnl = _calc_pnl("long", entry, exit_price, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("long", entry, tp1, half_contracts)
                outcome = "WIN_TP1_BE" if tp1_hit and pnl > 0 else "LOSS"
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=exit_price, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome=outcome, reason=reason, **meta,
                )
            if not tp1_hit and bar_high >= tp1:
                tp1_hit   = True
                remaining -= half_contracts
                be_stop   = entry
            if bar_high >= tp2:
                pnl = _calc_pnl("long", entry, tp2, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("long", entry, tp1, half_contracts)
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=tp2, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome="WIN_TP2", reason=reason, **meta,
                )
        else:
            if bar_high >= be_stop:
                exit_price = be_stop
                pnl = _calc_pnl("short", entry, exit_price, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("short", entry, tp1, half_contracts)
                outcome = "WIN_TP1_BE" if tp1_hit and pnl > 0 else "LOSS"
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=exit_price, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome=outcome, reason=reason, **meta,
                )
            if not tp1_hit and bar_low <= tp1:
                tp1_hit   = True
                remaining -= half_contracts
                be_stop   = entry
            if bar_low <= tp2:
                pnl = _calc_pnl("short", entry, tp2, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("short", entry, tp1, half_contracts)
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=tp2, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome="WIN_TP2", reason=reason, **meta,
                )

    return None


def _simulate_limit_trade(
    df: pd.DataFrame,
    start_idx: int,
    direction: str,
    limit_entry: float,
    stop: float,
    trade_date,
    score: int,
    reason: str,
    meta: dict | None = None,
) -> BacktestTrade | None:
    highs     = df["High"]
    lows      = df["Low"]
    est_dates = df.index.tz_convert(EST)
    tp1 = round(limit_entry + MAX_STOP_POINTS * 1.5, 2) if direction == "long" else round(limit_entry - MAX_STOP_POINTS * 1.5, 2)
    tp2 = round(limit_entry + MAX_STOP_POINTS * 3.0, 2) if direction == "long" else round(limit_entry - MAX_STOP_POINTS * 3.0, 2)

    for j in range(start_idx, min(start_idx + 150, len(df))):
        bar_date = est_dates[j].date()
        if bar_date != trade_date:
            return None

        est_mins = est_dates[j].hour * 60 + est_dates[j].minute
        if not (9 * 60 + 30 <= est_mins < TRADE_END_HOUR * 60 + TRADE_END_MIN):
            return None

        filled = (direction == "long" and float(lows.iloc[j]) <= limit_entry) or \
                 (direction == "short" and float(highs.iloc[j]) >= limit_entry)

        if filled:
            return _simulate_trade(
                df=df, start_idx=j + 1, direction=direction,
                entry=limit_entry, stop=stop, tp1=tp1, tp2=tp2,
                contracts=1, trade_date=trade_date, score=score, reason=reason,
                meta=meta,
            )

    return None


def _calc_pnl(direction: str, entry: float, exit_price: float, contracts: int) -> float:
    if direction == "long":
        return (exit_price - entry) * contracts * MNQ_DOLLARS_PER_POINT
    return (entry - exit_price) * contracts * MNQ_DOLLARS_PER_POINT
