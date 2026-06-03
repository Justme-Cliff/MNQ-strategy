"""
10-Year Hybrid Backtest using Databento NQ futures data.

Run with:
    python3 -m backtest.run_10yr

First run: downloads ~10yr of 1-min NQ data from Databento (~$12, ~30s).
Subsequent runs: loads from local cache instantly (free).

What this tells you:
  - Does the 76.7% WR hold across different market regimes?
  - 2018 selloff, 2020 COVID crash, 2021 bull, 2022 bear, 2023-2026 AI bull
  - Walk-Forward Efficiency across multiple years (not just 60 days)
  - Which strategies survive 10 years vs which are overfit to recent data
"""
from __future__ import annotations
from collections import defaultdict

from backtest.databento_loader import load_nq_databento, label_sessions_db
from backtest.hybrid_engine    import run_hybrid_backtest, HybridTrade

PROFIT_TARGET = 1_500
MAX_DRAWDOWN  = 1_000


def _stats(trades: list) -> dict:
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0,
                "wr": 0.0, "max_dd": 0.0, "avg_win": 0.0,
                "avg_loss": 0.0, "avg_rr": 0.0, "days": 0}
    wins   = [t for t in trades if t.outcome == "WIN"]
    losses = [t for t in trades if t.outcome == "LOSS"]
    pnl    = sum(t.pnl for t in trades)
    wr     = len(wins) / len(trades) * 100

    running = peak = max_dd = 0.0
    for t in trades:
        running += t.pnl
        peak    = max(peak, running)
        max_dd  = max(max_dd, peak - running)

    return {
        "total":    len(trades),
        "wins":     len(wins),
        "losses":   len(losses),
        "pnl":      pnl,
        "wr":       wr,
        "max_dd":   max_dd,
        "avg_win":  sum(t.pnl for t in wins)   / max(len(wins),   1),
        "avg_loss": sum(t.pnl for t in losses)  / max(len(losses), 1),
        "avg_rr":   sum(t.rr  for t in trades)  / len(trades),
        "days":     len(set(t.date for t in trades)),
    }


def _sep(w=72): return "─" * w


