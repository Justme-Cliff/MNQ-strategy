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
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

from backtest.data_loader import load_nq, label_sessions
from strategy.asia_range import build_asia_ranges
from strategy.fvg_detector import find_fvgs, get_active_fvg
from strategy.mss_detector import detect_mss
from strategy.vwap import compute_vwap
from strategy.confluence_scorer import score_setup
from risk.position_sizer import calculate_size, calculate_targets
from config import (
    MIN_CONFLUENCE_SCORE,
    MAX_TRADES_PER_DAY,
    MAX_DAILY_LOSS,
    MAX_STOP_POINTS,
    MNQ_DOLLARS_PER_POINT,
    STARTING_BALANCE,
    TRAILING_MAX_DRAWDOWN,
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
    outcome: str         # "WIN_TP2", "WIN_TP1_BE", "LOSS", "TIMEOUT"
    reason: str          # confluence breakdown
    signal_hour: int = 9
    day_of_week: int = 0  # 0=Mon, 4=Fri
    sweep_depth: float = 0.0
    asia_range_width: float = 0.0


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    daily_pnl: dict = field(default_factory=dict)


def run_backtest(interval: str = "5m", period: str = "60d") -> BacktestResult:
    print(f"Loading NQ data ({period} / {interval}) ...")
    df = load_nq(interval=interval, period=period)
    df = label_sessions(df)

    print(f"Loaded {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

    # Build Asia ranges
    asia_ranges = build_asia_ranges(df)
    print(f"Asia ranges built for {len(asia_ranges)} trading days")

    # Compute VWAP
    vwap_series = compute_vwap(df)

    result = BacktestResult()
    balance = STARTING_BALANCE - 400    # start accounting for the $400 already lost
    peak_balance = STARTING_BALANCE
    floor = STARTING_BALANCE - TRAILING_MAX_DRAWDOWN

    trades_today = 0
    daily_pnl_today = 0.0
    prev_date = None

    # Track sweep/MSS state per day
    sweep_done = {"bullish": False, "bearish": False}
    mss_confirmed = {"bullish": False, "bearish": False}
    sweep_bar = {"bullish": None, "bearish": None}
    sweep_depth = {"bullish": 0.0, "bearish": 0.0}

    closes = df["Close"]
    highs = df["High"]
    lows = df["Low"]

    for i, (ts, row) in enumerate(df.iterrows()):
        est_dt = ts.tz_convert(EST)
        trade_date = est_dt.date()

        # New day reset
        if trade_date != prev_date:
            if prev_date is not None:
                # Update trailing drawdown floor at EOD
                peak_balance = max(peak_balance, balance)
                floor = peak_balance - TRAILING_MAX_DRAWDOWN
                result.daily_pnl[prev_date] = daily_pnl_today

            trades_today = 0
            daily_pnl_today = 0.0
            sweep_done = {"bullish": False, "bearish": False}
            mss_confirmed = {"bullish": False, "bearish": False}
            sweep_bar = {"bullish": None, "bearish": None}
            sweep_depth = {"bullish": 0.0, "bearish": 0.0}
            prev_date = trade_date

        # Hard stop: hit floor
        if balance <= floor:
            break

        # Only process trade window bars
        if not row["in_trade_window"]:
            continue

        if trades_today >= MAX_TRADES_PER_DAY:
            continue

        if daily_pnl_today <= -MAX_DAILY_LOSS:
            continue

        # Get Asia range for today
        ar = asia_ranges.get(trade_date)
        if ar is None:
            continue
        asia_high = ar["high"]
        asia_low = ar["low"]

        price = float(row["Close"])
        high = float(row["High"])
        low = float(row["Low"])

        vwap = float(vwap_series.iloc[i]) if i < len(vwap_series) else None

        # ── Detect sweeps ──────────────────────────────────────────────────────
        if not sweep_done["bullish"] and low < asia_low:
            sweep_done["bullish"] = True
            sweep_bar["bullish"] = i
            sweep_depth["bullish"] = round(asia_low - low, 2)

        if not sweep_done["bearish"] and high > asia_high:
            sweep_done["bearish"] = True
            sweep_bar["bearish"] = i
            sweep_depth["bearish"] = round(high - asia_high, 2)

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

        # ── Score and enter ────────────────────────────────────────────────────
        for direction in ("bullish", "bearish"):
            if not sweep_done[direction] or not mss_confirmed[direction]:
                continue

            signal_dir = "long" if direction == "bullish" else "short"
            sb = sweep_bar[direction]
            if sb is None:
                continue

            # Find FVGs since the sweep
            fvgs = find_fvgs(df, signal_dir, sb, i, min_size_points=2.0)
            fvg_active = get_active_fvg(fvgs, price, signal_dir) is not None

            confluence = score_setup(
                asia_sweep=True,
                mss_confirmed=True,
                fvg_active=fvg_active,
                price=price,
                vwap=vwap,
                direction=signal_dir,
                bar_hour=est_dt.hour,
                bar_minute=est_dt.minute,
            )

            if not confluence.tradeable:
                continue

            # ── Entry via limit order (retracement into zone) ─────────────────
            # Stop = below the sweep wick. Entry = limit order placed at
            # (stop + MAX_STOP_POINTS) so risk is always exactly $50 on 1 contract.
            # We wait for price to pull back to that limit level after the MSS.

            if signal_dir == "long":
                sweep_wick = round(float(lows.iloc[max(0, sb):i+1].min()) - 1.0, 2)
                stop_level = sweep_wick
                limit_entry = round(stop_level + MAX_STOP_POINTS, 2)
            else:
                sweep_wick = round(float(highs.iloc[max(0, sb):i+1].max()) + 1.0, 2)
                stop_level = sweep_wick
                limit_entry = round(stop_level - MAX_STOP_POINTS, 2)

            meta = dict(
                signal_hour=est_dt.hour,
                day_of_week=trade_date.weekday(),
                sweep_depth=sweep_depth[direction],
                asia_range_width=round(asia_high - asia_low, 2),
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
                        tp1=round(limit_entry + MAX_STOP_POINTS * 1.5, 2),
                        tp2=round(limit_entry + MAX_STOP_POINTS * 3.0, 2),
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
                        tp1=round(limit_entry - MAX_STOP_POINTS * 1.5, 2),
                        tp2=round(limit_entry - MAX_STOP_POINTS * 3.0, 2),
                        contracts=1, trade_date=trade_date, score=confluence.score, reason=confluence.reason,
                        meta=meta,
                    )

            if trade is None:
                continue

            # Record
            result.trades.append(trade)
            trades_today += 1
            daily_pnl_today += trade.pnl
            balance += trade.pnl

            # Reset MSS state so we don't re-enter same direction
            mss_confirmed[direction] = False
            sweep_done[direction] = False

            break  # one signal per bar

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
    closes = df["Close"]
    highs = df["High"]
    lows = df["Low"]
    est_dates = df.index.tz_convert(EST)

    be_stop = stop        # becomes entry after TP1 hit
    tp1_hit = False
    # With 1 contract: no partial exit at TP1, just move stop to BE then exit at TP2.
    # With 2+ contracts: exit half at TP1, remaining at TP2.
    half_contracts = contracts // 2 if contracts > 1 else 0
    remaining = contracts

    for j in range(start_idx, min(start_idx + 200, len(df))):
        bar_date = est_dates[j].date()
        if bar_date != trade_date:
            # End of day — close at last close
            exit_price = float(closes.iloc[j - 1])
            pnl = _calc_pnl(direction, entry, exit_price, remaining) + (
                _calc_pnl(direction, entry, tp1, half_contracts) if tp1_hit else 0
            )
            return BacktestTrade(
                date=trade_date, direction=direction, entry=entry, stop=stop,
                tp1=tp1, tp2=tp2, exit_price=exit_price, contracts=contracts,
                pnl=round(pnl, 2), score=score, outcome="TIMEOUT", reason=reason, **meta,
            )

        bar_low  = float(lows.iloc[j])
        bar_high = float(highs.iloc[j])
        bar_close = float(closes.iloc[j])

        if direction == "long":
            # Stop hit
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
            # TP1 hit
            if not tp1_hit and bar_high >= tp1:
                tp1_hit = True
                remaining -= half_contracts
                be_stop = entry
            # TP2 hit
            if bar_high >= tp2:
                exit_price = tp2
                pnl = _calc_pnl("long", entry, tp2, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("long", entry, tp1, half_contracts)
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=tp2, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome="WIN_TP2", reason=reason, **meta,
                )
        else:  # short
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
                tp1_hit = True
                remaining -= half_contracts
                be_stop = entry
            if bar_low <= tp2:
                exit_price = tp2
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
    """
    Simulate waiting for price to pull back to limit_entry after the MSS.
    If price never touches the limit, no trade (returns None).
    """
    highs = df["High"] if "High" in df.columns else df["high"]
    lows = df["Low"] if "Low" in df.columns else df["low"]
    est_dates = df.index.tz_convert(EST)
    tp1 = round(limit_entry + MAX_STOP_POINTS * 1.5, 2) if direction == "long" else round(limit_entry - MAX_STOP_POINTS * 1.5, 2)
    tp2 = round(limit_entry + MAX_STOP_POINTS * 3.0, 2) if direction == "long" else round(limit_entry - MAX_STOP_POINTS * 3.0, 2)

    for j in range(start_idx, min(start_idx + 150, len(df))):
        bar_date = est_dates[j].date()
        if bar_date != trade_date:
            return None  # end of session, no fill

        # Enforce trade window (9:30-11:30 AM) for limit fill
        est_h = est_dates[j].hour
        est_m = est_dates[j].minute
        mins = est_h * 60 + est_m
        if not (9 * 60 + 30 <= mins < 11 * 60 + 30):
            return None

        bar_low  = float(lows.iloc[j])
        bar_high = float(highs.iloc[j])

        filled = (direction == "long" and bar_low <= limit_entry) or \
                 (direction == "short" and bar_high >= limit_entry)

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
