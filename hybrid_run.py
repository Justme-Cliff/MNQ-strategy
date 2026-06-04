"""
Hybrid System Backtest — run with: python3 hybrid_run.py

Runs all three systems and prints a full comparison:
  1. Base quant system (no institutional layer)
  2. Institutional system (8 hard filters)
  3. Hybrid system (confidence scoring → contract size)
"""
from __future__ import annotations
from collections import defaultdict

from backtest.quant_engine  import run_quant_backtest,  QuantTrade
from backtest.inst_engine   import run_inst_backtest,   InstTrade
from backtest.hybrid_engine import run_hybrid_backtest, HybridTrade

PROFIT_TARGET = 1_500
MAX_DRAWDOWN  = 1_000


def _stats(trades: list) -> dict:
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0, "wr": 0.0,
                "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "avg_rr": 0.0,
                "days": 0, "passes": False}
    wins   = [t for t in trades if t.outcome == "WIN"]
    losses = [t for t in trades if t.outcome == "LOSS"]
    total  = len(trades)
    pnl    = sum(t.pnl for t in trades)
    wr     = len(wins) / total * 100

    running = peak = max_dd = 0.0
    for t in trades:
        running += t.pnl
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    return {
        "total":   total,
        "wins":    len(wins),
        "losses":  len(losses),
        "pnl":     pnl,
        "wr":      wr,
        "max_dd":  max_dd,
        "avg_win":  sum(t.pnl for t in wins)   / max(len(wins), 1),
        "avg_loss": sum(t.pnl for t in losses)  / max(len(losses), 1),
        "avg_rr":  sum(t.rr for t in trades)    / total,
        "days":    len(set(t.date for t in trades)),
        "passes":  pnl >= PROFIT_TARGET and max_dd <= MAX_DRAWDOWN,
    }


def _sep(ch: str = "─", w: int = 72) -> str:
    return ch * w


# ── Base results ──────────────────────────────────────────────────────────────

def print_base(trades: list[QuantTrade], s: dict) -> None:
    print(f"\n{_sep('═')}")
    print("  BASE QUANT SYSTEM  (no institutional layer)")
    print(_sep('═'))
    _print_summary(s)
    _print_strategy_breakdown(trades)


# ── Institutional results ─────────────────────────────────────────────────────

def print_inst(trades: list[InstTrade], s: dict, blocks: dict) -> None:
    print(f"\n{_sep('═')}")
    print("  INSTITUTIONAL SYSTEM  (8 hard filters)")
    print(_sep('═'))
    _print_summary(s)
    _print_strategy_breakdown(trades)
    _print_filter_blocks(blocks)


# ── Hybrid results ────────────────────────────────────────────────────────────

