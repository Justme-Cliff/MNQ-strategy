"""
FastAPI webhook server.

TradingView sends a POST to /webhook when a TJR signal fires.
The server validates it, runs it through RiskManager, and executes on Tradovate.

Endpoints:
  POST /webhook        — receive TradingView alert
  GET  /status         — current account state
  POST /emergency_stop — cancel everything and close all positions
  GET  /health         — ping check
"""
from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from broker.order_manager import OrderManager
from broker.tradovate_client import TradovateClient
from journal.dashboard import print_dashboard
from journal.trade_journal import TradeJournal
from risk.prop_firm_rules import TradeifyState
from risk.risk_manager import RiskManager
from strategy.signal_generator import signal_from_webhook
from config import WEBHOOK_SECRET, MNQ_SYMBOL

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")

# ── Global instances (set up in lifespan) ───────────────────────────────────
_client: TradovateClient | None = None
_state: TradeifyState | None = None
_risk: RiskManager | None = None
_journal: TradeJournal | None = None
_order_mgr: OrderManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client, _state, _risk, _journal, _order_mgr

    _journal = TradeJournal()
    _state = TradeifyState()
    _state.setup(already_lost=400.0)    # <-- update this as your balance changes

    _risk = RiskManager(_state)
    _client = TradovateClient()

    try:
        ok = await _client.authenticate()
        if ok:
            log.info("Connected to Tradovate")
        else:
            log.warning("Tradovate auth failed — orders will be rejected")
    except Exception as e:
        log.warning("Tradovate connection error: %s", e)

    # Determine active MNQ contract symbol (e.g., MNQM5 for June 2025)
    symbol = _get_active_mnq_symbol()
    _order_mgr = OrderManager(_client, _journal, _risk, symbol)

    log.info("Server ready — symbol: %s", symbol)
    yield

    if _client:
        await _client.close()


def _get_active_mnq_symbol() -> str:
    """Return the front-month MNQ symbol. Update manually each rollover."""
    now = datetime.now(tz=EST)
    # CME MNQ contract months: H(Mar), M(Jun), U(Sep), Z(Dec)
    month_map = {3: "H", 6: "M", 9: "U", 12: "Z"}
    # Roll roughly 5 days before expiration (3rd Friday of month)
    m = now.month
    y = str(now.year)[-2:]
    for exp_month in [3, 6, 9, 12]:
        if m <= exp_month:
            return f"MNQ{month_map[exp_month]}{y}"
    return f"MNQZ{y}"


app = FastAPI(title="TJR Bot", lifespan=lifespan)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "time_est": datetime.now(tz=EST).isoformat()}


@app.get("/status")
async def status():
    if _state is None:
        raise HTTPException(503, "Server not initialized")
    return {
        "account": _state.summary(),
        "today_trades": _journal.get_today_trades() if _journal else [],
        "stats": _journal.get_stats() if _journal else {},
    }


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()

    # Validate secret
    if body.get("secret") != WEBHOOK_SECRET:
        log.warning("Webhook received with wrong secret")
        raise HTTPException(403, "Invalid secret")

    signal = signal_from_webhook(body)
    if signal is None:
        raise HTTPException(400, "Could not parse signal from payload")

    if _risk is None or _order_mgr is None:
        raise HTTPException(503, "Server not ready")

    approved, reason, order_params = _risk.approve(signal)
    log.info("Signal %s/5 %s → %s: %s", signal.score, signal.direction, "APPROVED" if approved else "REJECTED", reason)

    if not approved:
        return JSONResponse({"status": "rejected", "reason": reason})

    # Execute async without blocking the webhook response
    asyncio.create_task(_place_trade(order_params, body))
    return JSONResponse({"status": "accepted", "reason": reason, "params": order_params})


async def _place_trade(order_params: dict, raw_payload: dict) -> None:
    try:
        trade = await _order_mgr.execute_signal(order_params, {
            "direction":   order_params["direction"],
            "score":       order_params["score"],
            "score_reason": order_params["score_reason"],
            "asia_high":   raw_payload.get("asia_high"),
            "asia_low":    raw_payload.get("asia_low"),
            "vwap":        raw_payload.get("vwap"),
        })
        if trade:
            log.info("Trade executed: order_id=%s", trade.order_id)
    except Exception as e:
        log.error("Trade execution failed: %s", e)


@app.post("/emergency_stop")
async def emergency_stop():
    if _order_mgr is None:
        raise HTTPException(503, "Server not ready")
    await _order_mgr.force_close_all("Emergency stop via API")
    return {"status": "emergency_stop_executed"}
