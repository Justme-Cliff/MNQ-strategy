"""
Position sizer — always limits risk to MAX_RISK_PER_TRADE dollars.
MNQ = $2 per point. Never exceed 1-2 contracts until proven.
"""
from __future__ import annotations
from config import MAX_RISK_PER_TRADE, MNQ_DOLLARS_PER_POINT, MAX_CONTRACTS_MNQ, MNQ_TICK_SIZE


def _round_to_tick(price: float) -> float:
    ticks = round(price / MNQ_TICK_SIZE)
    return ticks * MNQ_TICK_SIZE


def calculate_size(entry: float, stop: float) -> dict:
    """
    Returns:
        contracts  : number of MNQ contracts (0 if stop is too wide)
        stop_points: distance in index points
        risk_dollars: actual dollar risk (contracts * stop_points * $2)
        valid      : bool — False means skip the trade
        reason     : human-readable explanation
    """
    if abs(entry - stop) < MNQ_TICK_SIZE:
        return {"contracts": 0, "stop_points": 0, "risk_dollars": 0, "valid": False,
                "reason": "Entry and stop are the same price"}

    stop_points = abs(entry - stop)
    risk_per_contract = stop_points * MNQ_DOLLARS_PER_POINT

    if risk_per_contract <= 0:
        return {"contracts": 0, "stop_points": stop_points, "risk_dollars": 0, "valid": False,
                "reason": "Invalid risk calculation"}

    max_contracts = int(MAX_RISK_PER_TRADE / risk_per_contract)
    contracts = min(max_contracts, MAX_CONTRACTS_MNQ)

    if contracts < 1:
        return {
            "contracts": 0,
            "stop_points": round(stop_points, 2),
            "risk_dollars": round(risk_per_contract, 2),
            "valid": False,
            "reason": f"Stop too wide: {stop_points:.1f} pts = ${risk_per_contract:.2f} risk per contract (max ${MAX_RISK_PER_TRADE})",
        }

    actual_risk = contracts * risk_per_contract
    return {
        "contracts": contracts,
        "stop_points": round(stop_points, 2),
        "risk_dollars": round(actual_risk, 2),
        "valid": True,
        "reason": f"{contracts} MNQ @ {stop_points:.1f}pt stop = ${actual_risk:.2f} risk",
    }


def calculate_targets(entry: float, stop: float, direction: str) -> dict:
    """Compute TP1 (1.5:1) and TP2 (3:1) rounded to nearest tick."""
    stop_dist = abs(entry - stop)
    if direction == "long":
        tp1 = _round_to_tick(entry + stop_dist * 1.5)
        tp2 = _round_to_tick(entry + stop_dist * 3.0)
    else:
        tp1 = _round_to_tick(entry - stop_dist * 1.5)
        tp2 = _round_to_tick(entry - stop_dist * 3.0)

    return {
        "tp1": tp1,
        "tp2": tp2,
        "stop_dist": round(stop_dist, 2),
        "points_to_tp2": round(stop_dist * 3.0, 2),
    }
