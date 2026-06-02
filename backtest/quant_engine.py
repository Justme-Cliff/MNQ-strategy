"""
Quantitative Strategy Backtest Engine — Adaptive Multi-Regime System.

Strategy priority per day (max 2 trades):
  1. Gap Fill    — highest WR (77-93%), fires at session open
  2. FVG         — Fair Value Gap fills (60-75% WR), fires all session — works in ANY regime
  3. ORB         — ATR-normalized opening range breakout (72-74% documented WR)
  4. IB Breakout — ATR-normalized IB (84% single-direction stat on NQ), fires 10:00-11:30
  5. VWAP Rev    — 66-67% WR, ONLY in neutral trend + normal vol (ADX < 25 equivalent)

Key adaptations:
  - All range/stop/target parameters are ATR-normalized (not fixed points)
  - Trend gating via EMA8/EMA21 (replaces simple 5-day return)
  - FVG added as the universal strategy that works in crash, recovery, and sideways
  - IB target extended to 1.5× range (research: trend days go 2-3×)
  - ORB range filter: 0.025–0.50× adaptive ATR (auto-scales to any volatility)

Risk management (prop firm compliant):
  - Max risk per trade: $50 (25 pts × $2/pt on 1 MNQ contract)
  - Max 2 trades per day
  - Max daily loss: $100
  - Session: 9:30 AM – noon ET
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

from backtest.data_loader import load_nq, label_sessions
from strategy.quant_regime import (
    classify_market_full, get_daily_atr, get_atr_adaptive, classify_regime,
    direction_allowed,
)
from strategy.quant_gap  import detect as detect_gap
from strategy.quant_orb  import detect as detect_orb
from strategy.quant_ib   import detect as detect_ib
from strategy.quant_vwap import detect_all as detect_vwap, detect_bounce as detect_vwap_bounce
from strategy.quant_fvg  import detect as detect_fvg

EST = ZoneInfo("America/New_York")

MNQ_PER_POINT     = 2.0
CHANDELIER_MULT   = 3.0
MAX_RISK_USD   = 50.0
MAX_STOP_PTS   = 25.0
MAX_TRADES_DAY = 3
MAX_DAILY_LOSS = 150.0


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class QuantTrade:
    date:       date
    day_name:   str
    strategy:   str
    direction:  str
    entry:      float
    stop:       float
    target:     float
    exit_price: float
    pnl:        float
    outcome:    str
    risk_pts:   float
    reward_pts: float
    rr:         float
    vix:        float
    regime:     str
    trend_dir:  str = ""
    signal_detail: str = ""


# ── VIX loader ────────────────────────────────────────────────────────────────

def _load_vix(period: str = "90d") -> dict[date, float]:
    try:
        vix = yf.Ticker("^VIX").history(period=period, interval="1d", auto_adjust=True)
        if vix.empty:
            return {}
        result = {}
        for ts, row in vix.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        return result
    except Exception:
        return {}


def _get_vix(vix_cache: dict, trade_date: date) -> float:
    if trade_date in vix_cache:
        return vix_cache[trade_date]
    for d in range(1, 6):
        check = trade_date - timedelta(days=d)
        if check in vix_cache:
            return vix_cache[check]
    return 18.0


# ── Trade simulation ──────────────────────────────────────────────────────────

def _bar_atr(df: pd.DataFrame, bar_idx: int, window: int = 14) -> float:
    """14-bar intraday True Range average for Chandelier trail."""
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


def _simulate_trade(
    df: pd.DataFrame,
    signal_bar_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    be_mult: float = 1.0,   # retained for signature compat; T1 system supersedes it
    max_hour: int = 12,
) -> tuple[float, float, str]:
    """
    Two-target exit system.
    T1: 1x risk -> exit 50% of position, lock that P&L.
    T2: trail remaining 50% with 3x intraday ATR Chandelier stop.
    Original stop holds until T1 is hit; after T1 stop is >= entry (long) / <= entry (short).
    """
    per_pt_half = MNQ_PER_POINT * 0.5

    risk_pts = abs(entry - stop)
    if risk_pts < 1.0:
        return entry, 0.0, "WIN"

    t1_target   = (entry + risk_pts) if direction == "long" else (entry - risk_pts)
    intra_atr   = _bar_atr(df, signal_bar_idx)

    t1_hit     = False
    t1_pnl     = 0.0
    curr_stop  = stop
    trail_anch = entry

    for i in range(signal_bar_idx, min(signal_bar_idx + 300, len(df))):
        row   = df.iloc[i]
        high  = float(row["High"])
        low   = float(row["Low"])
        close = float(row["Close"])

        ts_est = df.index[i].astimezone(EST)
        if ts_est.hour >= max_hour:
            if t1_hit:
                remain = (close - entry) if direction == "long" else (entry - close)
                total  = t1_pnl + remain * per_pt_half
                return close, total, "WIN" if total > 0 else "LOSS"
            pts = (close - entry) if direction == "long" else (entry - close)
            return close, pts * per_pt_half * 2, "WIN" if pts > 0 else "LOSS"

        if not t1_hit:
            if direction == "long":
                if high >= target and low > curr_stop:
                    return target, (target - entry) * per_pt_half * 2, "WIN"
                if high >= t1_target:
                    t1_pnl    = risk_pts * per_pt_half
                    t1_hit    = True
                    trail_anch = max(high, t1_target)
                    curr_stop  = max(entry, trail_anch - CHANDELIER_MULT * intra_atr)
                    if high >= target:
                        return target, t1_pnl + (target - entry) * per_pt_half, "WIN"
                elif low <= curr_stop:
                    pts = curr_stop - entry
                    return curr_stop, pts * per_pt_half * 2, "LOSS" if pts < 0 else "WIN"
            else:
                if low <= target and high < curr_stop:
                    return target, (entry - target) * per_pt_half * 2, "WIN"
                if low <= t1_target:
                    t1_pnl    = risk_pts * per_pt_half
                    t1_hit    = True
                    trail_anch = min(low, t1_target)
                    curr_stop  = min(entry, trail_anch + CHANDELIER_MULT * intra_atr)
                    if low <= target:
                        return target, t1_pnl + (entry - target) * per_pt_half, "WIN"
                elif high >= curr_stop:
                    pts = entry - curr_stop
                    return curr_stop, pts * per_pt_half * 2, "LOSS" if pts < 0 else "WIN"
        else:
            if direction == "long":
                trail_anch = max(trail_anch, high)
                curr_stop  = max(curr_stop, trail_anch - CHANDELIER_MULT * intra_atr)
                curr_stop  = max(curr_stop, entry)
                if high >= target:
                    return target, t1_pnl + (target - entry) * per_pt_half, "WIN"
                elif low <= curr_stop:
                    total = t1_pnl + (curr_stop - entry) * per_pt_half
                    return curr_stop, total, "WIN" if total > 0 else "LOSS"
            else:
                trail_anch = min(trail_anch, low)
                curr_stop  = min(curr_stop, trail_anch + CHANDELIER_MULT * intra_atr)
                curr_stop  = min(curr_stop, entry)
                if low <= target:
                    return target, t1_pnl + (entry - target) * per_pt_half, "WIN"
                elif high >= curr_stop:
                    total = t1_pnl + (entry - curr_stop) * per_pt_half
                    return curr_stop, total, "WIN" if total > 0 else "LOSS"

    last = float(df["Close"].iloc[-1])
    if t1_hit:
        remain = (last - entry) if direction == "long" else (entry - last)
        total  = t1_pnl + remain * per_pt_half
        return last, total, "WIN" if total > 0 else "LOSS"
    pts = (last - entry) if direction == "long" else (entry - last)
    return last, pts * per_pt_half * 2, "LOSS" if pts < 0 else "WIN"


def _add_trade(
    trades: list,
    df: pd.DataFrame,
    today: date,
    dow: int,
    strategy: str,
    sig,
    market: dict,
    day_names: list,
    signal_detail: str = "",
    max_hour: int = 12,
) -> tuple[float, bool]:
    """
    Simulate and record a trade. Returns (pnl, trade_added).
    max_hour=12 for AM strategies, 16 for PM VWAP.
    """
    risk_pts = abs(sig.entry - sig.stop)
    if risk_pts < 1.0:
        return 0.0, False

    be_mult = 2.0 if strategy == "orb" else 1.0
    exit_p, pnl, outcome = _simulate_trade(
        df, sig.signal_bar_idx,
        sig.direction, sig.entry, sig.stop, sig.target,
        be_mult=be_mult, max_hour=max_hour,
    )
    reward_pts = abs(sig.target - sig.entry)
    rr = reward_pts / risk_pts if risk_pts > 0 else 0

    trades.append(QuantTrade(
        date=today, day_name=day_names[dow],
        strategy=strategy, direction=sig.direction,
        entry=sig.entry, stop=sig.stop, target=sig.target,
        exit_price=exit_p, pnl=pnl, outcome=outcome,
        risk_pts=risk_pts, reward_pts=reward_pts, rr=rr,
        vix=market["vix"], regime=market["vix_regime"],
        trend_dir=market["ema_trend"]["direction"],
        signal_detail=signal_detail,
    ))
    return pnl, True


# ── Core day scanner (shared by backtest and live monitor) ───────────────────

def _scan_day(
    df: pd.DataFrame,
    vix_cache: dict,
    today: date,
    trades: list[QuantTrade],
    day_names: list[str],
) -> None:
    """Scan one trading day and append any signals found to `trades`."""
    dow = today.weekday()
    if dow >= 5:
        return

    vix    = _get_vix(vix_cache, today)
    market = classify_market_full(df, today, vix)
    atr    = market["atr"]
    trend  = market["ema_trend"]

    trades_today = 0
    daily_pnl    = 0.0
    used_strats: set[str] = set()

    est_idx  = df.index.tz_convert(EST)
    today_df = df[est_idx.date == today].copy()

    def _can_trade() -> bool:
        return trades_today < MAX_TRADES_DAY and daily_pnl > -MAX_DAILY_LOSS

    def _try(strategy, sig, detail="", max_hour=12) -> bool:
        nonlocal trades_today, daily_pnl
        if sig is None or not _can_trade():
            return False
        pnl, added = _add_trade(
            trades, df, today, dow, strategy, sig, market, day_names, detail,
            max_hour=max_hour,
        )
        if added:
            trades_today += 1
            daily_pnl    += pnl
            used_strats.add(strategy)
            return True
        return False

    def _1h_bias_ok(sig) -> bool:
        try:
            signal_ts = df.index[sig.signal_bar_idx]
            pre = today_df[today_df.index < signal_ts]
            if len(pre) < 6:
                return True
            hourly = pre.resample("1h").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
            ).dropna()
            if hourly.empty:
                return True
            last_h = hourly.iloc[-1]
            o, c = float(last_h["Open"]), float(last_h["Close"])
            if c > o * 1.0001:
                return sig.direction == "long"
            elif c < o * 0.9999:
                return sig.direction == "short"
            return True
        except Exception:
            return True

    vix_ok_breakout = market["vix"] < 25

    if _can_trade():
        gap = detect_gap(df, today, atr, dow=dow)
        if gap and direction_allowed(gap.direction, trend, strict=True):
            _try("gap_fill", gap, f"gap={gap.gap_size:.1f}pts ({gap.gap_ratio:.2f}xATR)")

    fvg_ok_trend = trend["direction"] == "neutral"
    if _can_trade() and vix_ok_breakout and fvg_ok_trend and dow != 0:
        fvg = detect_fvg(df, today, atr, trend["direction"])
        if fvg and direction_allowed(fvg.direction, trend, strict=True):
            _try("fvg", fvg, f"zone={fvg.zone_size:.1f}pts trend={trend['direction']}")

    if _can_trade() and vix_ok_breakout:
        orb = detect_orb(df, today, atr, dow)
        if orb:
            # ORB uses custom inline trend logic intentionally — stricter than direction_allowed():
            # longs require strong_bull/neutral (not just "not strong_bear");
            # shorts require strong_bear only (not general bear).
            # This matches ORB's mean-reversion character: we need confirmed momentum, not any trend.
            ok = (trend["direction"] == "strong_bear" if orb.direction == "short"
                  else trend["direction"] in ("strong_bull", "neutral"))
            if ok and _1h_bias_ok(orb):
                _try("orb", orb, f"ORB={orb.orb_range:.0f}pts [{orb.entry_type}]")

    if _can_trade() and vix_ok_breakout and dow != 0 and "orb" not in used_strats:
        ib = detect_ib(df, today, atr)
        if ib and direction_allowed(ib.direction, trend, strict=True) and _1h_bias_ok(ib):
            _try("ib_breakout", ib, f"IB={ib.ib_range:.0f}pts bias={ib.ib_bias}")

    if _can_trade() and market["vwap_ok"]:
        for vs in detect_vwap(df, today, vix, atr, max_signals=MAX_TRADES_DAY - trades_today):
            if not _can_trade(): break
            if direction_allowed(vs.direction, trend, strict=True) and _1h_bias_ok(vs):
                _try("vwap_rev", vs, f"dev={vs.deviation_pts:.1f}pts")
                if not _can_trade(): break

    # PM VWAP: require strong trend alignment — backtested at barely profitable (62.5% WR, -$1 PnL)
    pm_trend_ok = trend["direction"] in ("strong_bull", "strong_bear")
    if _can_trade() and market["vwap_ok"] and pm_trend_ok:
        for vs in detect_vwap(df, today, vix, atr,
                               max_signals=MAX_TRADES_DAY - trades_today,
                               start_min=13*60+30, end_min=15*60+30):
            if not _can_trade(): break
            if direction_allowed(vs.direction, trend, strict=True) and _1h_bias_ok(vs):
                _try("vwap_pm", vs, f"PM dev={vs.deviation_pts:.1f}pts", max_hour=16)
                if not _can_trade(): break

    if _can_trade() and market["vwap_ok"]:
        for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"],
                                      max_signals=MAX_TRADES_DAY - trades_today):
            if not _can_trade(): break
            if direction_allowed(vs.direction, trend, strict=True):
                _try("vwap_bounce", vs, f"bounce {trend['direction']}")
                if not _can_trade(): break

    if _can_trade() and market["vwap_ok"]:
        for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"],
                                      max_signals=MAX_TRADES_DAY - trades_today,
                                      start_min=13*60+30, end_min=15*60+30):
            if not _can_trade(): break
            if direction_allowed(vs.direction, trend, strict=True):
                _try("vwap_bounce_pm", vs, f"PM bounce {trend['direction']}", max_hour=16)
                if not _can_trade(): break


# ── Main backtest ─────────────────────────────────────────────────────────────

def run_quant_backtest(interval: str = "5m", period: str = "60d") -> list[QuantTrade]:
    print(f"Loading NQ data ({period} / {interval}) ...")
    df = load_nq(interval=interval, period=period)
    df = label_sessions(df, interval=interval)
    print(f"Loaded {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

    print("Loading VIX ...")
    vix_cache = _load_vix(period="90d")
    print(f"  VIX: {len(vix_cache)} days loaded")

    est_idx   = df.index.tz_convert(EST)
    all_dates = sorted(set(est_idx.date))
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    trades: list[QuantTrade] = []

    print(f"Scanning {len(all_dates)} trading days ...")
    for today in all_dates:
        _scan_day(df, vix_cache, today, trades, day_names)

    return trades


def run_quant_today(df: pd.DataFrame, vix_cache: dict) -> list[QuantTrade]:
    """
    Scan only today using pre-loaded data — no download, runs in <100ms.
    Used by the live monitor so it doesn't re-download on every bar close.
    """
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    trades: list[QuantTrade] = []
    _scan_day(df, vix_cache, date.today(), trades, day_names)
    return trades
