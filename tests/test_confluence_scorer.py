"""Tests for the confluence scorer."""
import pytest
from strategy.confluence_scorer import score_setup


def test_perfect_long_score():
    result = score_setup(
        asia_sweep=True,
        mss_confirmed=True,
        fvg_active=True,
        price=21500.0,
        vwap=21480.0,      # price above VWAP → aligned for long
        direction="long",
        bar_hour=10,
        bar_minute=0,      # in trade window
    )
    assert result.score == 5
    assert result.tradeable is True


def test_wrong_vwap_drops_score():
    result = score_setup(
        asia_sweep=True,
        mss_confirmed=True,
        fvg_active=True,
        price=21500.0,
        vwap=21520.0,      # price below VWAP → NOT aligned for long
        direction="long",
        bar_hour=10,
        bar_minute=0,
    )
    assert result.score == 4
    assert result.vwap_aligned is False


def test_outside_time_window():
    result = score_setup(
        asia_sweep=True,
        mss_confirmed=True,
        fvg_active=True,
        price=21500.0,
        vwap=21480.0,
        direction="long",
        bar_hour=13,       # 1 PM — outside window
        bar_minute=0,
    )
    assert result.in_time_window is False
    assert result.score == 4  # all others pass, time doesn't
    assert result.tradeable is True  # still >= 4 but warn in live


def test_no_sweep_not_tradeable():
    result = score_setup(
        asia_sweep=False,
        mss_confirmed=False,
        fvg_active=False,
        price=21500.0,
        vwap=21480.0,
        direction="long",
        bar_hour=10,
        bar_minute=0,
    )
    assert result.score == 2  # only VWAP + time
    assert result.tradeable is False


def test_short_setup():
    result = score_setup(
        asia_sweep=True,
        mss_confirmed=True,
        fvg_active=True,
        price=21500.0,
        vwap=21520.0,      # price below VWAP → aligned for short
        direction="short",
        bar_hour=9,
        bar_minute=45,
    )
    assert result.score == 5
    assert result.vwap_aligned is True


def test_reason_string_populated():
    result = score_setup(
        asia_sweep=True, mss_confirmed=True, fvg_active=False,
        price=21500.0, vwap=21480.0, direction="long",
        bar_hour=10, bar_minute=0,
    )
    assert "Asia Sweep" in result.reason
    assert "MSS" in result.reason
    assert "FVG" not in result.reason
