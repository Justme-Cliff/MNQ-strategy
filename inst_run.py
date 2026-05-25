"""
Institutional Quant System Backtest — run with: python3 inst_run.py

Runs BOTH the base quant system AND the 8-layer institutional system,
then prints a side-by-side comparison + full institutional analysis.
"""
from __future__ import annotations
from collections import defaultdict

from backtest.quant_engine import run_quant_backtest, QuantTrade
from backtest.inst_engine  import run_inst_backtest, InstTrade

PROFIT_TARGET = 1_500
MAX_DRAWDOWN  = 1_000


# ── Shared analysis helpers ───────────────────────────────────────────────────

def _stats(trades: list) -> dict:
    if not trades:
        return {}
    wins   = [t for t in trades if t.outcome == "WIN"]
    losses = [t for t in trades if t.outcome == "LOSS"]
    total  = len(trades)
    pnl    = sum(t.pnl for t in trades)
    wr     = len(wins) / total * 100

    running = peak = max_dd = 0.0
    for t in trades:
        running += t.pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    avg_win  = sum(t.pnl for t in wins)  / max(len(wins), 1)
    avg_loss = sum(t.pnl for t in losses) / max(len(losses), 1)
    avg_rr   = sum(t.rr for t in trades) / total
    days     = len(set(t.date for t in trades))

    return {
        "total": total, "wins": len(wins), "losses": len(losses),
        "pnl": pnl, "wr": wr, "max_dd": max_dd,
        "avg_win": avg_win, "avg_loss": avg_loss, "avg_rr": avg_rr,
        "days": days,
        "passes": pnl >= PROFIT_TARGET and max_dd <= MAX_DRAWDOWN,
    }


def _sep(char: str = "─", w: int = 72) -> str:
    return char * w


# ── Base system analysis ──────────────────────────────────────────────────────

def print_base_results(trades: list[QuantTrade], s: dict) -> None:
    print(f"\n{_sep('═')}")
    print("  BASE QUANT SYSTEM (no institutional filters)")
    print(_sep('═'))
    print(f"  Total P&L:    ${s['pnl']:+,.2f}    Target: ${PROFIT_TARGET:,}    "
          f"{'PASS ✓' if s['passes'] else 'FAIL ✗'}")
    print(f"  Win rate:     {s['wr']:.1f}%  ({s['wins']}W / {s['losses']}L of "
          f"{s['total']} trades over {s['days']} active days)")
    print(f"  Avg win:      ${s['avg_win']:+.2f}    Avg loss: ${s['avg_loss']:+.2f}    Avg RR: {s['avg_rr']:.2f}")
    print(f"  Max drawdown: ${s['max_dd']:.2f}    Limit: ${MAX_DRAWDOWN:,}")

    strats = defaultdict(list)
    for t in trades:
        strats[t.strategy].append(t)

    print(f"\n  Strategy breakdown:")
    for s_name in ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev"]:
        if s_name not in strats:
            continue
        st  = strats[s_name]
        sw  = [t for t in st if t.outcome == "WIN"]
        swr = len(sw) / len(st) * 100
        spnl = sum(t.pnl for t in st)
        print(f"    {s_name:<14}  {swr:5.1f}%  ({len(sw)}W/{len(st)-len(sw)}L)  P&L: ${spnl:+.0f}")


# ── Institutional system analysis ────────────────────────────────────────────

