"""
Fractional Kelly Position Sizing.

Kelly criterion (Kelly 1956):
  f* = p - q/b
  p = win probability, q = 1-p, b = avg_win / avg_loss

Half-Kelly is standard in institutional risk management:
  - Reduces variance by 50%
  - Retains 75% of EV advantage
  - Prevents ruin from parameter estimation error

Maps to 1 or 2 MNQ contracts (max 2 = prop firm rule).
  half_kelly >= 0.30 → 2 contracts
  half_kelly <  0.30 → 1 contract

Requires minimum 20 trades for reliable estimation (else default to 1).
"""
from __future__ import annotations
import numpy as np


def kelly_contracts(
    trade_history: list,
    lookback: int = 50,
    min_trades: int = 20,
    max_contracts: int = 2,
) -> int:
    """
    Compute half-Kelly position size as MNQ contract count.

    trade_history: list of objects with .outcome ("WIN"/"LOSS") and .pnl (float)
    Returns: 1 or 2
    """
    if len(trade_history) < min_trades:
        return 1

    recent = trade_history[-lookback:]
    wins   = [t for t in recent if t.outcome == "WIN"]
    losses = [t for t in recent if t.outcome == "LOSS"]

    if not wins or not losses:
        return 1

    n = len(recent)
    p = len(wins) / n
    q = len(losses) / n

    avg_win  = float(np.mean([t.pnl for t in wins]))
    avg_loss = float(abs(np.mean([t.pnl for t in losses])))

    if avg_loss < 0.01:
        return 1

    b = avg_win / avg_loss   # reward-to-risk ratio
    if b <= 0:
        return 1

    kelly_f    = p - q / b
    half_kelly = kelly_f / 2.0

    if half_kelly >= 0.30:
        return min(2, max_contracts)
    return 1
