"""
Backtest report with deep pattern breakdown.
"""
from __future__ import annotations
from collections import Counter, defaultdict

from rich.console import Console
from rich.table import Table
from rich import box

from backtest.engine import BacktestResult, BacktestTrade
from config import STARTING_BALANCE, TRAILING_MAX_DRAWDOWN, PROFIT_TARGET

console = Console()
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def _wr(trades: list[BacktestTrade]) -> str:
    if not trades:
        return "  -  "
    wins = sum(1 for t in trades if t.pnl > 0)
    pct = wins / len(trades) * 100
    color = "green" if pct >= 50 else "red"
    return f"[{color}]{pct:.0f}%[/{color}] ({wins}/{len(trades)})"


def _avg_pnl(trades: list[BacktestTrade]) -> str:
    if not trades:
        return "  -  "
    avg = sum(t.pnl for t in trades) / len(trades)
    color = "green" if avg > 0 else "red"
    return f"[{color}]{avg:+.0f}[/{color}]"


def analyze(result: BacktestResult) -> dict:
    trades = result.trades
    if not trades:
        console.print("[red]No trades generated in backtest.[/red]")
        return {}

    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    outcomes = Counter(t.outcome for t in trades)

    total_pnl = sum(t.pnl for t in trades)
    avg_win   = sum(t.pnl for t in wins) / len(wins) if wins else 0
    avg_loss  = sum(t.pnl for t in losses) / len(losses) if losses else 0
    win_rate  = len(wins) / len(trades) * 100

    balance = STARTING_BALANCE - 400
    peak    = STARTING_BALANCE
    floor   = STARTING_BALANCE - TRAILING_MAX_DRAWDOWN
    max_dd  = 0.0
    for t in trades:
        balance += t.pnl
        peak = max(peak, balance)
        floor = peak - TRAILING_MAX_DRAWDOWN
        max_dd = max(max_dd, peak - balance)

    daily: dict = defaultdict(list)
    for t in trades:
        daily[t.date].append(t.pnl)

    consistency_violations = 0
    cumulative_profit = 0.0
    for d in sorted(daily.keys()):
        day_pnl = sum(daily[d])
        if cumulative_profit > 0 and day_pnl / cumulative_profit > 0.40:
            consistency_violations += 1
        if day_pnl > 0:
            cumulative_profit += day_pnl

    stats = {
        "total_trades":           len(trades),
        "wins":                   len(wins),
        "losses":                 len(losses),
        "win_rate_pct":           round(win_rate, 1),
        "total_pnl":              round(total_pnl, 2),
        "avg_win":                round(avg_win, 2),
        "avg_loss":               round(avg_loss, 2),
        "best_trade":             round(max((t.pnl for t in trades), default=0), 2),
        "worst_trade":            round(min((t.pnl for t in trades), default=0), 2),
        "max_drawdown_sim":       round(max_dd, 2),
        "would_pass_challenge":   total_pnl >= PROFIT_TARGET,
        "consistency_violations": consistency_violations,
        "outcomes":               dict(outcomes),
        "days_traded":            len(daily),
    }

    _print_report(trades, stats, daily)
    _print_breakdown(trades)
    return stats


def _print_report(trades, stats, daily):
    console.print()
    console.rule("[bold cyan]BACKTEST RESULTS[/bold cyan]")

    pass_fail = (
        "[bold green]YES — Would PASS[/bold green]"
        if stats["would_pass_challenge"]
        else "[bold red]NO — Would FAIL[/bold red]"
    )
    console.print(f"\nTotal P&L: [bold]${stats['total_pnl']:+,.2f}[/bold]    Target: ${PROFIT_TARGET:,}    {pass_fail}")
    console.print(f"Win rate:  [bold]{stats['win_rate_pct']}%[/bold]  ({stats['wins']}W / {stats['losses']}L of {stats['total_trades']} trades over {stats['days_traded']} days)")
    console.print(f"Avg win:   [green]+${stats['avg_win']}[/green]   Avg loss: [red]${stats['avg_loss']}[/red]")
    console.print(f"Max simulated drawdown: [yellow]${stats['max_drawdown_sim']:.2f}[/yellow]   Limit: ${TRAILING_MAX_DRAWDOWN}")
    console.print(f"Consistency violations: {stats['consistency_violations']}   Outcomes: {stats['outcomes']}")
    console.print()

    table = Table(box=box.SIMPLE_HEAD, title="Last 20 Trades")
    for col in ["Date", "Day", "Dir", "Score", "Hour", "Sweep", "Asia W", "P&L", "Outcome", "London", "OB"]:
        table.add_column(col)
    for t in trades[-20:]:
        pnl_c = "green" if t.pnl > 0 else "red"
        table.add_row(
            str(t.date),
            DAYS[t.day_of_week] if t.day_of_week < 5 else "?",
            "[green]L[/green]" if t.direction == "long" else "[red]S[/red]",
            f"{t.score}/7",
            f"{t.signal_hour}h",
            f"{t.sweep_depth:.1f}",
            f"{t.asia_range_width:.0f}",
            f"[{pnl_c}]{t.pnl:+.2f}[/{pnl_c}]",
            t.outcome,
            "",
            "",
        )
    console.print(table)


