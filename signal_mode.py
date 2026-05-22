"""
Signal-only mode — no Tradovate connection needed.

TradingView fires a webhook → this server receives it → risk manager checks it
→ prints exactly what to trade in your terminal → you execute manually.

Run: python3 signal_mode.py
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from rich.console import Console
from rich.panel import Panel
from rich import box

from config import WEBHOOK_SECRET, WEBHOOK_PORT
from risk.prop_firm_rules import TradeifyState
from risk.risk_manager import RiskManager
from journal.trade_journal import TradeJournal
from strategy.signal_generator import signal_from_webhook

EST = ZoneInfo("America/New_York")
console = Console()
log = logging.getLogger("signal_mode")

# ── Setup (edit already_lost to match your current loss) ─────────────────────
state = TradeifyState()
state.setup(already_lost=400.0)   # <-- update this number each day

risk = RiskManager(state)
journal = TradeJournal()

app = FastAPI(title="TJR Signal Mode")


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now(tz=EST).strftime("%H:%M:%S EST")}


@app.get("/status")
async def status():
    return {
        "account": state.summary(),
        "today": journal.get_today_trades(),
        "stats": journal.get_stats(),
    }


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()

    if body.get("secret") != WEBHOOK_SECRET:
        log.warning("Wrong secret received")
        raise HTTPException(403, "Invalid secret")

    signal = signal_from_webhook(body)
    if signal is None:
        console.print("[red]Could not parse signal from TradingView payload[/red]")
        raise HTTPException(400, "Bad payload")

    approved, reason, order_params = risk.approve(signal)
    now = datetime.now(tz=EST).strftime("%H:%M:%S")

    if approved:
        _print_trade_alert(signal, order_params, now)
        # Log to journal (status=SIGNAL — you execute manually)
        journal.log_trade({
            "timestamp":      datetime.now(tz=EST).isoformat(),
            "direction":      order_params["direction"],
            "entry_price":    order_params["entry"],
            "stop_price":     order_params["stop"],
            "tp1_price":      order_params["tp1"],
            "tp2_price":      order_params["tp2"],
            "contracts":      order_params["contracts"],
            "risk_dollars":   order_params["risk_dollars"],
            "score":          order_params["score"],
            "score_reason":   order_params["score_reason"],
            "status":         "SIGNAL",
            "drawdown_remaining": state.drawdown_buffer,
            "daily_pnl":      state.daily_pnl,
            "total_pnl":      state.total_realized_pnl,
            "asia_high":      body.get("asia_high"),
            "asia_low":       body.get("asia_low"),
            "vwap":           body.get("vwap"),
        })
        return JSONResponse({"status": "approved", "reason": reason})

    else:
        _print_rejected(signal, reason, now)
        return JSONResponse({"status": "rejected", "reason": reason})


@app.post("/trade_result")
async def trade_result(request: Request):
    """
    Call this manually after your trade closes to update the journal and account state.
    Body: {"pnl": 150.0}   (positive = win, negative = loss)
    """
    body = await request.json()
    pnl = float(body.get("pnl", 0))
    risk.record_fill(pnl)

    color = "green" if pnl >= 0 else "red"
    console.print(f"\n[{color}]Trade recorded: PnL = {'+'if pnl>=0 else ''}{pnl:.2f}[/{color}]")
    _print_account_status()
    return {"status": "recorded", "account": state.summary()}


def _print_trade_alert(signal, order_params, now):
    direction = order_params["direction"].upper()
    color = "green" if direction == "LONG" else "red"
    arrow = "▲" if direction == "LONG" else "▼"

    lines = [
        f"[bold {color}]{arrow} {direction} MNQ — TAKE THIS TRADE[/bold {color}]",
        "",
        f"  Entry:     [bold]{order_params['entry']:.2f}[/bold]   (market order or limit at this price)",
        f"  Stop Loss: [bold red]{order_params['stop']:.2f}[/bold red]   ({order_params['stop_points']:.1f} pts = ${order_params['risk_dollars']:.0f} risk)",
        f"  TP1:       [bold]{order_params['tp1']:.2f}[/bold]   → move stop to break-even when hit",
        f"  TP2:       [bold green]{order_params['tp2']:.2f}[/bold green]   → full exit (3:1 target)",
        f"  Contracts: [bold]{order_params['contracts']} MNQ[/bold]",
        "",
        f"  Score:     {order_params['score']}/5  ({order_params['score_reason']})",
        f"  Buffer:    ${state.drawdown_buffer:.0f} remaining  |  Trades today: {state.trades_today}/2",
    ]

    console.print(Panel(
        "\n".join(lines),
        title=f"[bold white] TJR SIGNAL  {now} [/bold white]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print(f"[dim]After trade closes, run: curl -X POST http://localhost:{WEBHOOK_PORT}/trade_result -H 'Content-Type: application/json' -d '{{\"pnl\": X}}'[/dim]\n")


def _print_rejected(signal, reason, now):
    console.print(Panel(
        f"[yellow]Signal REJECTED — {reason}[/yellow]\n"
        f"Direction: {signal.direction}  Score: {signal.score}/5",
        title=f"[dim] REJECTED  {now} [/dim]",
        border_style="yellow",
        padding=(0, 2),
    ))


def _print_account_status():
    s = state.summary()
    buf = s["drawdown_buffer"]
    buf_color = "red" if buf < 200 else ("yellow" if buf < 400 else "green")
    console.print(
        f"Balance: ${s['current_balance']:,.2f}  |  "
        f"Total P&L: {'+'if s['total_pnl']>=0 else ''}{s['total_pnl']:.2f}  |  "
        f"Buffer: [{buf_color}]${buf:.0f}[/{buf_color}]  |  "
        f"Progress: {s['progress_pct']}% to target"
    )


if __name__ == "__main__":
    console.print(Panel(
        "[bold cyan]TJR Signal Mode — MNQ[/bold cyan]\n\n"
        "Waiting for TradingView signals...\n"
        f"Webhook URL: [bold]http://localhost:{WEBHOOK_PORT}/webhook[/bold]\n\n"
        "[dim]Use ngrok to expose this publicly for TradingView alerts[/dim]",
        box=box.DOUBLE_EDGE,
        border_style="cyan",
    ))
    _print_account_status()
    console.print()
    uvicorn.run(app, host="0.0.0.0", port=WEBHOOK_PORT, log_level="warning")
