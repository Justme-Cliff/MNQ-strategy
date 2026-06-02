"""
Walk-Forward Validation — Out-of-sample test of the hybrid system.

Methodology (rolling, not anchored):
  - In-sample window : 90 trading days (~4.5 months)
  - Out-of-sample    : 30 trading days (~1.5 months)
  - Embargo          : 5 trading days between IS and OOS (prevent leakage)
  - Slide forward    : 30 days at a time
  - Total data       : ~1 year (yfinance period="1y")

Walk-Forward Efficiency (WFE) = (avg OOS annualized return) / (avg IS annualized return)
  WFE > 80%  → exceptional, minimal curve-fitting
  WFE 50-80% → robust and tradeable
  WFE 35-50% → borderline — reduce parameter count
  WFE < 35%  → curve-fitted — do not trade live

Run with: python3 -m backtest.walk_forward
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import yfinance as yf

from backtest.data_loader import load_nq, load_es, label_sessions
from backtest.hybrid_engine import (
    _load_vix, _load_extended_vix, _get_vix, _get_ext_vix,
    run_hybrid_backtest, HybridTrade,
)

# NOTE: yfinance 5m data is limited to the last 60 trading days.
# A proper walk-forward needs 1+ year of data. Until we have a longer data
# source (Databento historical, proprietary CSV), we use a simple IS/OOS split:
#   IS: first 75% of available days
#   OOS: last 25% of available days
# This is statistically limited (1 OOS period) but still gives a directional signal.
# Run multiple times as new 60-day windows become available to build confidence.
IS_PCT         = 0.75   # fraction of data used as in-sample
EMBARGO_DAYS   = 3      # trading days between IS end and OOS start
TRADING_DAYS_PER_YEAR = 252


def _split_dates(all_dates: list[date]) -> list[tuple[list[date], list[date]]]:
    """
    Single IS/OOS split (limited by yfinance 60-day 5m window).
    IS = first 75%, OOS = last 25% after a 3-day embargo.
    """
    n = len(all_dates)
    is_end    = int(n * IS_PCT)
    oos_start = is_end + EMBARGO_DAYS

    if oos_start >= n or is_end < 20 or n - oos_start < 5:
        return []

    return [(all_dates[:is_end], all_dates[oos_start:])]


def _stats_for_dates(
    trades: list[HybridTrade],
    date_set: set[date],
    n_days: int,
) -> dict:
    subset = [t for t in trades if t.date in date_set]
    if not subset:
        return {"trades": 0, "wins": 0, "pnl": 0.0, "wr": 0.0, "ann_ret": 0.0}

    wins = [t for t in subset if t.outcome == "WIN"]
    pnl  = sum(t.pnl for t in subset)
    wr   = len(wins) / len(subset) * 100

    # Annualized return (as % of starting $25k)
    ann_ret = (pnl / 25_000) / n_days * TRADING_DAYS_PER_YEAR * 100

    return {
        "trades": len(subset),
        "wins":   len(wins),
        "pnl":    pnl,
        "wr":     wr,
        "ann_ret": ann_ret,
    }


def run_walk_forward(period: str = "1y") -> None:
    print("=" * 70)
    print("  WALK-FORWARD VALIDATION")
    print(f"  IS=75%  OOS=25%  Embargo={EMBARGO_DAYS}d  Data={period}")
    print("=" * 70)

    print(f"\nNOTE: yfinance 5m data is limited to 60 days. Using a single 75%/25%")
    print(f"IS/OOS split. This gives 1 OOS period — directional signal only.")
    print(f"For proper walk-forward, collect 1yr of daily backtest runs over time.")

    # Run full backtest on the available period (strategy rules fixed — no re-optimization)
    print(f"\nRunning full hybrid backtest ({period}) ...")
    trades = run_hybrid_backtest(interval="5m", period=period)

    if not trades:
        print("No trades generated. Check data availability.")
        return

    all_trade_dates = sorted(set(t.date for t in trades))
    from zoneinfo import ZoneInfo
    EST = ZoneInfo("America/New_York")

    df = load_nq(interval="5m", period=period)
    df = label_sessions(df, interval="5m")
    est_idx   = df.index.tz_convert(EST)
    all_dates = sorted(set(est_idx.date))
    print(f"Total calendar: {len(all_dates)} trading days, {len(trades)} trades")

    splits = _split_dates(all_dates)
    if not splits:
        print("Not enough data for walk-forward splits. Use period='2y' or larger.")
        return

    print(f"Walk-forward splits: {len(splits)}")
    print()

    results = []
    print(f"  {'Period':<20} {'IS Trades':>9} {'IS WR':>7} {'IS PnL':>9} "
          f"{'OOS Trades':>10} {'OOS WR':>8} {'OOS PnL':>9} {'WFE':>7}")
    print("  " + "-" * 80)

    for i, (is_dates, oos_dates) in enumerate(splits):
        is_set  = set(is_dates)
        oos_set = set(oos_dates)

        is_stats  = _stats_for_dates(trades, is_set,  len(is_dates))
        oos_stats = _stats_for_dates(trades, oos_set, len(oos_dates))

        wfe = (oos_stats["ann_ret"] / is_stats["ann_ret"] * 100
               if is_stats["ann_ret"] > 0 else 0.0)

        period_label = f"{is_dates[0]}→{oos_dates[-1]}"
        print(
            f"  {period_label:<20} "
            f"{is_stats['trades']:>9}  {is_stats['wr']:>5.1f}%  ${is_stats['pnl']:>7.0f}  "
            f"{oos_stats['trades']:>10}  {oos_stats['wr']:>6.1f}%  ${oos_stats['pnl']:>7.0f}  "
            f"{wfe:>6.0f}%"
        )
        results.append({
            "is": is_stats, "oos": oos_stats, "wfe": wfe,
            "is_start": is_dates[0], "oos_end": oos_dates[-1],
        })

    if not results:
        return

    # Summary
    print("\n" + "=" * 70)
    all_oos_trades = sum(r["oos"]["trades"] for r in results)
    all_oos_pnl    = sum(r["oos"]["pnl"] for r in results)
    oos_wins_tot   = sum(r["oos"]["wins"] for r in results)
    avg_wfe        = float(np.mean([r["wfe"] for r in results if r["is"]["ann_ret"] > 0]))
    oos_wr         = oos_wins_tot / all_oos_trades * 100 if all_oos_trades > 0 else 0

    print(f"  Combined OOS: {all_oos_trades} trades  WR={oos_wr:.1f}%  P&L=${all_oos_pnl:+,.0f}")
    print(f"  Average WFE:  {avg_wfe:.0f}%")
    print()

    if avg_wfe >= 80:
        verdict = "EXCEPTIONAL — minimal curve-fitting. System is very robust."
    elif avg_wfe >= 50:
        verdict = "ROBUST — goldilocks zone. System is tradeable."
    elif avg_wfe >= 35:
        verdict = "BORDERLINE — reduce parameter count or loosen thresholds."
    else:
        verdict = "CURVE-FITTED — do NOT trade live until fixed."

    print(f"  Verdict: {verdict}")
    print("=" * 70)


if __name__ == "__main__":
    run_walk_forward(period="60d")