def print_inst_results(trades: list[InstTrade], s: dict, rejections: dict) -> None:
    print(f"\n{_sep('═')}")
    print("  INSTITUTIONAL SYSTEM (8-layer filter pipeline)")
    print(_sep('═'))
    print(f"  Total P&L:    ${s['pnl']:+,.2f}    Target: ${PROFIT_TARGET:,}    "
          f"{'PASS ✓' if s['passes'] else 'FAIL ✗'}")
    print(f"  Win rate:     {s['wr']:.1f}%  ({s['wins']}W / {s['losses']}L of "
          f"{s['total']} trades over {s['days']} active days)")
    print(f"  Avg win:      ${s['avg_win']:+.2f}    Avg loss: ${s['avg_loss']:+.2f}    Avg RR: {s['avg_rr']:.2f}")
    print(f"  Max drawdown: ${s['max_dd']:.2f}    Limit: ${MAX_DRAWDOWN:,}")

    # Kelly sizing breakdown
    if trades:
        two_contract = [t for t in trades if t.n_contracts == 2]
        one_contract = [t for t in trades if t.n_contracts == 1]
        print(f"\n  Kelly sizing:  1-contract: {len(one_contract)} trades  |  "
              f"2-contract: {len(two_contract)} trades")

    # HMM state breakdown
    if trades:
        state_groups = defaultdict(list)
        for t in trades:
            state_groups[t.hmm_state].append(t)
        print(f"\n  HMM state distribution:")
        for state in ["bull", "volatile", "bear", "unavailable"]:
            if state not in state_groups:
                continue
            sg = state_groups[state]
            sw = [t for t in sg if t.outcome == "WIN"]
            print(f"    {state:<12}  {len(sw)}/{len(sg)} = "
                  f"{len(sw)/len(sg)*100:.0f}%   P&L ${sum(t.pnl for t in sg):+.0f}")

    # HAR-RV regime breakdown
    if trades:
        harv_groups = defaultdict(list)
        for t in trades:
            harv_groups[t.har_regime].append(t)
        print(f"\n  HAR-RV vol regime:")
        for r in ["low", "normal", "high"]:
            if r not in harv_groups:
                continue
            rg = harv_groups[r]
            rw = [t for t in rg if t.outcome == "WIN"]
            print(f"    {r:<8}  {len(rw)}/{len(rg)} = "
                  f"{len(rw)/len(rg)*100:.0f}%   P&L ${sum(t.pnl for t in rg):+.0f}")

    # Strategy breakdown
    strats = defaultdict(list)
    for t in trades:
        strats[t.strategy].append(t)
    print(f"\n  Strategy breakdown:")
    for s_name in ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev"]:
        if s_name not in strats:
            continue
        st   = strats[s_name]
        sw   = [t for t in st if t.outcome == "WIN"]
        swr  = len(sw) / len(st) * 100
        spnl = sum(t.pnl for t in st)
        avg2 = sum(1 for t in st if t.n_contracts == 2)
        print(f"    {s_name:<14}  {swr:5.1f}%  ({len(sw)}W/{len(st)-len(sw)}L)  "
              f"P&L: ${spnl:+.0f}  (2-lot: {avg2})")

    # Filter rejection breakdown
    total_rej = sum(rejections.values())
    if total_rej > 0:
        print(f"\n  Filter rejection breakdown (trades blocked):")
        labels = {
            "hmm_bear":    "HMM bear state (skip day)",
            "harv_extreme":"HAR-RV extreme vol (skip day)",
            "gex_mismatch":"GEX bias mismatch",
            "tsmom":       "TSMOM momentum opposition",
            "bns_jump":    "BNS jump detected",
            "vpin":        "VPIN informed flow (mean-rev)",
            "ofi":         "OFI opposing z-score",
            "es_leadlag":  "ES lead-lag disagreement",
            "risk_too_wide":"HAR-RV stop too wide",
        }
        for key, label in labels.items():
            n = rejections.get(key, 0)
            if n > 0:
                print(f"    {label:<38}  {n:3d} rejections")

    # GEX bias breakdown
    if trades:
        gex_groups = defaultdict(list)
        for t in trades:
            gex_groups[t.gex_bias].append(t)
        print(f"\n  GEX bias environment:")
        for bias in ["breakout", "neutral", "mean_rev"]:
            if bias not in gex_groups:
                continue
            gg = gex_groups[bias]
            gw = [t for t in gg if t.outcome == "WIN"]
            print(f"    {bias:<10}  {len(gw)}/{len(gg)} = "
                  f"{len(gw)/len(gg)*100:.0f}%   P&L ${sum(t.pnl for t in gg):+.0f}")

    # Last 15 trades
    print(f"\n  LAST 15 TRADES")
    print(f"  {'Date':<12} {'Day':<4} {'Strategy':<12} {'Dir':<6} {'Lots':<5} "
          f"{'HMM':<10} {'GEX':<9} {'HAR':<8} {'P&L':>8} {'Outcome'}")
    print("  " + _sep(w=100))
    for t in trades[-15:]:
        print(f"  {str(t.date):<12} {t.day_name:<4} {t.strategy:<12} "
              f"{t.direction:<6} {t.n_contracts:<5} "
              f"{t.hmm_state:<10} {t.gex_bias:<9} {t.har_regime:<8} "
              f"${t.pnl:>+7.0f}  {t.outcome}")


