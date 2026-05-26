"""
Quantitative Strategy Backtest — run with: python3 quant_run.py

Strategies:
  1. Gap Fill       — tiny overnight gaps, 93.1% documented WR
  2. ORB            — opening range breakout, 72-74% WR
  3. IB Breakout    — initial balance breakout + shallow retracement, 92% WR
  4. VWAP Reversion — 2σ deviation reversion, 66-67% WR (VIX < 22 only)
"""
from __future__ import annotations
from collections import defaultdict
from backtest.quant_engine import run_quant_backtest, QuantTrade
from strategy.bot_memory import log_trade, print_status, get_sizing, is_paused

PROFIT_TARGET = 1_500
MAX_DRAWDOWN  = 1_000
MNQ_PER_POINT = 2.0


def analyze(trades: list[QuantTrade]) -> None:
    if not trades:
        print("No trades found.")
        return

    wins   = [t for t in trades if t.outcome == "WIN"]
    losses = [t for t in trades if t.outcome == "LOSS"]
    total  = len(trades)
    wr     = len(wins) / total * 100

    total_pnl   = sum(t.pnl for t in trades)
    avg_win     = sum(t.pnl for t in wins)  / max(len(wins), 1)
    avg_loss    = sum(t.pnl for t in losses) / max(len(losses), 1)
    avg_rr      = sum(t.rr for t in trades) / total

    # Max drawdown
    running = 0.0
    peak    = 0.0
    max_dd  = 0.0
    for t in trades:
        running += t.pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    passes = total_pnl >= PROFIT_TARGET and max_dd <= MAX_DRAWDOWN
    days_with_trades = len(set(t.date for t in trades))

    print("\n" + "─" * 70)
    print("  QUANT SYSTEM BACKTEST RESULTS")
    print("─" * 70)
    print(f"  Total P&L:   ${total_pnl:+,.2f}    Target: ${PROFIT_TARGET:,}    {'YES — PASS ✓' if passes else 'NO — FAIL ✗'}")
    print(f"  Win rate:    {wr:.1f}%  ({len(wins)}W / {len(losses)}L of {total} trades over {days_with_trades} active days)")
    print(f"  Avg win:     ${avg_win:+.2f}    Avg loss: ${avg_loss:+.2f}    Avg RR: {avg_rr:.2f}")
    print(f"  Max drawdown: ${max_dd:.2f}    Limit: ${MAX_DRAWDOWN:,}")
    print("─" * 70)

    # ── Strategy breakdown ────────────────────────────────────────────────────
    print("\n  WIN RATE BY STRATEGY")
    strats = defaultdict(list)
    for t in trades:
        strats[t.strategy].append(t)

    strategy_order = ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev", "vwap_pm", "vwap_bounce", "vwap_bounce_pm"]
    strategy_names = {
        "gap_fill":       "Gap Fill       (tiny gap + premarket bias)",
        "fvg":            "FVG            (fair value gap fill)",
        "orb":            "ORB            (pullback entry on 5-min opening range)",
        "ib_breakout":    "IB Breakout    (initial balance + C-period)",
        "vwap_rev":       "VWAP Rev AM    (1.5s reversion 9:45-11:30)",
        "vwap_pm":        "VWAP Rev PM    (1.5s reversion 1:30-3:30)",
        "vwap_bounce":    "VWAP Bounce AM (trend continuation at VWAP 10:00-11:30)",
        "vwap_bounce_pm": "VWAP Bounce PM (trend continuation at VWAP 1:30-3:30)",
    }
    for s in strategy_order:
        if s not in strats:
            continue
        st = strats[s]
        sw = [t for t in st if t.outcome == "WIN"]
        sl = [t for t in st if t.outcome == "LOSS"]
        swr = len(sw) / len(st) * 100
        spnl = sum(t.pnl for t in st)
        avg_w = sum(t.pnl for t in sw) / max(len(sw), 1)
        avg_l = sum(t.pnl for t in sl) / max(len(sl), 1)
        print(f"  {strategy_names.get(s, s):<48}  {swr:5.1f}%  ({len(sw)}W/{len(sl)}L)  P&L: ${spnl:+.0f}  avg_win=${avg_w:+.0f}  avg_loss=${avg_l:+.0f}")

    # ── Day of week ───────────────────────────────────────────────────────────
    print("\n  WIN RATE BY DAY")
    dow_groups = defaultdict(list)
    for t in trades:
        dow_groups[t.day_name].append(t)
    for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        if d not in dow_groups:
            continue
        dg = dow_groups[d]
        dw = [t for t in dg if t.outcome == "WIN"]
        dpnl = sum(t.pnl for t in dg)
        print(f"  {d}   {len(dw)}/{len(dg)} = {len(dw)/len(dg)*100:.0f}%   P&L ${dpnl:+.0f}")

    # ── Direction breakdown ───────────────────────────────────────────────────
    print("\n  WIN RATE BY DIRECTION")
    for d in ["long", "short"]:
        dg = [t for t in trades if t.direction == d]
        if not dg:
            continue
        dw = [t for t in dg if t.outcome == "WIN"]
        dpnl = sum(t.pnl for t in dg)
        print(f"  {d.upper():<6}  {len(dw)}/{len(dg)} = {len(dw)/len(dg)*100:.0f}%   P&L ${dpnl:+.0f}")

    # ── Regime breakdown ─────────────────────────────────────────────────────
    print("\n  WIN RATE BY VIX REGIME")
    reg_groups = defaultdict(list)
    for t in trades:
        reg_groups[t.regime].append(t)
    for r in ["low", "normal", "elevated", "high"]:
        if r not in reg_groups:
            continue
        rg = reg_groups[r]
        rw = [t for t in rg if t.outcome == "WIN"]
        rpnl = sum(t.pnl for t in rg)
        avg_vix = sum(t.vix for t in rg) / len(rg)
        print(f"  {r:<10}  {len(rw)}/{len(rg)} = {len(rw)/len(rg)*100:.0f}%   avg VIX={avg_vix:.1f}   P&L ${rpnl:+.0f}")

    # ── Last 20 trades ────────────────────────────────────────────────────────
    print("\n  LAST 20 TRADES")
    print(f"  {'Date':<12} {'Day':<4} {'Strategy':<12} {'Dir':<6} {'Trend':<12} {'Entry':>8} {'Stop':>8} {'Target':>8} {'P&L':>8} {'RR':>5} {'Outcome'}")
    print("  " + "─" * 100)
    for t in trades[-20:]:
        print(f"  {str(t.date):<12} {t.day_name:<4} {t.strategy:<12} {t.direction:<6} "
              f"{getattr(t,'trend_dir',''):<12} "
              f"{t.entry:>8.1f} {t.stop:>8.1f} {t.target:>8.1f} "
              f"${t.pnl:>+7.0f} {t.rr:>5.2f}  {t.outcome}")
    print("─" * 70)

    # ── Comparison vs ICT system ─────────────────────────────────────────────
    print(f"\n  COMPARISON vs ICT SYSTEM (same 60-day window)")
    print(f"  {'Metric':<25} {'ICT System':>15} {'Quant System':>15}")
    print(f"  {'─'*55}")
    print(f"  {'Win rate':<25} {'~50%':>15} {wr:>14.1f}%")
    print(f"  {'Total P&L':<25} {'~$2,091':>15} ${total_pnl:>+13,.0f}")
    print(f"  {'Total trades':<25} {'30':>15} {total:>15}")
    print(f"  {'Avg trades/day':<25} {'0.86':>15} {total/max(days_with_trades,1):>14.2f}")
    print(f"  {'Passes $1,500 target':<25} {'YES':>15} {'YES' if passes else 'NO':>15}")


