"""
Morning briefing — shown when bot starts each day.
End of session summary — shown at 11:30 AM.
"""
from __future__ import annotations
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from strategy.london_session import london_summary_line
from strategy.market_context import get_vix_regime, check_news_calendar, get_weekly_profile

EST = ZoneInfo("America/New_York")
console = Console()


def get_prev_day_levels() -> dict:
    """Fetch previous day high/low from yfinance."""
    try:
        df = yf.Ticker("NQ=F").history(period="5d", interval="1d", auto_adjust=True)
        if len(df) >= 2:
            prev = df.iloc[-2]
            return {"high": float(prev["High"]), "low": float(prev["Low"])}
    except Exception:
        pass
    return {"high": None, "low": None}


def print_morning_briefing(
    asia_high: float | None,
    asia_low: float | None,
    current_price: float | None,
    state,
    smart,
    london_action: dict | None = None,
    market_context: dict | None = None,
) -> dict:
    """Print full morning briefing. Returns prev day levels dict."""
    now = datetime.now(tz=EST)
    console.rule(f"[bold cyan]TJR Morning Briefing  {now.strftime('%A %B %d, %Y')}[/bold cyan]")

    prev = get_prev_day_levels()
    s = state.summary()
    buf = s["drawdown_buffer"]
    buf_color = "red" if buf < 200 else ("yellow" if buf < 400 else "green")

    # ── Account ────────────────────────────────────────────────────────────────
    acct = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    acct.add_column("k", style="dim")
    acct.add_column("v")
    acct.add_row("Balance",     f"${s['current_balance']:,.2f}")
    acct.add_row("Buffer",      f"[{buf_color}]${buf:.0f} remaining[/{buf_color}]  (floor ${s['drawdown_floor']:,.0f})")
    acct.add_row("Total P&L",   f"${s['total_pnl']:+.2f}")
    acct.add_row("Progress",    f"{s['progress_pct']:.1f}% toward $1,500 target")
    acct.add_row("Win streak",  str(smart.consecutive_wins)   if smart.consecutive_wins  else "none")
    acct.add_row("Loss streak", f"[red]{smart.consecutive_losses}[/red]" if smart.consecutive_losses else "none")
    dow = now.weekday()
    min_score = smart.min_score_required(now.hour, now.minute, dow, market_context=market_context)
    profile = get_weekly_profile(now)
    dow_colors = {0: "green", 1: "red", 2: "cyan", 3: "yellow", 4: "blue"}
    dow_c = dow_colors.get(dow, "white")
    acct.add_row("Day profile",    f"[{dow_c}]{profile['phase'].upper()}[/{dow_c}]  {profile['note']}")
    acct.add_row("Min score today", f"[bold]{min_score}/9[/bold]  [dim]{profile['guidance'][:60]}[/dim]")
    console.print(Panel(acct, title="[bold]Account[/bold]", border_style="blue", padding=(0, 1)))

    # ── Market context: VIX + News ─────────────────────────────────────────────
    vix_data = get_vix_regime()
    news_data = check_news_calendar(now)
    vix_col = "green" if vix_data["regime"] in ("low", "unknown") else ("yellow" if vix_data["regime"] == "medium" else "red")
    news_col = "red" if news_data["skip"] else ("yellow" if news_data["score_penalty"] > 0 else "green")
    ctx_body = (
        f"  VIX: [{vix_col}]{vix_data.get('vix', 'n/a')} ({vix_data['regime']})[/{vix_col}]"
        f"   Regime penalty: +{vix_data['score_penalty']} pts\n"
        f"  News: [{news_col}]{news_data['reason']}[/{news_col}]"
        f"{'   [red]SKIP TRADING NOW[/red]' if news_data['skip'] else ''}"
    )
    if market_context and market_context.get("weekly"):
        wk = market_context["weekly"]
        if wk.get("prev_week_high"):
            ctx_body += f"\n  Prev Week High: [dim]{wk['prev_week_high']:.2f}[/dim]   Prev Week Low: [dim]{wk['prev_week_low']:.2f}[/dim]"
    if market_context and market_context.get("smt"):
        smt = market_context["smt"]
        smt_col = "red" if smt.get("divergent") else "green"
        ctx_body += f"\n  SMT (ES/NQ): [{smt_col}]{smt['detail']}[/{smt_col}]"
    ctx_border = "red" if news_data["skip"] else ("yellow" if vix_data["score_penalty"] > 0 else "dim")
    console.print(Panel(ctx_body, title="[bold]Market Context[/bold]", border_style=ctx_border, padding=(0, 1)))

    # ── Key levels ─────────────────────────────────────────────────────────────
    if asia_high and asia_low and current_price:
        dist_high = abs(current_price - asia_high)
        dist_low  = abs(current_price - asia_low)
        closer    = "Asia High (bear setup likely)" if dist_high < dist_low else "Asia Low (bull setup likely)"

        lvl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        lvl.add_column("k", style="dim")
        lvl.add_column("v")
        lvl.add_row("Current price", f"[bold]{current_price:.2f}[/bold]")
        lvl.add_row("Asia High",     f"[orange1]{asia_high:.2f}[/orange1]  ({dist_high:.0f} pts away)")
        lvl.add_row("Asia Low",      f"[orange1]{asia_low:.2f}[/orange1]   ({dist_low:.0f} pts away)")
        if prev["high"]:
            lvl.add_row("Prev Day High", f"[dim]{prev['high']:.2f}[/dim]")
            lvl.add_row("Prev Day Low",  f"[dim]{prev['low']:.2f}[/dim]")
        lvl.add_row("Closer to",    f"[bold yellow]{closer}[/bold yellow]")
        console.print(Panel(lvl, title="[bold]Key Levels[/bold]", border_style="orange1", padding=(0, 1)))

    # ── London session bias ────────────────────────────────────────────────────
    if london_action:
        direction = london_action.get("direction", "neutral")
        border = "green" if direction == "bullish" else ("red" if direction == "bearish" else "dim")
        console.print(Panel(
            f"  {london_summary_line(london_action)}",
            title="[bold]London Session Bias[/bold]", border_style=border, padding=(0, 1)
        ))

    # ── Consistency cap ────────────────────────────────────────────────────────
    total_profit = state.total_profit
    if total_profit > 0:
        max_today = state.max_allowed_today
        console.print(Panel(
            f"  Total profit: [green]${total_profit:.2f}[/green]\n"
            f"  Max you can make TODAY: [bold yellow]${max_today:.2f}[/bold yellow]  (38% cap — Tradeify rule is 40%)\n"
            f"  [dim]Bot will auto-stop if you approach this limit[/dim]",
            title="[bold]Consistency Cap[/bold]", border_style="yellow", padding=(0, 1)
        ))
    else:
        console.print(Panel(
            f"  Still in drawdown (${total_profit:.2f}) — consistency cap doesn't apply yet\n"
            f"  [green]No daily limit today[/green]",
            title="[bold]Consistency Cap[/bold]", border_style="dim", padding=(0, 1)
        ))

    # ── Game plan ──────────────────────────────────────────────────────────────
    if asia_high and asia_low:
        day_warning = ""
        if dow in (1, 3):
            day_warning = f"\n  [red]Tough day historically. Require higher score. Check Judas Swing guidance.[/red]"
        elif dow == 0:
            day_warning = f"\n  [green]Strong day historically — trust the signals[/green]"
        console.print(Panel(
            f"  [bold]Watch for:[/bold]\n"
            f"  🔴 Price sweeps ABOVE [orange1]{asia_high:.2f}[/orange1] → bear setup (SHORT)\n"
            f"  🟢 Price sweeps BELOW [orange1]{asia_low:.2f}[/orange1] → bull setup (LONG)\n\n"
            f"  [bold]Entry rules:[/bold] Need {min_score}/9 score minimum\n"
            f"  [bold]Risk:[/bold] $50 per trade  |  [bold]Target:[/bold] $150 per trade\n"
            f"  [bold]Max trades:[/bold] 2 today  |  [bold]Stop:[/bold] 11:30 AM EST"
            f"{day_warning}",
            title="[bold]Today's Game Plan[/bold]", border_style="green", padding=(0, 1)
        ))

    console.print()
    return prev


