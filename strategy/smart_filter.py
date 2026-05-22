"""
Smart adaptive filters — makes the bot learn from what's happening.

1. Consecutive loss protection — gets more selective after losses
2. Sweep quality filter — ignores fake or too-deep sweeps
3. Time quality — stricter requirements late in session
4. Session bias — tracks if market is trending or choppy today
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date


@dataclass
class SmartFilter:
    # Loss streak tracking
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    today_results: list = field(default_factory=list)
    last_result_date: date | None = None

    # Session tracking
    session_high: float | None = None
    session_low: float | None = None
    price_history: list = field(default_factory=list)  # last 20 prices

    def reset_day(self):
        self.today_results = []
        self.session_high = None
        self.session_low = None
        self.price_history = []

    def record_result(self, won: bool):
        self.today_results.append(won)
        if won:
            self.consecutive_losses = 0
            self.consecutive_wins += 1
        else:
            self.consecutive_wins = 0
            self.consecutive_losses += 1

    def update_price(self, price: float):
        self.price_history.append(price)
        if len(self.price_history) > 50:
            self.price_history.pop(0)
        if self.session_high is None or price > self.session_high:
            self.session_high = price
        if self.session_low is None or price < self.session_low:
            self.session_low = price

    # ── Min score required ────────────────────────────────────────────────────

    def min_score_required(self, bar_hour: int, bar_minute: int) -> int:
        """
        Adapts required score based on:
        - Loss streak (gets stricter after losses)
        - Time of day (stricter late in session)
        """
        base = 4
        mins = bar_hour * 60 + bar_minute

        # After 2 consecutive losses → require 5/5 (only perfect setups)
        if self.consecutive_losses >= 2:
            base = 5

        # Late session (11:00-11:30 AM) → always require 5/5
        if mins >= 11 * 60:
            base = 5

        # Best window (9:30-10:00 AM) + on a win streak → allow 4/5
        if mins < 10 * 60 and self.consecutive_wins >= 2:
            base = 4

        return base

    # ── Sweep quality check ───────────────────────────────────────────────────

    def is_sweep_valid(
        self,
        sweep_price: float,
        asia_level: float,
        direction: str,
    ) -> tuple[bool, str]:
        """
        Filter out bad sweeps:
        - Too shallow (< 3 pts): likely noise, not a real liquidity grab
        - Too deep (> 80 pts): entry zone is too far from stop, risk too high
        """
        depth = abs(sweep_price - asia_level)

        if depth < 3.0:
            return False, f"Sweep too shallow ({depth:.1f} pts) — likely noise"

        if depth > 80.0:
            return False, f"Sweep too deep ({depth:.1f} pts) — risk unmanageable"

        return True, f"Sweep depth {depth:.1f} pts — valid"

    # ── Market condition ──────────────────────────────────────────────────────

    def market_is_choppy(self) -> bool:
        """
        Detect if market is chopping around with no clear direction.
        Uses the last 20 price updates — if range is tiny, it's choppy.
        """
        if len(self.price_history) < 10:
            return False
        rng = max(self.price_history) - min(self.price_history)
        return rng < 15.0  # less than 15 points range = choppy

    def summary(self) -> dict:
        mins_required = self.min_score_required(9, 45)  # example time
        return {
            "consecutive_losses": self.consecutive_losses,
            "consecutive_wins":   self.consecutive_wins,
            "today_results":      self.today_results,
            "choppy":             self.market_is_choppy(),
            "session_range":      round((self.session_high or 0) - (self.session_low or 0), 2),
        }