if __name__ == "__main__":
    print("=" * 70)
    print("  QUANT SYSTEM  |  5-minute bars  |  60-day backtest")
    print("  Strategies: Gap Fill · ORB · IB Breakout · VWAP Reversion")
    print("=" * 70)

    # Show bot memory status before running
    print_status()

    paused, reason = is_paused()
    if paused:
        print(f"\n  ⚠  Bot is paused today: {reason}")
        print("  To override, edit journal/bot_memory.json and set 'paused' to false.\n")

    contracts = get_sizing()
    if contracts > 1:
        print(f"\n  ✓ Bot memory: running {contracts} contracts (hot streak)\n")

    trades = run_quant_backtest(interval="5m", period="60d")
    analyze(trades)

    # Log all backtest trades into memory so the bot learns from them
    for t in trades:
        log_trade(
            strategy=t.strategy,
            direction=t.direction,
            entry=t.entry,
            stop=t.stop,
            target=t.target,
            outcome=t.outcome,
            pnl=t.pnl,
            contracts=contracts,
            vix=getattr(t, "vix", 0.0),
            atr=0.0,
            trend=getattr(t, "trend_dir", ""),
            day_name=getattr(t, "day_name", ""),
        )

    print(f"\nDone. {len(trades)} trades logged to bot memory.")
    print_status()
