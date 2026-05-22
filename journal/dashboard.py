"""
Live terminal dashboard using the Rich library.
Shows account state, today's trades, and overall stats.
Run standalone or import print_dashboard() for a one-time snapshot.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich import box
from rich.text import Text

from journal.trade_journal import TradeJournal
from risk.prop_firm_rules import TradeifyState

EST = ZoneInfo("America/New_York")
console = Console()


def _color_pnl(val: float) -> str:
    return f"[green]+${val:.2f}[/green]" if val >= 0 else f"[red]-${abs(val):.2f}[/red]"


def print_dashboard(state: TradeifyState, journal: TradeJournal) -> None:
    console.clear()
    now = datetime.now(tz=EST).strftime("%Y-%m-%d %H:%M:%S EST")
    summary = state.summary()

    # ── Header ──────────────────────────────────────────────────────────────────
    console.print(Panel(
        f"[bold cyan]TJR Enhanced — MNQ Auto Trader[/bold cyan]   [dim]{now}[/dim]",
        box=box.DOUBLE_EDGE,
    ))

    # ── Account stats ───────────────────────────────────────────────────────────
    buf = summary["drawdown_buffer"]
    buf_color = "red" if buf < 200 else ("yellow" if buf < 400 else "green")

    stats_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    stats_table.add_column("Key", style="bold")
    stats_table.add_column("Value")

    stats_table.add_row("Balance",          f"${summary['current_balance']:,.2f}")
    stats_table.add_row("Daily P&L",        _color_pnl(summary["daily_pnl"]))
    stats_table.add_row("Total P&L",        _color_pnl(summary["total_pnl"]))
    stats_table.add_row("Profit Target",    f"${summary['profit_target']:,}  ({summary['progress_pct']}% there)")
    stats_table.add_row("Drawdown Buffer",  f"[{buf_color}]${buf:.0f}[/{buf_color}]  (floor ${summary['drawdown_floor']:,.0f})")
    stats_table.add_row("Trades Today",     f"{summary['trades_today']}/2")
    stats_table.add_row("Consistency",      f"{summary['consistency_pct']}%  (max {int(summary['max_today']) if summary['max_today'] != 'unlimited' else '∞'})")

    console.print(Panel(stats_table, title="[bold]Account[/bold]", border_style="blue"))

    # ── Today's trades ──────────────────────────────────────────────────────────
    today_trades = journal.get_today_trades()
    t_table = Table(box=box.SIMPLE_HEAD, show_header=True)
    t_table.add_column("Time",      style="dim")
    t_table.add_column("Dir")
    t_table.add_column("Entry")
    t_table.add_column("Stop")
    t_table.add_column("TP2")
    t_table.add_column("Exit")
    t_table.add_column("P&L")
    t_table.add_column("Score")
    t_table.add_column("Status")

    for tr in today_trades:
        pnl = tr.get("pnl_dollars") or 0
        pnl_str = _color_pnl(pnl) if tr.get("status") == "CLOSED" else "[dim]open[/dim]"
        status_color = "green" if tr.get("outcome", "").startswith("WIN") else ("red" if tr.get("status") == "CLOSED" else "yellow")
        t_table.add_row(
            str(tr.get("timestamp", ""))[:16],
            "[green]LONG[/green]" if tr.get("direction") == "long" else "[red]SHORT[/red]",
            f"{tr.get('entry_price', 0):.2f}",
            f"{tr.get('stop_price', 0):.2f}",
            f"{tr.get('tp2_price', 0):.2f}",
            f"{tr.get('exit_price', 0):.2f}" if tr.get("exit_price") else "—",
            pnl_str,
            f"{tr.get('score', 0)}/5",
            f"[{status_color}]{tr.get('status', '?')}[/{status_color}]",
        )

    console.print(Panel(t_table, title="[bold]Today's Trades[/bold]", border_style="blue"))

    # ── All-time stats ──────────────────────────────────────────────────────────
    stats = journal.get_stats()
    console.print(
        f"All-time: [bold]{stats['total_trades']}[/bold] trades  |  "
        f"[green]{stats['wins']} wins[/green]  [red]{stats['losses']} losses[/red]  |  "
        f"Win rate [bold]{stats['win_rate']}%[/bold]  |  "
        f"Avg win [green]+${stats['avg_win']}[/green]  Avg loss [red]${stats['avg_loss']}[/red]"
    )
    console.print()
