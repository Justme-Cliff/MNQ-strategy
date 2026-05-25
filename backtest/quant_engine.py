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
import yfinance as yf

from backtest.data_loader import load_nq, label_sessions
from strategy.quant_regime import (
    classify_market_full, get_daily_atr, get_atr_adaptive, classify_regime,
    direction_allowed,
)
from strategy.quant_gap  import detect as detect_gap
from strategy.quant_orb  import detect as detect_orb
from strategy.quant_ib   import detect as detect_ib
from strategy.quant_vwap import detect_all as detect_vwap
from strategy.quant_fvg  import detect as detect_fvg

EST = ZoneInfo("America/New_York")

MNQ_PER_POINT  = 2.0
MAX_RISK_USD   = 50.0
MAX_STOP_PTS   = 25.0
MAX_TRADES_DAY = 2
MAX_DAILY_LOSS = 100.0


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

def _simulate_trade(
    df: pd.DataFrame,
    signal_bar_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
) -> tuple[float, float, str]:
    """
    Simulate bar-by-bar outcome after signal_bar_idx.
    Tie-break: candle direction determines whether stop or target hit first.
    """
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
            pnl = (close - entry) * MNQ_PER_POINT if direction == "long" \
                  else (entry - close) * MNQ_PER_POINT
            return close, pnl, "LOSS" if pnl < 0 else "WIN"

        if direction == "long":
            hit_stop   = low  <= stop
            hit_target = high >= target
            if hit_stop and hit_target:
                if close >= open_:
                    pnl = reward_pts * MNQ_PER_POINT
                    return target, pnl, "WIN"
                else:
                    pnl = -risk_pts * MNQ_PER_POINT
                    return stop, pnl, "LOSS"
            elif hit_target:
                pnl = reward_pts * MNQ_PER_POINT
                return target, pnl, "WIN"
            elif hit_stop:
                pnl = -risk_pts * MNQ_PER_POINT
                return stop, pnl, "LOSS"
        else:
            hit_stop   = high >= stop
            hit_target = low  <= target
            if hit_stop and hit_target:
                if close <= open_:
                    pnl = reward_pts * MNQ_PER_POINT
                    return target, pnl, "WIN"
                else:
                    pnl = -risk_pts * MNQ_PER_POINT
                    return stop, pnl, "LOSS"
            elif hit_target:
                pnl = reward_pts * MNQ_PER_POINT
                return target, pnl, "WIN"
            elif hit_stop:
                pnl = -risk_pts * MNQ_PER_POINT
                return stop, pnl, "LOSS"

    last = float(df["Close"].iloc[-1])
    pnl = (last - entry) * MNQ_PER_POINT if direction == "long" \
          else (entry - last) * MNQ_PER_POINT
    return last, pnl, "LOSS" if pnl < 0 else "WIN"


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
) -> tuple[float, bool]:
    """
    Simulate and record a trade. Returns (pnl, trade_added).
    """
    risk_pts = abs(sig.entry - sig.stop)
    if risk_pts < 1.0:
        return 0.0, False

    exit_p, pnl, outcome = _simulate_trade(
        df, sig.signal_bar_idx,
        sig.direction, sig.entry, sig.stop, sig.target,
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
    trades: list[QuantTrade] = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    print(f"Scanning {len(all_dates)} trading days ...")

    for today in all_dates:
        dow = today.weekday()
        if dow >= 5:     # skip weekend timezone artifacts
            continue

        vix    = _get_vix(vix_cache, today)
        market = classify_market_full(df, today, vix)
        atr    = market["atr"]
        trend  = market["ema_trend"]

        trades_today = 0
        daily_pnl    = 0.0
        used_strats: set[str] = set()

        def _can_trade() -> bool:
            return trades_today < MAX_TRADES_DAY and daily_pnl > -MAX_DAILY_LOSS

        def _try(strategy, sig, detail="") -> bool:
            nonlocal trades_today, daily_pnl
            if sig is None:
                return False
            if not _can_trade():
                return False
            pnl, added = _add_trade(
                trades, df, today, dow, strategy, sig, market, day_names, detail
            )
            if added:
                trades_today += 1
                daily_pnl += pnl
                used_strats.add(strategy)
                return True
            return False

        # ── Priority 1: Gap Fill ───────────────────────────────────────────────
        # In trending markets: only take gap fills in the TREND direction.
        # Gap UP (short entry) in a bull market rarely fills — bulls buy every dip.
        # Gap DOWN (long entry) in a bull market DOES fill — bulls step in immediately.
        if _can_trade():
            gap = detect_gap(df, today, atr)
            if gap and direction_allowed(gap.direction, trend, strict=True):
                _try("gap_fill", gap,
                     f"gap={gap.gap_size:.1f}pts ({gap.gap_ratio:.2f}×ATR)")

        vix_ok_breakout = market["vix"] < 22  # elevated VIX (22-30) destroys ORB/IB/FVG stats

        # ── Priority 2: FVG ───────────────────────────────────────────────────
        # FVG is a mean-reversion strategy — only valid in neutral/sideways markets.
        # In trending markets, zones get blown through rather than respected.
        fvg_ok_trend = trend["direction"] == "neutral"
        if _can_trade() and vix_ok_breakout and fvg_ok_trend:
            fvg = detect_fvg(df, today, atr, trend["direction"])
            if fvg and direction_allowed(fvg.direction, trend, strict=True):
                _try("fvg", fvg,
                     f"zone={fvg.zone_size:.1f}pts trend={trend['direction']}")

        # ── Priority 3: ORB ───────────────────────────────────────────────────
        # ORB requires VIX < 22 — elevated VIX causes chaotic opens that stop out breakouts.
        # Longs: strong_bull or neutral only (bull-trend ORBs show poor WR empirically).
        # Shorts: strong_bear only (neutral ORB shorts get squeezed in crash recoveries).
        if _can_trade() and vix_ok_breakout:
            orb = detect_orb(df, today, atr, dow)
            if orb:
                if orb.direction == "short":
                    ok = trend["direction"] == "strong_bear"
                else:
                    ok = trend["direction"] in ("strong_bull", "neutral")
                if ok:
                    _try("orb", orb,
                         f"ORB={orb.orb_range:.0f}pts ({orb.atr_ratio:.2f}×ATR) VWAP={orb.vwap_at_entry:.0f}")

        # ── Priority 4: IB Breakout ───────────────────────────────────────────
        # IB needs a neutral/sideways session to form a meaningful balance range.
        ib_ok_trend = trend["direction"] == "neutral"
        if _can_trade() and vix_ok_breakout and dow != 0 and "orb" not in used_strats and ib_ok_trend:
            ib = detect_ib(df, today, atr)
            if ib and direction_allowed(ib.direction, trend, strict=True):
                _try("ib_breakout", ib,
                     f"IB={ib.ib_range:.0f}pts ({ib.atr_ratio:.2f}×ATR) bias={ib.ib_bias}")

        # ── Priority 5: VWAP Reversion (neutral regime only) ─────────────────
        if _can_trade() and market["vwap_ok"]:
            remaining = MAX_TRADES_DAY - trades_today
            vwap_sigs = detect_vwap(df, today, vix, atr,
                                    max_signals=remaining)
            for vs in vwap_sigs:
                if not _can_trade():
                    break
                if direction_allowed(vs.direction, trend, strict=True):
                    _try("vwap_rev", vs,
                         f"dev={vs.deviation_pts:.1f}pts ({vs.deviation_std:.1f}σ) ATR={atr:.0f}")

    return trades
