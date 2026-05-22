"""Edge cases for position sizer."""
import pytest
from risk.position_sizer import calculate_size, calculate_targets


def test_same_entry_stop():
    result = calculate_size(21500.0, 21500.0)
    assert result["valid"] is False


def test_short_direction_targets():
    targets = calculate_targets(entry=21500.0, stop=21515.0, direction="short")
    # Stop is 15 points above entry
    # TP1 = entry - 1.5*15 = 21500 - 22.5 = 21477.5
    # TP2 = entry - 3.0*15 = 21500 - 45.0 = 21455.0
    assert targets["tp1"] > targets["tp2"]    # for short: TP2 is lower (further down)
    assert targets["tp1"] < 21500.0           # both below entry for short
    assert targets["tp2"] < 21500.0


def test_max_contracts_cap():
    # 5 point stop = $10/contract → could fit 5 contracts, but capped at 10
    result = calculate_size(21500.0, 21495.0)
    assert result["contracts"] <= 10
    assert result["valid"] is True


def test_risk_never_exceeds_50():
    for stop_pts in [5, 10, 15, 20, 25]:
        entry = 21500.0
        stop = entry - stop_pts
        result = calculate_size(entry, stop)
        if result["valid"]:
            assert result["risk_dollars"] <= 50.0