# ── Side-by-side comparison ───────────────────────────────────────────────────

def print_comparison(base_s: dict, inst_s: dict) -> None:
    print(f"\n{_sep('═')}")
    print("  SIDE-BY-SIDE COMPARISON")
    print(_sep('═'))
    print(f"  {'Metric':<28} {'Base Quant':>14} {'Institutional':>14}  {'Delta':>10}")
    print(f"  {_sep(w=68)}")

    rows = [
        ("Total P&L",      f"${base_s['pnl']:+,.0f}",    f"${inst_s['pnl']:+,.0f}",    f"${inst_s['pnl']-base_s['pnl']:+,.0f}"),
        ("Win rate",        f"{base_s['wr']:.1f}%",        f"{inst_s['wr']:.1f}%",        f"{inst_s['wr']-base_s['wr']:+.1f}%"),
        ("Total trades",    f"{base_s['total']}",          f"{inst_s['total']}",          f"{inst_s['total']-base_s['total']:+d}"),
        ("Avg win",         f"${base_s['avg_win']:+.0f}",  f"${inst_s['avg_win']:+.0f}",  f"${inst_s['avg_win']-base_s['avg_win']:+.0f}"),
        ("Avg loss",        f"${base_s['avg_loss']:+.0f}", f"${inst_s['avg_loss']:+.0f}", f"${inst_s['avg_loss']-base_s['avg_loss']:+.0f}"),
        ("Avg R:R",         f"{base_s['avg_rr']:.2f}",     f"{inst_s['avg_rr']:.2f}",     f"{inst_s['avg_rr']-base_s['avg_rr']:+.2f}"),
        ("Max drawdown",    f"${base_s['max_dd']:.0f}",    f"${inst_s['max_dd']:.0f}",    f"${inst_s['max_dd']-base_s['max_dd']:+.0f}"),
        ("Active days",     f"{base_s['days']}",           f"{inst_s['days']}",           "—"),
        ("Passes eval",     "YES" if base_s['passes'] else "NO",
                            "YES" if inst_s['passes'] else "NO",  "—"),
    ]

    for label, bval, ival, delta in rows:
        print(f"  {label:<28} {bval:>14} {ival:>14}  {delta:>10}")

    print(_sep())


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 72)
    print("  INSTITUTIONAL NQ QUANT SYSTEM  |  5m bars  |  60d backtest")
    print("  Filters: HMM · HAR-RV · GEX · TSMOM · BNS · VPIN · OFI · ES Lead-Lag")
    print("=" * 72)

    # Run base quant system first for comparison
    print("\n[BASE] Running base quant system ...")
    base_trades = run_quant_backtest(interval="5m", period="60d")
    base_s = _stats(base_trades)
    print_base_results(base_trades, base_s)

    # Run institutional system
    print(f"\n[INST] Running institutional system ...")
    inst_trades = run_inst_backtest(interval="5m", period="60d")
    inst_s = _stats(inst_trades)
    rejections = run_inst_backtest._rejections
    print_inst_results(inst_trades, inst_s, rejections)

    # Side-by-side
    print_comparison(base_s, inst_s)

    print(f"\nDone. Base: {len(base_trades)} trades | Institutional: {len(inst_trades)} trades")