def print_hybrid(trades: list[HybridTrade], s: dict, blocks: dict) -> None:
    print(f"\n{_sep('═')}")
    print("  HYBRID SYSTEM  (confidence scoring → contract size)")
    print(_sep('═'))
    _print_summary(s)

    two_lot = [t for t in trades if t.n_contracts == 2]
    one_lot = [t for t in trades if t.n_contracts == 1]
    print(f"\n  Contract sizing:")
    print(f"    1-contract trades: {len(one_lot)}")
    print(f"    2-contract trades: {len(two_lot)}"
          + (f"  ← {sum(t.pnl for t in two_lot):+.0f} P&L from these" if two_lot else ""))

    if two_lot:
        tw = [t for t in two_lot if t.outcome == "WIN"]
        print(f"    2-lot win rate:    {len(tw)}/{len(two_lot)} = "
              f"{len(tw)/len(two_lot)*100:.0f}%")

    _print_strategy_breakdown(trades, show_lots=True)

    # Score distribution (0–20 point system, +1 memory bonus)
    print(f"\n  Confidence score distribution (0-20+memory, skip <=5, 2-lot >=16):")
    score_groups = defaultdict(list)
    for t in trades:
        score_groups[t.score].append(t)
    skipped_label = "  [≤3 = SKIP threshold]"
    for sc in sorted(score_groups.keys(), reverse=True):
        sg = score_groups[sc]
        sw = [t for t in sg if t.outcome == "WIN"]
        n2 = sum(1 for t in sg if t.n_contracts == 2)
        lots_label = f"  {n2}×2-lot" if n2 else ""
        flag = "  ← 2-lot" if sc >= 19 else ""
        print(f"    score {sc:>2}:  {len(sw)}/{len(sg)} WR={len(sw)/len(sg)*100:.0f}%  "
              f"P&L ${sum(t.pnl for t in sg):+.0f}{lots_label}{flag}")

    # Hard blocks
    total_blocks = sum(blocks.values())
    if total_blocks > 0:
        print(f"\n  Hard blocks: {total_blocks} trades skipped")
        for reason, n in blocks.items():
            if n > 0:
                print(f"    {reason}: {n}")

    # Confidence factor hit rates (from score_breakdown dict)
    if trades:
        print(f"\n  Confidence factor hit rates (16-point system):")
        all_factors = set()
        for t in trades:
            bd = getattr(t, "score_breakdown", {})
            all_factors.update(bd.keys())
        for factor in sorted(all_factors):
            pts = [getattr(t, "score_breakdown", {}).get(factor, 0) for t in trades]
            hit = sum(pts)
            print(f"    {factor:<14}  {hit}/{len(trades)} ({hit/len(trades)*100:.0f}%)")

    # Trade log
    print(f"\n  ALL TRADES")
    print(f"  {'Date':<12} {'Day':<4} {'Strategy':<14} {'Dir':<6} "
          f"{'Lots':<5} {'Score':<6} {'StMult':<7} {'HMM':<10} {'P&L':>8} {'Outcome'}")
    print("  " + _sep(w=100))
    for t in trades:
        two   = " ★" if t.n_contracts == 2 else ""
        smult = getattr(t, "stop_mult", 1.0)
        smult_s = f"{smult:.2f}" if smult != 1.0 else "1.00"
        print(f"  {str(t.date):<12} {t.day_name:<4} {t.strategy:<14} "
              f"{t.direction:<6} {t.n_contracts:<5} {t.score:<6} "
              f"{smult_s:<7} {t.hmm_state:<10} "
              f"${t.pnl:>+7.0f}  {t.outcome}{two}")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _print_summary(s: dict) -> None:
    label = "PASS ✓" if s["passes"] else "FAIL ✗"
    print(f"  Total P&L:    ${s['pnl']:+,.2f}    Target: ${PROFIT_TARGET:,}    {label}")
    print(f"  Win rate:     {s['wr']:.1f}%  ({s['wins']}W / {s['losses']}L of "
          f"{s['total']} trades over {s['days']} active days)")
    print(f"  Avg win:      ${s['avg_win']:+.2f}    Avg loss: ${s['avg_loss']:+.2f}    "
          f"Avg RR: {s['avg_rr']:.2f}")
    print(f"  Max drawdown: ${s['max_dd']:.2f}    Limit: ${MAX_DRAWDOWN:,}")


def _print_strategy_breakdown(trades: list, show_lots: bool = False) -> None:
    strats = defaultdict(list)
    for t in trades:
        strats[t.strategy].append(t)
    print(f"\n  Strategy breakdown:")
    all_strats = sorted(set(t.strategy for t in trades))
    for name in ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev",
                 "vwap_pm", "vwap_bounce", "vwap_bounce_pm", "va_rule"] + \
                [s for s in all_strats if s not in {"gap_fill","fvg","orb",
                 "ib_breakout","vwap_rev","vwap_pm","vwap_bounce","vwap_bounce_pm","va_rule"}]:
        if name not in strats:
            continue  # noqa: skip strategies with no trades
        st  = strats[name]
        sw  = [t for t in st if t.outcome == "WIN"]
        swr = len(sw) / len(st) * 100
        spnl = sum(t.pnl for t in st)
        extra = ""
        if show_lots:
            n2 = sum(1 for t in st if getattr(t, "n_contracts", 1) == 2)
            extra = f"  2-lot: {n2}"
        print(f"    {name:<14}  {swr:5.1f}%  ({len(sw)}W/{len(st)-len(sw)}L)  "
              f"P&L: ${spnl:+.0f}{extra}")


