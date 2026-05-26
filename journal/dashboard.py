"""
Terminal dashboard — account state, today's trades, all-time stats.
Run standalone: python3 -m journal.dashboard
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from journal.trade_journal import TradeJournal
from risk.prop_firm_rules import TradeifyState

EST     = ZoneInfo("America/New_York")
console = Console()


def _pnl(val: float) -> str:
    return f"[green]+${val:.2f}[/green]" if val >= 0 else f"[red]-${abs(val):.2f}[/red]"


def print_dashboard(state: TradeifyState, journal: TradeJournal) -> None:
    console.clear()
    now = datetime.now(tz=EST).strftime("%Y-%m-%d  %H:%M:%S ET")
    s   = state.summary()

    console.print(Panel(
        f"[bold cyan]NQ Quant System — Trade Journal[/bold cyan]   [dim]{now}[/dim]",
        box=box.DOUBLE_EDGE,
    ))

    # ── Account ──────────────────────────────────────────────────────────────
    buf       = s["drawdown_buffer"]
    buf_color = "red" if buf < 200 else ("yellow" if buf < 400 else "green")

    acct = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    acct.add_column("Key",   style="bold")
    acct.add_column("Value")
    acct.add_row("Balance",         f"${s['current_balance']:,.2f}")
    acct.add_row("Daily P&L",       _pnl(s["daily_pnl"]))
    acct.add_row("Total P&L",       _pnl(s["total_pnl"]))
    acct.add_row("Profit Target",   f"${s['profit_target']:,}   ({s['progress_pct']}% there)")
    acct.add_row("Drawdown Buffer", f"[{buf_color}]${buf:.0f}[/{buf_color}]  (floor ${s['drawdown_floor']:,.0f})")
    acct.add_row("Trades Today",    f"{s['trades_today']}/3")
    if s["max_today"] != "unlimited":
        acct.add_row("Consistency",
                     f"{s['consistency_pct']}%  (max today ${s['max_today']:.0f})")
    console.print(Panel(acct, title="[bold]Account[/bold]", border_style="blue"))

    # ── Today's trades ────────────────────────────────────────────────────────
    today_trades = journal.get_today_trades()
    tbl = Table(box=box.SIMPLE_HEAD)
    tbl.add_column("Time",     style="dim")
    tbl.add_column("Strategy")
    tbl.add_column("Dir")
    tbl.add_column("Entry")
    tbl.add_column("Stop")
    tbl.add_column("Target")
    tbl.add_column("Exit")
    tbl.add_column("P&L")
    tbl.add_column("Status")

    for tr in today_trades:
        pnl    = tr.get("pnl_dollars") or 0
        closed = tr.get("status") == "CLOSED"
        pnl_s  = _pnl(pnl) if closed else "[dim]open[/dim]"
        sc     = "green" if (tr.get("outcome") or "").startswith("WIN") else ("red" if closed else "yellow")
        tbl.add_row(
            str(tr.get("timestamp", ""))[:16],
            tr.get("strategy", "—"),
            "[green]LONG[/green]"  if tr.get("direction") == "long" else "[red]SHORT[/red]",
            f"{tr.get('entry_price', 0):.1f}",
            f"{tr.get('stop_price',  0):.1f}",
            f"{tr.get('tp1_price',   0):.1f}",
            f"{tr.get('exit_price',  0):.1f}" if tr.get("exit_price") else "—",
            pnl_s,
            f"[{sc}]{tr.get('status', '?')}[/{sc}]",
        )

    console.print(Panel(tbl, title="[bold]Today's Trades[/bold]", border_style="blue"))

    # ── All-time ──────────────────────────────────────────────────────────────
    stats = journal.get_stats()
    if stats["total_trades"] == 0:
        console.print("All-time: no trades logged yet.")
    else:
        console.print(
            f"All-time: [bold]{stats['total_trades']}[/bold] trades  |  "
            f"[green]{stats['wins']}W[/green]  [red]{stats['losses']}L[/red]  |  "
            f"WR [bold]{stats['win_rate']}%[/bold]  |  "
            f"Avg win [green]+${stats['avg_win']:.0f}[/green]  "
            f"Avg loss [red]-${abs(stats['avg_loss']):.0f}[/red]  |  "
            f"P&L {_pnl(stats['total_pnl'])}"
        )
    console.print()


if __name__ == "__main__":
    import json
    import os
    import time
    from pathlib import Path
    from datetime import date as _date

    j     = TradeJournal()
    state = TradeifyState()

    acct_path = Path(__file__).parent / "account.json"

    def _reload_state() -> TradeifyState:
        s = TradeifyState()
        if acct_path.exists():
            acct = json.loads(acct_path.read_text())
            s.starting_balance    = acct["starting_balance"]
            s.current_balance     = acct["current_balance"]
            s.peak_eod_balance    = acct.get("peak_eod_balance", acct["starting_balance"])
            s.total_realized_pnl  = acct["current_balance"] - acct["starting_balance"]
        today = str(_date.today())
        for t in TradeJournal().get_all_trades():
            if t.get("status") == "CLOSED" and t.get("pnl_dollars") is not None:
                if str(t.get("timestamp", ""))[:10] == today:
                    s.record_trade(t["pnl_dollars"])
        return s

    while True:
        try:
            state = _reload_state()
            print_dashboard(state, TradeJournal())
            time.sleep(5)
        except KeyboardInterrupt:
            break
