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
        market_context: dict | None = None,
    ) -> int:
        """
        Returns the minimum confluence score required to fire a signal.

        Layers (applied in order):
          1. Base threshold from BotMemory (real win rates) or hardcoded baseline
          2. Market context penalty (VIX regime, news calendar, SMT divergence)
          3. Session-state rules (loss streak, late session, MSS, London, sweep depth)
          4. Monday win-streak fast-pass
        """
        mins = bar_hour * 60 + bar_minute

        # Layer 1: data-driven DOW base
        if memory is not None:
            base = memory.min_score_for_dow(day_of_week)
        else:
            if day_of_week == 1:    # Tuesday: Judas Swing day — require strong confirmation
                base = 8
            elif day_of_week == 3:  # Thursday: jobless claims — all signals elevated
                base = 8
            else:
                base = 4

        # Layer 2: market context penalty (VIX + news + SMT)
        if market_context is not None:
            from strategy.market_context import context_score_penalty
            ctx_skip, ctx_penalty, _ = context_score_penalty(market_context)
            if ctx_skip:
                return 99   # caller should check for this and skip entirely
            # Only apply VIX penalty to LONG setups (high VIX trending markets
            # are actually favorable for SHORT sweep setups — trend continuation)
            news_penalty = market_context.get("news", {}).get("score_penalty", 0)
            smt_penalty  = 1 if market_context.get("smt", {}).get("divergent") else 0
            base = max(base, base + news_penalty + smt_penalty)

        # Layer 3: session-state rules
        if self.consecutive_losses >= 2:
            base = max(base, 6)
        if mins >= 11 * 60:
            base = max(base, 5)
        if not mss_strong:
            base = max(base, base + 1)
        if not london_aligned:
            base = max(base, base + 1)
        if sweep_depth < 15.0:
            base = max(base, 6)  # shallow sweeps: require 6+ not just 5

        # Layer 4: Monday prime-window fast-pass
        if day_of_week == 0 and mins < 10 * 60 and self.consecutive_wins >= 1:
            base = min(base, 4)

        return min(base, 8)

    # ── Sweep quality check ───────────────────────────────────────────────────

    def is_sweep_valid(
        self,
        sweep_price: float,
        asia_level: float,
        direction: str,
    ) -> tuple[bool, str]:
        """
        Reject sweeps that are too shallow (noise) or too deep (news event).
        Backtest data: 0-30 pt sweeps had 0% WR; 30-80 pt sweeps had 89% WR.
        Minimum raised to 20 pts to filter shallow institutional noise.
        """
        depth = abs(sweep_price - asia_level)

        if depth < 20.0:
            return False, f"Sweep too shallow ({depth:.1f} pts) — below 20-pt institutional threshold"

        if depth > 80.0:
            return False, f"Sweep too deep ({depth:.1f} pts) — likely news spike, skip"

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
