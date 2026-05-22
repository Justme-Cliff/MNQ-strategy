"""
OrderManager — sits on top of TradovateClient and handles the full trade lifecycle:
  1. Place bracket order (entry + stop + tp2)
  2. Monitor price → when TP1 hit, move stop to break-even
  3. Hard close at 11:30 AM EST
  4. Emergency stop button
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from broker.tradovate_client import TradovateClient
from journal.trade_journal import TradeJournal
from risk.risk_manager import RiskManager

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


@dataclass
class LiveTrade:
    journal_id: int
    order_id: int
    direction: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    contracts: int
    symbol: str
    stop_at_be: bool = False          # True once stop moved to break-even
    tp1_hit: bool = False
    closed: bool = False
    pnl: float = 0.0


class OrderManager:
    def __init__(self, client: TradovateClient, journal: TradeJournal, risk_mgr: RiskManager, symbol: str):
        self.client = client
        self.journal = journal
        self.risk = risk_mgr
        self.symbol = symbol
        self._open_trades: list[LiveTrade] = []
        self._running = False

    async def execute_signal(self, order_params: dict, signal_data: dict) -> LiveTrade | None:
        """Place the bracket order and log the trade."""
        direction  = order_params["direction"]
        entry      = order_params["entry"]
        stop       = order_params["stop"]
        tp1        = order_params["tp1"]
        tp2        = order_params["tp2"]
        contracts  = order_params["contracts"]

        try:
            resp = await self.client.place_bracket_order(
                symbol=self.symbol,
                direction=direction,
                entry=entry,
                stop=stop,
                tp2=tp2,
                contracts=contracts,
            )
            order_id = resp.get("orderId", resp.get("id", 0))
        except Exception as e:
            log.error("Order placement failed: %s", e)
            return None

        jid = self.journal.log_trade({
            **signal_data,
            "entry_price":   entry,
            "stop_price":    stop,
            "tp1_price":     tp1,
            "tp2_price":     tp2,
            "contracts":     contracts,
            "risk_dollars":  order_params["risk_dollars"],
            "tradovate_order_id": str(order_id),
            "status": "OPEN",
            "drawdown_remaining": self.risk.state.drawdown_buffer,
            "daily_pnl":     self.risk.state.daily_pnl,
            "total_pnl":     self.risk.state.total_realized_pnl,
        })

        trade = LiveTrade(
            journal_id=jid,
            order_id=order_id,
            direction=direction,
            entry=entry,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            contracts=contracts,
            symbol=self.symbol,
        )
        self._open_trades.append(trade)
        log.info("Trade opened: %s %s @ %.2f → stop %.2f tp2 %.2f", direction, self.symbol, entry, stop, tp2)
        return trade

    async def on_price_update(self, current_price: float) -> None:
        """Called on each tick — manages TP1 break-even logic."""
        for trade in self._open_trades:
            if trade.closed or trade.stop_at_be:
                continue

            if trade.direction == "long" and current_price >= trade.tp1:
                await self._move_to_breakeven(trade)
            elif trade.direction == "short" and current_price <= trade.tp1:
                await self._move_to_breakeven(trade)

    async def _move_to_breakeven(self, trade: LiveTrade) -> None:
        """Move stop loss to entry price (break-even)."""
        try:
            await self.client.modify_order(trade.order_id, trade.entry)
            trade.stop_at_be = True
            trade.tp1_hit = True
            log.info("Stop moved to break-even @ %.2f for order %s", trade.entry, trade.order_id)
        except Exception as e:
            log.error("Failed to move stop to BE: %s", e)

    def record_close(self, order_id: int, exit_price: float) -> None:
        """Call when Tradovate confirms an order is closed."""
        for trade in self._open_trades:
            if trade.order_id != order_id or trade.closed:
                continue
            if trade.direction == "long":
                pnl = (exit_price - trade.entry) * trade.contracts * 2.0
            else:
                pnl = (trade.entry - exit_price) * trade.contracts * 2.0

            trade.closed = True
            trade.pnl = round(pnl, 2)
            self.risk.record_fill(pnl)

            outcome = "WIN" if pnl > 0 else "LOSS"
            self.journal.update_trade(trade.journal_id, {
                "exit_price":   exit_price,
                "pnl_dollars":  trade.pnl,
                "outcome":      outcome,
                "status":       "CLOSED",
                "daily_pnl":    self.risk.state.daily_pnl,
                "total_pnl":    self.risk.state.total_realized_pnl,
                "drawdown_remaining": self.risk.state.drawdown_buffer,
            })
            log.info("Trade closed: %s PnL=$%.2f", outcome, pnl)
            break

        self._open_trades = [t for t in self._open_trades if not t.closed]

    async def force_close_all(self, reason: str = "Manual") -> None:
        """Emergency or end-of-session close."""
        log.warning("Force closing all positions: %s", reason)
        await self.client.cancel_all_orders()
        await self.client.close_all_positions()

    def has_open_trades(self) -> bool:
        return any(not t.closed for t in self._open_trades)
