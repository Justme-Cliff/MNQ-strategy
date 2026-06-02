"""
80% Value Area Rule — Market Profile Strategy.

From The Profile Reports (Dalton Capital Management, 1987-1991) and validated
across 30+ years of futures data:

  "If price opens outside the prior session's Value Area and then rotates back
   inside, there is approximately an 80% probability that price will traverse
   the entire Value Area."

For NQ 5-minute bars:
  - Price opens outside prior VA
  - Enters the VA (crosses VAH from above, or VAL from below)
  - Stays inside for 3+ consecutive 5-min bars (confirms re-entry)
  - Target: opposite VA edge (full traverse)
  - Stop: 3pts beyond the VA edge that price entered through

Three setup types:
  Type A: Open above VAH, pull back into VA, stay 3 bars -> SHORT to VAL
  Type B: Open below VAL, rally into VA, stay 3 bars    -> LONG to VAH
  Type C: Mid-session VA reclaim                         -> trade toward opposite edge

Requires: prior session VA from inst_volprofile.py
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from strategy.inst_volprofile import get_prior_session_levels

EST = ZoneInfo("America/New_York")

CONFIRM_BARS = 3      # consecutive bars inside VA before entry
MIN_TARGET   = 5.0    # minimum VA traverse distance to bother trading


@dataclass
class VASignal:
    direction:      str
    entry:          float
    stop:           float
    target:         float
    setup_type:     str    # "A", "B", "C"
    va_entry_edge:  float
    va_target_edge: float
    signal_bar_idx: int


def detect_va_rule_signal(
    df: pd.DataFrame,
    today: date,
    atr: float,
) -> Optional[VASignal]:
    """
    Detect the 80% Value Area Rule setup.

    Returns a VASignal if the setup triggers, else None.
    """
    try:
        prior_levels = get_prior_session_levels(df, today)
        if prior_levels is None:
            return None

        vah = prior_levels.vah
        val = prior_levels.val
        va_range = vah - val

        if va_range < 5.0 or atr <= 0:
            return None

        est_idx  = df.index.tz_convert(EST)
        today_df = df[est_idx.date == today].copy()
        if len(today_df) < 8:
            return None

        first_bar  = today_df.iloc[0]
        open_price = float(first_bar["Open"])

        opened_above_va = open_price > vah
        opened_below_va = open_price < val

        consecutive_inside = 0
        entry_fired = False

        stop_buffer = max(3.0, atr * 0.015)  # 1.5% of daily ATR or 3pts minimum

        for pos, (ts, row) in enumerate(today_df.iterrows()):
            dt   = ts.astimezone(EST)
            mins = dt.hour * 60 + dt.minute

            if mins < 9 * 60 + 45:   # skip first 15 min
                continue
            if mins >= 11 * 60 + 30:  # stop looking after 11:30 AM
                break
            if entry_fired:
                break

            close = float(row["Close"])
            inside_va = val <= close <= vah

            if inside_va:
                consecutive_inside += 1
            else:
                consecutive_inside = 0
                # Track mid-session reclaim: if not opened outside VA
                if not opened_above_va and not opened_below_va:
                    opened_above_va = close > vah
                    opened_below_va = close < val

            if consecutive_inside >= CONFIRM_BARS and not entry_fired:
                entry_fired = True

                if opened_above_va:
                    # Type A: came from above VA, now inside -> SHORT to VAL
                    direction = "short"
                    entry     = close
                    stop      = vah + stop_buffer
                    target    = val
                    setup     = "A"
                elif opened_below_va:
                    # Type B: came from below VA, now inside -> LONG to VAH
                    direction = "long"
                    entry     = close
                    stop      = val - stop_buffer
                    target    = vah
                    setup     = "B"
                else:
                    # Type C: mid-session VA reclaim
                    mid_va = (val + vah) / 2.0
                    if close < mid_va:
                        direction = "long"
                        entry     = close
                        stop      = val - stop_buffer
                        target    = vah
                    else:
                        direction = "short"
                        entry     = close
                        stop      = vah + stop_buffer
                        target    = val
                    setup = "C"

                if abs(entry - target) < MIN_TARGET:
                    return None

                # Sanity check: stop on right side of entry
                if direction == "long"  and stop >= entry:
                    return None
                if direction == "short" and stop <= entry:
                    return None

                try:
                    global_idx = df.index.get_loc(ts)
                except Exception:
                    return None

                return VASignal(
                    direction=direction,
                    entry=entry,
                    stop=stop,
                    target=target,
                    setup_type=setup,
                    va_entry_edge=(vah if opened_above_va else val),
                    va_target_edge=(val if opened_above_va else vah),
                    signal_bar_idx=global_idx,
                )

        return None

    except Exception:
        return None