def _print_breakdown(trades: list[BacktestTrade]):
    console.rule("[bold yellow]PATTERN BREAKDOWN[/bold yellow]")

    # ── By day of week ────────────────────────────────────────────────────────
    dow_tbl = Table(box=box.SIMPLE_HEAD, title="Win Rate by Day of Week")
    dow_tbl.add_column("Day")
    dow_tbl.add_column("Win Rate")
    dow_tbl.add_column("Avg P&L")
    dow_tbl.add_column("Trades")

    by_dow: dict[int, list] = defaultdict(list)
    for t in trades:
        by_dow[t.day_of_week].append(t)
    for d in range(5):
        g = by_dow[d]
        dow_tbl.add_row(DAYS[d], _wr(g), _avg_pnl(g), str(len(g)))
    console.print(dow_tbl)

    # ── By direction ──────────────────────────────────────────────────────────
    dir_tbl = Table(box=box.SIMPLE_HEAD, title="Win Rate by Direction")
    dir_tbl.add_column("Direction")
    dir_tbl.add_column("Win Rate")
    dir_tbl.add_column("Avg P&L")
    dir_tbl.add_column("Trades")
    for d in ("long", "short"):
        g = [t for t in trades if t.direction == d]
        label = "[green]LONG[/green]" if d == "long" else "[red]SHORT[/red]"
        dir_tbl.add_row(label, _wr(g), _avg_pnl(g), str(len(g)))
    console.print(dir_tbl)

    # ── By confluence score ───────────────────────────────────────────────────
    sc_tbl = Table(box=box.SIMPLE_HEAD, title="Win Rate by Confluence Score")
    sc_tbl.add_column("Score")
    sc_tbl.add_column("Win Rate")
    sc_tbl.add_column("Avg P&L")
    sc_tbl.add_column("Trades")
    for s in (3, 4, 5):
        g = [t for t in trades if t.score == s]
        sc_tbl.add_row(f"{s}/5", _wr(g), _avg_pnl(g), str(len(g)))
    console.print(sc_tbl)

    # ── By signal hour ────────────────────────────────────────────────────────
    hr_tbl = Table(box=box.SIMPLE_HEAD, title="Win Rate by Signal Hour")
    hr_tbl.add_column("Hour (EST)")
    hr_tbl.add_column("Win Rate")
    hr_tbl.add_column("Avg P&L")
    hr_tbl.add_column("Trades")
    for h in (9, 10, 11):
        g = [t for t in trades if t.signal_hour == h]
        hr_tbl.add_row(f"{h}:xx AM", _wr(g), _avg_pnl(g), str(len(g)))
    console.print(hr_tbl)

    # ── By sweep depth bucket ─────────────────────────────────────────────────
    sw_tbl = Table(box=box.SIMPLE_HEAD, title="Win Rate by Sweep Depth")
    sw_tbl.add_column("Sweep Depth")
    sw_tbl.add_column("Win Rate")
    sw_tbl.add_column("Avg P&L")
    sw_tbl.add_column("Trades")
    buckets = [(0, 5, "0-5 pts (shallow)"), (5, 15, "5-15 pts"), (15, 30, "15-30 pts"), (30, 80, "30-80 pts (deep)")]
    for lo, hi, label in buckets:
        g = [t for t in trades if lo <= t.sweep_depth < hi]
        sw_tbl.add_row(label, _wr(g), _avg_pnl(g), str(len(g)))
    console.print(sw_tbl)

    # ── By Asia range width ───────────────────────────────────────────────────
    ar_tbl = Table(box=box.SIMPLE_HEAD, title="Win Rate by Asia Range Width")
    ar_tbl.add_column("Range Width")
    ar_tbl.add_column("Win Rate")
    ar_tbl.add_column("Avg P&L")
    ar_tbl.add_column("Trades")
    buckets2 = [(0, 20, "Tight (<20)"), (20, 40, "Normal (20-40)"), (40, 999, "Wide (>40)")]
    for lo, hi, label in buckets2:
        g = [t for t in trades if lo <= t.asia_range_width < hi]
        ar_tbl.add_row(label, _wr(g), _avg_pnl(g), str(len(g)))
    console.print(ar_tbl)

    # ── Summary: worst combinations ───────────────────────────────────────────
    console.rule("[bold red]LOSS CLUSTERS — Rule Candidates[/bold red]")

    combos = []
    for t in trades:
        dow_name = DAYS[t.day_of_week] if t.day_of_week < 5 else "?"
        sweep_bucket = "shallow" if t.sweep_depth < 5 else ("deep" if t.sweep_depth >= 30 else "normal")
        combos.append({
            "dow": dow_name,
            "dir": t.direction,
            "hour": t.signal_hour,
            "sweep": sweep_bucket,
            "score": t.score,
            "won": t.pnl > 0,
            "pnl": t.pnl,
        })

    # Group and rank by win rate (min 2 trades)
    groups: dict[str, list] = defaultdict(list)
    for c in combos:
        groups[f"{c['dow']} {c['dir']}"].append(c)
        groups[f"{c['dir']} @ {c['hour']}h"].append(c)
        groups[f"score={c['score']} {c['dir']}"].append(c)
        groups[f"sweep={c['sweep']} {c['dir']}"].append(c)

    ranked = []
    for label, items in groups.items():
        if len(items) < 2:
            continue
        wr = sum(1 for x in items if x["won"]) / len(items)
        avg = sum(x["pnl"] for x in items) / len(items)
        ranked.append((wr, avg, len(items), label))
    ranked.sort()

    combo_tbl = Table(box=box.SIMPLE_HEAD, title="Worst Combinations (by win rate)")
    combo_tbl.add_column("Combination")
    combo_tbl.add_column("Win Rate")
    combo_tbl.add_column("Avg P&L")
    combo_tbl.add_column("n")
    for wr, avg, n, label in ranked[:10]:
        pct = wr * 100
        color = "green" if pct >= 50 else "red"
        combo_tbl.add_row(
            label,
            f"[{color}]{pct:.0f}%[/{color}]",
            f"[{'green' if avg > 0 else 'red'}]{avg:+.0f}[/{'green' if avg > 0 else 'red'}]",
            str(n),
        )
    console.print(combo_tbl)
