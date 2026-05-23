"""
Smart adaptive filters — data-driven thresholds that adjust to conditions.

Rules derived from 60-day backtest analysis:
  - Monday: 86% win rate — best day
  - Tuesday: 20% win rate — requires 5/7
  - Thursday: 25% win rate — requires 5/7
  - Sweep depth 0-8 pts: 0% win rate — hard reject
  - Shallow sweeps (8-15 pts): 25% — require 5/7
  - Weak MSS (no displacement): require +1
  - London opposed to setup direction: require +1
  - After 11:00 AM: require 5/7
  - After 2 losses: require 6/7
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class SmartFilter:
    # Loss streak tracking
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    today_results: list = field(default_factory=list)

    # Session price tracking
    session_high: float | None = None
    session_low: float | None = None
    price_history: list = field(default_factory=list)

    # Opening range (9:30-10:00 AM): used for opening range opposed condition
    _opening_range_open: float | None = None
    _opening_range_close: float | None = None
    _opening_range_set: bool = False
    _opening_range_direction: str = "neutral"   # "bullish", "bearish", "neutral"

    def reset_day(self):
        self.today_results = []
        self.session_high = None
        self.session_low = None
        self.price_history = []
        self._opening_range_open = None
        self._opening_range_close = None
        self._opening_range_set = False
        self._opening_range_direction = "neutral"

    def record_result(self, won: bool):
        self.today_results.append(won)
        if won:
            self.consecutive_losses = 0
            self.consecutive_wins += 1
        else:
            self.consecutive_wins = 0
            self.consecutive_losses += 1

    def update_price(self, price: float, now_est: datetime | None = None):
        self.price_history.append(price)
        if len(self.price_history) > 50:
            self.price_history.pop(0)
        if self.session_high is None or price > self.session_high:
            self.session_high = price
        if self.session_low is None or price < self.session_low:
            self.session_low = price

        # Track opening range (9:30-10:00 AM)
        if now_est is not None:
            mins = now_est.hour * 60 + now_est.minute
            if mins == 9 * 60 + 30 and self._opening_range_open is None:
                self._opening_range_open = price
            if 9 * 60 + 30 <= mins < 10 * 60:
                self._opening_range_close = price
            if mins == 10 * 60 and not self._opening_range_set and self._opening_range_open is not None:
                self._opening_range_set = True
                if self._opening_range_close and self._opening_range_close > self._opening_range_open:
                    self._opening_range_direction = "bullish"
                elif self._opening_range_close and self._opening_range_close < self._opening_range_open:
                    self._opening_range_direction = "bearish"

    def opening_range_direction(self) -> str:
        """Direction of the 9:30-10:00 AM opening move."""
        return self._opening_range_direction

    def is_opening_range_opposed(self, signal_direction: str) -> bool:
        """
        True if the setup direction goes AGAINST the opening move.
        Opening went UP but we're shorting = institutions reversed the open trap.
        This is the highest-probability pattern in ICT opening range theory.
        """
        if self._opening_range_direction == "neutral":
            return False
        if self._opening_range_direction == "bullish" and signal_direction == "short":
            return True
        if self._opening_range_direction == "bearish" and signal_direction == "long":
            return True
        return False

    # ── Min score required ────────────────────────────────────────────────────

    def min_score_required(
        self,
        bar_hour: int,
        bar_minute: int,
        day_of_week: int = -1,
        london_aligned: bool = True,
        mss_strong: bool = True,
        sweep_depth: float = 999.0,
        memory=None,
    ) -> int:
        """
        Returns the minimum confluence score required to fire a signal.
        Reads data-driven thresholds from BotMemory when available,
        falls back to hardcoded baseline when not enough samples exist.
        """
        mins = bar_hour * 60 + bar_minute

        # Base threshold: use real win-rate-derived value from memory if available
        if memory is not None:
            base = memory.min_score_for_dow(day_of_week)
        else:
            # Hardcoded baseline (used until memory has enough samples)
            if day_of_week == 1:
                base = 7
            elif day_of_week == 3:
                base = 5
            else:
                base = 4

        # After 2 consecutive losses: require near-perfect setup
        if self.consecutive_losses >= 2:
            base = max(base, 6)

        # Late session (11:00-11:30 AM): require 5/7
        if mins >= 11 * 60:
            base = max(base, 5)

        # Weak MSS (no real displacement): require +1
        if not mss_strong:
            base = max(base, base + 1)

        # London opposes the setup direction: require +1
        if not london_aligned:
            base = max(base, base + 1)

        # Shallow sweep (8-15 pts): require 5/7
        if sweep_depth < 15.0:
            base = max(base, 5)

        # Monday with active win streak in prime window: cap at base 4
        if day_of_week == 0 and mins < 10 * 60 and self.consecutive_wins >= 1:
            base = min(base, 4)

        return min(base, 7)

    # ── Sweep quality check ───────────────────────────────────────────────────

    def is_sweep_valid(
        self,
        sweep_price: float,
        asia_level: float,
        direction: str,
    ) -> tuple[bool, str]:
        """
        Reject sweeps that are too shallow (noise) or too deep (news event).
        Minimum raised from 3 to 8 pts based on backtest: 0-5 pt sweeps had 0% win rate.
        """
        depth = abs(sweep_price - asia_level)

        if depth < 8.0:
            return False, f"Sweep too shallow ({depth:.1f} pts) — noise, not institutional"

        if depth > 80.0:
            return False, f"Sweep too deep ({depth:.1f} pts) — likely news event, skip"

        return True, f"Sweep depth {depth:.1f} pts — valid"

    # ── Market condition ──────────────────────────────────────────────────────

    def market_is_choppy(self) -> bool:
        if len(self.price_history) < 10:
            return False
        rng = max(self.price_history) - min(self.price_history)
        return rng < 15.0

    def summary(self) -> dict:
        return {
            "consecutive_losses":      self.consecutive_losses,
            "consecutive_wins":        self.consecutive_wins,
            "today_results":           self.today_results,
            "choppy":                  self.market_is_choppy(),
            "session_range":           round((self.session_high or 0) - (self.session_low or 0), 2),
            "opening_range_direction": self._opening_range_direction,
        }
