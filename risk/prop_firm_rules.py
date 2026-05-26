"""
Tradeify $25k evaluation rule tracker.

Rules:
  - Trailing Max Drawdown (EOD): $1,000
  - Self-imposed daily loss limit: $150
  - Consistency: no single day > 40% of total profit (we use 38% buffer)
  - Max trades: 3/day
"""
from __future__ import annotations
from dataclasses import dataclass

STARTING_BALANCE      = 25_000.0
TRAILING_MAX_DRAWDOWN = 1_000.0
PROFIT_TARGET         = 1_500.0
MAX_DAILY_LOSS        = 150.0
MAX_TRADES_PER_DAY    = 3
CONSISTENCY_BUFFER    = 0.38
DRAWDOWN_ALERT        = 200.0
DRAWDOWN_BLOCK        = 100.0


@dataclass
class TradeifyState:
    starting_balance:   float = STARTING_BALANCE
    current_balance:    float = STARTING_BALANCE
    peak_eod_balance:   float = STARTING_BALANCE
    total_realized_pnl: float = 0.0
    daily_pnl:          float = 0.0
    trades_today:       int   = 0

    def setup(self, already_lost: float = 0.0) -> None:
        self.total_realized_pnl = -already_lost
        self.current_balance    = self.starting_balance - already_lost
        self.peak_eod_balance   = self.starting_balance

    @property
    def drawdown_floor(self) -> float:
        return self.peak_eod_balance - TRAILING_MAX_DRAWDOWN

    @property
    def drawdown_buffer(self) -> float:
        return self.current_balance - self.drawdown_floor

    @property
    def total_profit(self) -> float:
        return max(0.0, self.total_realized_pnl)

    @property
    def max_allowed_today(self) -> float:
        if self.total_profit == 0:
            return float("inf")
        return self.total_profit * CONSISTENCY_BUFFER

    @property
    def consistency_pct(self) -> float:
        if self.total_profit == 0:
            return 0.0
        return (self.daily_pnl / self.total_profit * 100) if self.daily_pnl > 0 else 0.0

    @property
    def progress_pct(self) -> float:
        return (self.total_realized_pnl / PROFIT_TARGET) * 100

    def can_open_trade(self) -> tuple[bool, str]:
        if self.drawdown_buffer <= DRAWDOWN_BLOCK:
            return False, f"Drawdown buffer too low (${self.drawdown_buffer:.0f} left)"
        if self.daily_pnl <= -MAX_DAILY_LOSS:
            return False, f"Daily loss limit hit (${self.daily_pnl:.0f})"
        if self.trades_today >= MAX_TRADES_PER_DAY:
            return False, f"Max {MAX_TRADES_PER_DAY} trades/day reached"
        if self.total_profit > 0 and self.daily_pnl >= self.max_allowed_today:
            return False, f"Consistency cap hit (${self.daily_pnl:.0f} today, max ${self.max_allowed_today:.0f})"
        return True, "OK"

    def record_trade(self, pnl: float) -> None:
        self.daily_pnl          += pnl
        self.total_realized_pnl += pnl
        self.current_balance    += pnl
        self.trades_today       += 1

    def record_eod(self, eod_balance: float) -> None:
        self.peak_eod_balance = max(self.peak_eod_balance, eod_balance)
        self.current_balance  = eod_balance
        self.daily_pnl        = 0.0
        self.trades_today     = 0

    def summary(self) -> dict:
        return {
            "current_balance":  round(self.current_balance, 2),
            "total_pnl":        round(self.total_realized_pnl, 2),
            "daily_pnl":        round(self.daily_pnl, 2),
            "trades_today":     self.trades_today,
            "drawdown_floor":   round(self.drawdown_floor, 2),
            "drawdown_buffer":  round(self.drawdown_buffer, 2),
            "peak_eod_balance": round(self.peak_eod_balance, 2),
            "consistency_pct":  round(self.consistency_pct, 1),
            "max_today":        round(self.max_allowed_today, 2) if self.max_allowed_today != float("inf") else "unlimited",
            "profit_target":    PROFIT_TARGET,
            "progress_pct":     round(self.progress_pct, 1),
        }