def _print_filter_blocks(blocks: dict) -> None:
    total = sum(blocks.values())
    if total:
        print(f"\n  Hard blocks: {total} trades skipped")
        for reason, n in blocks.items():
            if n > 0:
                print(f"    {reason}: {n}")


# ── Three-way comparison ──────────────────────────────────────────────────────

def print_comparison(base_s: dict, inst_s: dict, hyb_s: dict) -> None:
    print(f"\n{_sep('═')}")
    print("  THREE-WAY COMPARISON")
    print(_sep('═'))
    print(f"  {'Metric':<25} {'Base':>12} {'Institutional':>15} {'Hybrid':>10}  {'Hybrid vs Base':>16}")
    print(f"  {_sep(w=82)}")

    rows = [
        ("Total P&L",
            f"${base_s['pnl']:+,.0f}",
            f"${inst_s['pnl']:+,.0f}",
            f"${hyb_s['pnl']:+,.0f}",
            f"${hyb_s['pnl']-base_s['pnl']:+,.0f}"),
        ("Win rate",
            f"{base_s['wr']:.1f}%",
            f"{inst_s['wr']:.1f}%",
            f"{hyb_s['wr']:.1f}%",
            f"{hyb_s['wr']-base_s['wr']:+.1f}%"),
        ("Total trades",
            f"{base_s['total']}",
            f"{inst_s['total']}",
            f"{hyb_s['total']}",
            f"{hyb_s['total']-base_s['total']:+d}"),
        ("Avg win",
            f"${base_s['avg_win']:+.0f}",
            f"${inst_s['avg_win']:+.0f}",
            f"${hyb_s['avg_win']:+.0f}",
            f"${hyb_s['avg_win']-base_s['avg_win']:+.0f}"),
        ("Avg loss",
            f"${base_s['avg_loss']:+.0f}",
            f"${inst_s['avg_loss']:+.0f}",
            f"${hyb_s['avg_loss']:+.0f}",
            f"${hyb_s['avg_loss']-base_s['avg_loss']:+.0f}"),
        ("Avg R:R",
            f"{base_s['avg_rr']:.2f}",
            f"{inst_s['avg_rr']:.2f}",
            f"{hyb_s['avg_rr']:.2f}",
            f"{hyb_s['avg_rr']-base_s['avg_rr']:+.2f}"),
        ("Max drawdown",
            f"${base_s['max_dd']:.0f}",
            f"${inst_s['max_dd']:.0f}",
            f"${hyb_s['max_dd']:.0f}",
            f"${hyb_s['max_dd']-base_s['max_dd']:+.0f}"),
        ("Passes $1,500",
            "YES" if base_s['passes'] else "NO",
            "YES" if inst_s['passes'] else "NO",
            "YES" if hyb_s['passes'] else "NO",
            "—"),
    ]

    for label, bv, iv, hv, delta in rows:
        print(f"  {label:<25} {bv:>12} {iv:>15} {hv:>10}  {delta:>16}")

    print(_sep())


# ── Main ──────────────────────────────────────────────────────────────────────
#
#  Usage:
#    python3 hybrid_run.py          → default 60-day backtest  (~5 sec)
#    python3 hybrid_run.py /60d     → 60-day (yfinance, free)  (~5 sec)
#    python3 hybrid_run.py /6mo     → 6-month (yfinance, free) (~15 sec)
#    python3 hybrid_run.py /1y      → 1-year (yfinance, free)  (~30 sec)
#    python3 hybrid_run.py /2y      → 2-year (Databento cache) (~2 min) ← fast iteration
#    python3 hybrid_run.py /3y      → 3-year (Databento cache) (~3 min)
#    python3 hybrid_run.py /10y     → 10-year (Databento cache) (~4 min after HMM cache warm)
#    python3 hybrid_run.py /10y --refresh  → force re-download from Databento