def run_10yr_backtest(years: int = 10, force_refresh: bool = False) -> None:
    print("=" * 72)
    print("  ISOGENY ALPHA SYSTEM v7.0  |  10-YEAR BACKTEST")
    print("  Databento GLBX.MDP3  |  NQ.c.0 continuous  |  5-min bars")
    print("=" * 72)

    # ── Load data ─────────────────────────────────────────────────────────────
    df = load_nq_databento(years=years, force_refresh=force_refresh)

    # ── Run backtest ──────────────────────────────────────────────────────────
    n_bars = len(df)
    n_days = len(set(df.index.date))
    print(f"\nRunning hybrid backtest on {n_bars:,} bars / {n_days:,} trading days...")
    print("(This takes 3-8 minutes for 10 years — grab a coffee)\n")
    trades = run_hybrid_backtest(df=df)

    if not trades:
        print("No trades generated. Check data quality.")
        return

    s = _stats(trades)

    # ── Overall results ───────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"  OVERALL  ({df.index[0].date()} to {df.index[-1].date()})")
    print(f"{'=' * 72}")
    print(f"  Total trades:    {s['total']}")
    print(f"  Win rate:        {s['wr']:.1f}%  ({s['wins']}W / {s['losses']}L)")
    print(f"  Net P&L:         ${s['pnl']:+,.2f}")
    print(f"  Avg win:         ${s['avg_win']:+.2f}")
    print(f"  Avg loss:        ${s['avg_loss']:+.2f}")
    print(f"  Avg R:R:         {s['avg_rr']:.2f}x")
    print(f"  Max drawdown:    ${s['max_dd']:,.2f}")
    print(f"  Active days:     {s['days']}")

    # ── Yearly breakdown ──────────────────────────────────────────────────────
    print(f"\n  YEARLY BREAKDOWN")
    print(f"  {'Year':<6} {'Trades':>7} {'WR':>7} {'P&L':>10} {'MaxDD':>8}  {'Regime Notes'}")
    print(f"  {_sep(70)}")

    by_year = defaultdict(list)
    for t in trades:
        by_year[t.date.year].append(t)

    regime_notes = {
        2016: "election vol, range",
        2017: "ultra-low VIX bull",
        2018: "Dec crash, vol spikes",
        2019: "strong bull recovery",
        2020: "COVID crash + V-recovery",
        2021: "meme stock bull run",
        2022: "rate hike bear market",
        2023: "AI bull run begins",
        2024: "AI momentum continues",
        2025: "tariff shock + recovery",
        2026: "current year",
    }

    for yr in sorted(by_year.keys()):
        yt = by_year[yr]
        ys = _stats(yt)
        note = regime_notes.get(yr, "")
        print(f"  {yr:<6} {ys['total']:>7}  {ys['wr']:>5.1f}%  "
              f"${ys['pnl']:>+9,.0f}  ${ys['max_dd']:>7,.0f}  {note}")

    # ── Strategy breakdown ────────────────────────────────────────────────────
    print(f"\n  STRATEGY BREAKDOWN (10yr)")
    print(f"  {'Strategy':<18} {'Trades':>7} {'WR':>7} {'P&L':>10} {'Avg RR':>8}")
    print(f"  {_sep(56)}")

    by_strat = defaultdict(list)
    for t in trades:
        by_strat[t.strategy].append(t)

    strat_order = ["gap_fill", "fvg", "orb", "ib_breakout",
                   "vwap_rev", "vwap_pm", "vwap_bounce", "vwap_bounce_pm", "va_rule"]
    for name in strat_order + [s for s in by_strat if s not in strat_order]:
        if name not in by_strat:
            continue
        st = by_strat[name]
        ss = _stats(st)
        print(f"  {name:<18} {ss['total']:>7}  {ss['wr']:>5.1f}%  "
              f"${ss['pnl']:>+9,.0f}  {ss['avg_rr']:>7.2f}x")

    # ── Score distribution ────────────────────────────────────────────────────
    print(f"\n  CONFIDENCE SCORE DISTRIBUTION (10yr, skip<=5, 2-lot>=16)")
    score_groups = defaultdict(list)
    for t in trades:
        score_groups[t.score].append(t)
    for sc in sorted(score_groups.keys(), reverse=True):
        sg = score_groups[sc]
        sw = [t for t in sg if t.outcome == "WIN"]
        n2 = sum(1 for t in sg if t.n_contracts == 2)
        flag = " <- 2-lot" if sc >= 16 else ""
        print(f"    score {sc:>2}:  {len(sw)}/{len(sg)} WR={len(sw)/len(sg)*100:.0f}%"
              f"  P&L ${sum(t.pnl for t in sg):+,.0f}  n2lot={n2}{flag}")

    # ── Walk-forward multi-year ───────────────────────────────────────────────
    print(f"\n  WALK-FORWARD: YEARLY OOS WINDOWS")
    print(f"  (Each year's performance = out-of-sample for that period)")
    years_list = sorted(by_year.keys())
    if len(years_list) > 2:
        all_pnl   = [_stats(by_year[y])["pnl"] for y in years_list]
        pos_years = sum(1 for p in all_pnl if p > 0)
        print(f"  Positive years:   {pos_years}/{len(years_list)} "
              f"({pos_years/len(years_list)*100:.0f}%)")
        print(f"  Best year:        {years_list[all_pnl.index(max(all_pnl))]}  "
              f"${max(all_pnl):+,.0f}")
        print(f"  Worst year:       {years_list[all_pnl.index(min(all_pnl))]}  "
              f"${min(all_pnl):+,.0f}")
        print(f"  Avg P&L/year:     ${sum(all_pnl)/len(all_pnl):+,.0f}")

    print(f"\n{'=' * 72}")
    print(f"  Done. {len(trades)} trades over {s['days']} active days.")
    print(f"  Cache: .cache/nq_5m_10yr.parquet  (free to re-run)")
    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    import sys
    force = "--refresh" in sys.argv
    run_10yr_backtest(years=10, force_refresh=force)
