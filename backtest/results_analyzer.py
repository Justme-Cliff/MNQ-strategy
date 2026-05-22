"""
Print a full backtest report to the terminal.
"""
from __future__ import annotations
from collections import Counter

from rich.console import Console
from rich.table import Table
from rich import box

from backtest.engine import BacktestResult, BacktestTrade
from config import STARTING_BALANCE, TRAILING_MAX_DRAWDOWN, PROFIT_TARGET

console = Console()


def analyze(result: BacktestResult) -> dict:
    trades = result.trades
    if not trades:
        console.print("[red]No trades generated in backtest.[/red]")
        return {}

    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    outcomes = Counter(t.outcome for t in trades)

    total_pnl   = sum(t.pnl for t in trades)
    avg_win     = sum(t.pnl for t in wins) / len(wins) if wins else 0
    avg_loss    = sum(t.pnl for t in losses) / len(losses) if losses else 0
    win_rate    = len(wins) / len(trades) * 100

    # Max drawdown simulation
    balance = STARTING_BALANCE - 400
    peak    = STARTING_BALANCE
    floor   = STARTING_BALANCE - TRAILING_MAX_DRAWDOWN
    max_dd  = 0.0
    for t in trades:
        balance += t.pnl
        peak = max(peak, balance)
        floor = peak - TRAILING_MAX_DRAWDOWN
        dd = peak - balance
        max_dd = max(max_dd, dd)

    # Consistency check — no single day > 40%
    daily = {}
    for t in trades:
        daily.setdefault(t.date, []).append(t.pnl)
    consistency_violations = 0
    cumulative_profit = 0.0
    for d in sorted(daily.keys()):
        day_pnl = sum(daily[d])
        if cumulative_profit > 0 and day_pnl / cumulative_profit > 0.40:
            consistency_violations += 1
        if day_pnl > 0:
            cumulative_profit += day_pnl

    stats = {
        "total_trades":             len(trades),
        "wins":                     len(wins),
        "losses":                   len(losses),
        "win_rate_pct":             round(win_rate, 1),
        "total_pnl":                round(total_pnl, 2),
        "avg_win":                  round(avg_win, 2),
        "avg_loss":                 round(avg_loss, 2),
        "best_trade":               round(max((t.pnl for t in trades), default=0), 2),
        "worst_trade":              round(min((t.pnl for t in trades), default=0), 2),
        "max_drawdown_sim":         round(max_dd, 2),
        "would_pass_challenge":     total_pnl >= PROFIT_TARGET,
        "consistency_violations":   consistency_violations,
        "outcomes":                 dict(outcomes),
        "days_traded":              len(daily),
    }

    _print_report(trades, stats, daily)
    return stats


def _print_report(trades: list[BacktestTrade], stats: dict, daily: dict) -> None:
    console.print()
    console.rule("[bold cyan]BACKTEST RESULTS — Enhanced TJR on MNQ[/bold cyan]")

    # Summary panel
    pass_fail = "[bold green]YES — Would PASS challenge[/bold green]" if stats["would_pass_challenge"] else "[bold red]NO — Would FAIL challenge[/bold red]"
    console.print(f"\nTotal P&L: [bold]${stats['total_pnl']:+,.2f}[/bold]    Target: ${PROFIT_TARGET:,}    {pass_fail}")
    console.print(f"Win rate:  [bold]{stats['win_rate_pct']}%[/bold]  ({stats['wins']}W / {stats['losses']}L of {stats['total_trades']} trades over {stats['days_traded']} days)")
    console.print(f"Avg win:   [green]+${stats['avg_win']}[/green]   Avg loss: [red]${stats['avg_loss']}[/red]")
    console.print(f"Max simulated drawdown: [yellow]${stats['max_drawdown_sim']:.2f}[/yellow]   Limit: ${TRAILING_MAX_DRAWDOWN}")
    console.print(f"Consistency violations: [{'red' if stats['consistency_violations'] > 0 else 'green'}]{stats['consistency_violations']}[/{'red' if stats['consistency_violations'] > 0 else 'green'}]")
    console.print(f"Outcomes: {stats['outcomes']}")
    console.print()

    # Last 20 trades table
    table = Table(box=box.SIMPLE_HEAD, title="Last 20 Trades")
    table.add_column("Date")
    table.add_column("Dir")
    table.add_column("Entry")
    table.add_column("Stop")
    table.add_column("TP2")
    table.add_column("Exit")
    table.add_column("P&L")
    table.add_column("Score")
    table.add_column("Outcome")

    for t in trades[-20:]:
        pnl_color = "green" if t.pnl > 0 else "red"
        table.add_row(
            str(t.date),
            "[green]LONG[/green]" if t.direction == "long" else "[red]SHORT[/red]",
            f"{t.entry:.2f}",
            f"{t.stop:.2f}",
            f"{t.tp2:.2f}",
            f"{t.exit_price:.2f}",
            f"[{pnl_color}]{t.pnl:+.2f}[/{pnl_color}]",
            f"{t.score}/5",
            t.outcome,
        )
    console.print(table)

    # Daily P&L
    daily_table = Table(box=box.SIMPLE_HEAD, title="Daily P&L Summary")
    daily_table.add_column("Date")
    daily_table.add_column("Trades")
    daily_table.add_column("P&L")
    for d in sorted(daily.keys())[-20:]:
        day_pnl = sum(daily[d])
        color = "green" if day_pnl > 0 else "red"
        daily_table.add_row(str(d), str(len(daily[d])), f"[{color}]{day_pnl:+.2f}[/{color}]")
    console.print(daily_table)
