"""Tests for RiskManager and PropFirmRules."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo

from risk.prop_firm_rules import TradeifyState
from risk.position_sizer import calculate_size, calculate_targets

EST = ZoneInfo("America/New_York")


# ── Position Sizer ────────────────────────────────────────────────────────────

def test_size_normal_stop():
    # 20 point stop on MNQ = $40 risk on 1 contract → 1 contract
    result = calculate_size(entry=21500.0, stop=21480.0)
    assert result["valid"] is True
    assert result["contracts"] == 1
    assert result["stop_points"] == 20.0
    assert result["risk_dollars"] == 40.0


def test_size_wide_stop_rejected():
    # 30 point stop = $60 > $50 max → 0 contracts
    result = calculate_size(entry=21500.0, stop=21470.0)
    assert result["valid"] is False
    assert result["contracts"] == 0


def test_size_exactly_at_limit():
    # 25 point stop = $50 exactly → 1 contract
    result = calculate_size(entry=21500.0, stop=21475.0)
    assert result["valid"] is True
    assert result["contracts"] == 1
    assert result["risk_dollars"] == 50.0


def test_size_tight_stop_two_contracts():
    # 10 point stop = $20 per contract → can fit 2 contracts within $50
    result = calculate_size(entry=21500.0, stop=21490.0)
    assert result["valid"] is True
    assert result["contracts"] == 2
    assert result["risk_dollars"] == pytest.approx(40.0)


def test_targets_long():
    targets = calculate_targets(entry=21500.0, stop=21480.0, direction="long")
    assert targets["tp1"] == pytest.approx(21530.0, abs=0.5)  # 1.5 * 20 = 30 pts
    assert targets["tp2"] == pytest.approx(21560.0, abs=0.5)  # 3.0 * 20 = 60 pts


def test_targets_short():
    targets = calculate_targets(entry=21500.0, stop=21520.0, direction="short")
    assert targets["tp1"] == pytest.approx(21470.0, abs=0.5)
    assert targets["tp2"] == pytest.approx(21440.0, abs=0.5)


# ── Prop Firm Rules ────────────────────────────────────────────────────────────

def test_initial_state():
    state = TradeifyState()
    state.setup(already_lost=400.0)
    assert state.total_realized_pnl == -400.0
    assert state.drawdown_buffer == pytest.approx(600.0, abs=1.0)


def test_can_trade_ok():
    state = TradeifyState()
    state.setup(already_lost=400.0)
    ok, reason = state.can_open_trade()
    assert ok is True


def test_max_trades_per_day():
    state = TradeifyState()
    state.setup(already_lost=400.0)
    state.trades_today = 2
    ok, reason = state.can_open_trade()
    assert ok is False
    assert "2 trades" in reason.lower() or "max" in reason.lower()


def test_daily_loss_block():
    state = TradeifyState()
    state.setup(already_lost=400.0)
    state.daily_pnl = -100.0
    ok, reason = state.can_open_trade()
    assert ok is False
    assert "daily loss" in reason.lower() or "loss limit" in reason.lower()


def test_drawdown_block():
    state = TradeifyState()
    state.setup(already_lost=400.0)
    state.current_balance = state.drawdown_floor + 50  # only $50 buffer
    ok, reason = state.can_open_trade()
    assert ok is False
    assert "drawdown" in reason.lower() or "blocked" in reason.lower()


def test_consistency_rule():
    state = TradeifyState()
    state.setup(already_lost=0.0)
    state.total_realized_pnl = 300.0
    state.daily_pnl = 120.0  # 40% of 300 = 120, we cap at 38% = 114
    ok, reason = state.can_open_trade()
    assert ok is False
    assert "consistency" in reason.lower() or "cap" in reason.lower()


def test_record_trade_updates_state():
    state = TradeifyState()
    state.setup(already_lost=400.0)
    state.record_trade(150.0)
    assert state.daily_pnl == 150.0
    assert state.total_realized_pnl == -250.0
    assert state.trades_today == 1
