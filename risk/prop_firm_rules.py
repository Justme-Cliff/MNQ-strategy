"""
Tradeify $25k evaluation rule tracker.

Key rules:
  - Trailing Max Drawdown (EOD): $1,000 — floor moves UP as EOD balance grows
  - No daily loss limit (we self-impose $100)
  - Consistency: no single day > 40% of total profit made (we use 38% buffer)
  - Max contracts: 10 MNQ

State is persisted in SQLite via TradeJournal, but this class holds live session state.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

from config import (
    STARTING_BALANCE,
    TRAILING_MAX_DRAWDOWN,
    PROFIT_TARGET,
    CONSISTENCY_BUFFER,
    CONSISTENCY_RULE,
    MAX_DAILY_LOSS,
    DRAWDOWN_ALERT,
    DRAWDOWN_BLOCK,
)


@dataclass
class TradeifyState:
    # Account
    starting_balance: float = STARTING_BALANCE
    current_balance: float = STARTING_BALANCE
    peak_eod_balance: float = STARTING_BALANCE

    # P&L tracking
    total_realized_pnl: float = 0.0    # lifetime from eval start
    daily_pnl: float = 0.0             # resets each session
    trades_today: int = 0

    # Already lost before we started the bot
    initial_loss: float = 0.0          # set to 400 on startup

    def setup(self, already_lost: float = 400.0) -> None:
        self.initial_loss = already_lost
        self.total_realized_pnl = -already_lost
        self.current_balance = self.starting_balance - already_lost
        self.peak_eod_balance = self.starting_balance  # starts at original balance

    # ── Drawdown ────────────────────────────────────────────────────────────────

    @property
    def drawdown_floor(self) -> float:
        """The lowest balance allowed — trailing from peak EOD balance."""
        return self.peak_eod_balance - TRAILING_MAX_DRAWDOWN

    @property
    def drawdown_buffer(self) -> float:
        """How many dollars remain before hitting the floor."""
        return self.current_balance - self.drawdown_floor

    def record_eod_balance(self, eod_balance: float) -> None:
        """Call at end of each trading day to potentially raise the floor."""
        self.peak_eod_balance = max(self.peak_eod_balance, eod_balance)
        self.current_balance = eod_balance
        self.daily_pnl = 0.0
        self.trades_today = 0

    # ── Consistency rule ────────────────────────────────────────────────────────

    @property
    def total_profit(self) -> float:
        """Only count positive total P&L for the consistency calculation."""
        return max(0.0, self.total_realized_pnl)

    @property
    def max_allowed_today(self) -> float:
        """
        Maximum profit allowed today without breaching the 40% consistency rule.
        We use 38% buffer instead of 40%.
        """
        if self.total_profit == 0:
            return float("inf")
        return self.total_profit * CONSISTENCY_BUFFER

    @property
    def consistency_pct(self) -> float:
        """Current day's contribution to total profit (%)."""
        if self.total_profit == 0:
            return 0.0
        return (self.daily_pnl / self.total_profit) * 100 if self.daily_pnl > 0 else 0.0

    # ── Guards ──────────────────────────────────────────────────────────────────

    def can_open_trade(self) -> tuple[bool, str]:
        """
        Returns (True, "OK") or (False, reason).
        Called BEFORE placing any order.
        """
        if self.drawdown_buffer <= DRAWDOWN_BLOCK:
            return False, f"BLOCKED: Drawdown buffer too low (${self.drawdown_buffer:.0f} remaining)"

        if self.drawdown_buffer <= DRAWDOWN_ALERT:
            pass  # allow but will be logged as warning

        if self.daily_pnl <= -MAX_DAILY_LOSS:
            return False, f"BLOCKED: Daily loss limit hit (${self.daily_pnl:.0f})"

        if self.trades_today >= 2:
            return False, f"BLOCKED: Max 2 trades per day (already {self.trades_today})"

        if self.total_profit > 0 and self.daily_pnl >= self.max_allowed_today:
            return False, (
                f"BLOCKED: Consistency cap hit — today at ${self.daily_pnl:.0f}, "
                f"max allowed ${self.max_allowed_today:.0f} (38% of ${self.total_profit:.0f})"
            )

        return True, "OK"

    # ── P&L updates ─────────────────────────────────────────────────────────────

    def record_trade(self, pnl: float) -> None:
        self.daily_pnl += pnl
        self.total_realized_pnl += pnl
        self.current_balance += pnl
        self.trades_today += 1

    # ── Progress ────────────────────────────────────────────────────────────────

    @property
    def progress_pct(self) -> float:
        return (self.total_realized_pnl / PROFIT_TARGET) * 100

    def summary(self) -> dict:
        return {
            "current_balance":   round(self.current_balance, 2),
            "total_pnl":         round(self.total_realized_pnl, 2),
            "daily_pnl":         round(self.daily_pnl, 2),
            "trades_today":      self.trades_today,
            "drawdown_floor":    round(self.drawdown_floor, 2),
            "drawdown_buffer":   round(self.drawdown_buffer, 2),
            "peak_eod_balance":  round(self.peak_eod_balance, 2),
            "consistency_pct":   round(self.consistency_pct, 1),
            "max_today":         round(self.max_allowed_today, 2) if self.max_allowed_today != float("inf") else "unlimited",
            "profit_target":     PROFIT_TARGET,
            "progress_pct":      round(self.progress_pct, 1),
        }
