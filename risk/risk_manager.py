"""
RiskManager — single entry point that approves or rejects every trade.

Checks (in order):
  1. Time window (9:30–11:30 AM EST)
  2. Confluence score >= 4
  3. Stop width <= 25 points ($50 risk on 1 contract)
  4. Tradeify prop firm rules (drawdown, trades, consistency)
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from risk.position_sizer import calculate_size, calculate_targets
from risk.prop_firm_rules import TradeifyState
from strategy.signal_generator import TradeSignal
from config import (
    MIN_CONFLUENCE_SCORE,
    MAX_STOP_POINTS,
    MIN_TARGET_POINTS,
    TRADE_START_HOUR, TRADE_START_MIN,
    TRADE_END_HOUR, TRADE_END_MIN,
    DRAWDOWN_ALERT,
)

EST = ZoneInfo("America/New_York")


class RiskManager:
    def __init__(self, state: TradeifyState):
        self.state = state

    def approve(self, signal: TradeSignal) -> tuple[bool, str, dict]:
        """
        Returns: (approved: bool, reason: str, order_params: dict)
        order_params is populated only when approved=True.
        """
        # 1. Time window
        now_est = datetime.now(tz=EST)
        ok, reason = self._check_time(now_est)
        if not ok:
            return False, reason, {}

        # 2. Confluence score
        if signal.score < MIN_CONFLUENCE_SCORE:
            return False, f"Score {signal.score}/5 below minimum {MIN_CONFLUENCE_SCORE}/5", {}

        # 3. Position size / stop width
        size = calculate_size(signal.entry, signal.stop)
        if not size["valid"]:
            return False, size["reason"], {}

        if size["stop_points"] > MAX_STOP_POINTS:
            return False, f"Stop too wide: {size['stop_points']:.1f} pts (max {MAX_STOP_POINTS})", {}

        targets = calculate_targets(signal.entry, signal.stop, signal.direction)
        if targets["points_to_tp2"] < MIN_TARGET_POINTS:
            return False, f"Target too close: {targets['points_to_tp2']:.1f} pts (min {MIN_TARGET_POINTS})", {}

        # 4. Prop firm / daily rules
        prop_ok, prop_reason = self.state.can_open_trade()
        if not prop_ok:
            return False, prop_reason, {}

        # Drawdown warning (non-blocking)
        warning = ""
        if self.state.drawdown_buffer <= DRAWDOWN_ALERT:
            warning = f" [WARNING: only ${self.state.drawdown_buffer:.0f} drawdown remaining]"

        order_params = {
            "direction": signal.direction,
            "entry": signal.entry,
            "stop": signal.stop,
            "tp1": targets["tp1"],
            "tp2": targets["tp2"],
            "contracts": size["contracts"],
            "risk_dollars": size["risk_dollars"],
            "stop_points": size["stop_points"],
            "score": signal.score,
            "score_reason": signal.confluence.reason,
        }

        return True, f"APPROVED — {size['reason']}{warning}", order_params

    def _check_time(self, now_est: datetime) -> tuple[bool, str]:
        start = now_est.replace(hour=TRADE_START_HOUR, minute=TRADE_START_MIN, second=0, microsecond=0)
        end   = now_est.replace(hour=TRADE_END_HOUR,   minute=TRADE_END_MIN,   second=0, microsecond=0)
        if start <= now_est < end:
            return True, "OK"
        return False, f"Outside trade window ({TRADE_START_HOUR}:{TRADE_START_MIN:02d}–{TRADE_END_HOUR}:{TRADE_END_MIN:02d} EST)"

    def record_fill(self, pnl: float) -> None:
        """Call when a trade closes with its P&L."""
        self.state.record_trade(pnl)