def print_session_summary(state, smart, today_signals: list, today_missed: list):
    """Print end-of-session wrap-up at 11:30 AM."""
    now = datetime.now(tz=EST)
    s   = state.summary()
    buf = s["drawdown_buffer"]
    buf_color = "red" if buf < 200 else ("yellow" if buf < 400 else "green")

    taken  = [t for t in today_signals if t.get("took")]
    wins   = [t for t in taken if t.get("pnl", 0) > 0]
    losses = [t for t in taken if t.get("pnl", 0) < 0]
    be     = [t for t in taken if t.get("pnl", 0) == 0]

    missed_pnl = sum(t.get("would_have_pnl", 0) for t in today_missed)
    missed_color = "green" if missed_pnl > 0 else ("red" if missed_pnl < 0 else "dim")

    days_needed = 0
    if s["total_pnl"] < 1500:
        remaining = 1500 - max(0, s["total_pnl"])
        days_needed = max(1, int(remaining / 150))

    console.print()
    console.rule(f"[bold cyan]Session Over — {now.strftime('%A %B %d')} 11:30 AM[/bold cyan]")

    body = (
        f"  [bold]Today's trades:[/bold]  {len(taken)} taken  "
        f"([green]{len(wins)} wins[/green]  [red]{len(losses)} losses[/red]  {len(be)} BE)\n"
        f"  [bold]Today's P&L:[/bold]    {'+'if s['daily_pnl']>=0 else ''}{s['daily_pnl']:.0f}\n"
    )

    if today_missed:
        body += f"  [bold]Missed signals:[/bold] {len(today_missed)}  → would have been [{missed_color}]{missed_pnl:+.0f}[/{missed_color}]\n"

    body += (
        f"\n  [bold]Account:[/bold]\n"
        f"    Balance: ${s['current_balance']:,.2f}  |  "
        f"Buffer: [{buf_color}]${buf:.0f}[/{buf_color}]\n"
        f"    Total P&L: {s['total_pnl']:+.2f}  |  Progress: {s['progress_pct']:.1f}%\n"
        f"\n  [bold]Path to passing:[/bold]\n"
        f"    Need ${max(0, 1500 - max(0, s['total_pnl'])):.0f} more\n"
        f"    Estimated {days_needed} winning days at $150/day\n"
        f"\n  [dim]Come back Monday 9:00 AM. Same plan.[/dim]"
    )

    console.print(Panel(body, title="[bold white] Session Summary [/bold white]",
                        border_style="cyan", box=box.DOUBLE_EDGE, padding=(1, 2)))
    console.print()