if __name__ == "__main__":
    import sys

    arg       = next((a for a in sys.argv[1:] if a.startswith("/")), "/60d")
    period    = arg.lstrip("/")              # "60d", "6mo", "1y", "10y"
    refresh   = "--refresh" in sys.argv
    use_db    = period in ("10y", "5y", "3y", "2y")

    print("=" * 72)
    print(f"  ISOGENY ALPHA SYSTEM v7.0  |  {period.upper()} BACKTEST")
    if use_db:
        print(f"  Source: Databento GLBX.MDP3  |  NQ.c.0 continuous")
    else:
        print(f"  Source: yfinance NQ=F  |  5-min bars")
    print("=" * 72)

    if use_db:
        # ── Databento long-period backtest (hybrid only — most meaningful) ────
        from backtest.databento_loader import load_nq_databento
        years = int(period.replace("y", ""))
        df_db = load_nq_databento(years=years, force_refresh=refresh)

        print(f"\nRunning HYBRID system on {years}-year dataset ...")
        hyb_trades = run_hybrid_backtest(df=df_db)
        hyb_s      = _stats(hyb_trades)
        print_hybrid(hyb_trades, hyb_s, run_hybrid_backtest._hard_blocks)

        # Yearly breakdown
        from collections import defaultdict as _dd
        from backtest.run_10yr import _stats as _ys
        by_year = _dd(list)
        for t in hyb_trades:
            by_year[t.date.year].append(t)
        regime_notes = {
            2016:"election vol", 2017:"ultra-low VIX bull", 2018:"Dec crash",
            2019:"bull recovery", 2020:"COVID crash+recovery", 2021:"meme bull",
            2022:"rate hike bear", 2023:"AI bull begins", 2024:"AI momentum",
            2025:"tariff shock", 2026:"current year",
        }
        print(f"\n  YEARLY BREAKDOWN")
        print(f"  {'Year':<6} {'Trades':>7} {'WR':>7} {'P&L':>10} {'MaxDD':>8}  Notes")
        print(f"  {'─'*65}")
        all_pnl = []
        for yr in sorted(by_year):
            yt = by_year[yr]; ys = _ys(yt)
            all_pnl.append(ys["pnl"])
            note = regime_notes.get(yr, "")
            print(f"  {yr:<6} {ys['total']:>7}  {ys['wr']:>5.1f}%  "
                  f"${ys['pnl']:>+9,.0f}  ${ys['max_dd']:>7,.0f}  {note}")
        if all_pnl:
            pos = sum(1 for p in all_pnl if p > 0)
            print(f"\n  Positive years: {pos}/{len(all_pnl)} "
                  f"({pos/len(all_pnl)*100:.0f}%)  "
                  f"Avg/year: ${sum(all_pnl)/len(all_pnl):+,.0f}")

        # Generate charts
        from backtest.quant_charts import generate_all_charts
        print("\nGenerating charts ...")
        generate_all_charts(hyb_trades)

    else:
        # ── Standard yfinance three-way comparison ────────────────────────────
        print(f"\n[1/3] Running BASE system ...")
        base_trades = run_quant_backtest(interval="5m", period=period)
        base_s = _stats(base_trades)
        print_base(base_trades, base_s)

        print(f"\n[2/3] Running INSTITUTIONAL system ...")
        inst_trades = run_inst_backtest(interval="5m", period=period)
        inst_s = _stats(inst_trades)
        print_inst(inst_trades, inst_s, run_inst_backtest._rejections)

        print(f"\n[3/3] Running HYBRID system ...")
        hyb_trades = run_hybrid_backtest(interval="5m", period=period)
        hyb_s = _stats(hyb_trades)
        print_hybrid(hyb_trades, hyb_s, run_hybrid_backtest._hard_blocks)

        print_comparison(base_s, inst_s, hyb_s)

        # Generate charts
        from backtest.quant_charts import generate_all_charts
        print("\nGenerating charts ...")
        generate_all_charts(hyb_trades)

        print(f"\nDone.")
        print(f"  Base: {len(base_trades)} trades  |  "
              f"Institutional: {len(inst_trades)} trades  |  "
              f"Hybrid: {len(hyb_trades)} trades")
