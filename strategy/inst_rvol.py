"""
RVOL — Relative Volume (Time-of-Day Adjusted).

Compares the current 5-min bar's volume to the historical average for the
same 5-minute slot across the prior 20 sessions.

Research:
  RVOL 1.5-2.0x (sweet spot): 58.8% three-day follow-through on breakouts
  RVOL > 2.0x (extreme):       53.4% follow-through, 43.8% next-day (watch for exhaustion)
  RVOL < 0.8x:                 40% follow-through — low-participation moves reliably fail

The time-of-day adjustment is critical for NQ: the 9:30 bar always has 5-10x
the volume of the 11:00 bar. Flat session averages produce meaningless RVOL.
This compares the current bar to the SAME slot on prior sessions.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import date
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")


def _rvol_default() -> dict:
    return {
        "rvol":         1.0,
        "current_vol":  0.0,
        "hist_avg_vol": 0.0,
        "regime":       "normal",
        "confirmation": False,
        "exhaustion":   False,
        "available":    False,
    }


def compute_rvol(
    df: pd.DataFrame,
    today: date,
    bar_pos: int,
    lookback_sessions: int = 20,
) -> dict:
    """
    Time-of-day adjusted Relative Volume.
    bar_pos: 0-based index within today's RTH bars.

    Returns:
      rvol          : float  — current_vol / historical_avg_same_slot
      current_vol   : float
      hist_avg_vol  : float
      regime        : "climax" | "high" | "normal" | "thin"
      confirmation  : bool — True if RVOL 1.5-2.5 (institutional participation)
      exhaustion    : bool — True if RVOL > 3.0 (potential climax reversal)
      available     : bool
    """
    try:
        est_idx = df.index.tz_convert(EST)
        today_mask = est_idx.date == today
        today_bars = df[today_mask]

        if bar_pos < 0 or bar_pos >= len(today_bars):
            return _rvol_default()

        current_ts  = today_bars.index[bar_pos].astimezone(EST)
        slot_hour   = current_ts.hour
        slot_min    = current_ts.minute
        current_vol = float(today_bars.iloc[bar_pos]["Volume"])

        all_dates = sorted(set(d for d in est_idx.date if d < today))
        if len(all_dates) < 5:
            return _rvol_default()

        slot_vols = []
        for session_date in all_dates[-lookback_sessions:]:
            sess = df[est_idx.date == session_date]
            if sess.empty:
                continue
            sess_est = sess.index.tz_convert(EST)
            slot_mask = (sess_est.hour == slot_hour) & (sess_est.minute == slot_min)
            slot_bars = sess[slot_mask]
            if not slot_bars.empty:
                slot_vols.append(float(slot_bars.iloc[0]["Volume"]))

        if len(slot_vols) < 5:
            return _rvol_default()

        hist_avg = float(np.mean(slot_vols))
        if hist_avg < 1.0:
            return _rvol_default()

        rvol = current_vol / hist_avg

        if rvol > 3.0:
            regime = "climax"
        elif rvol > 1.5:
            regime = "high"
        elif rvol > 0.8:
            regime = "normal"
        else:
            regime = "thin"

        return {
            "rvol":         rvol,
            "current_vol":  current_vol,
            "hist_avg_vol": hist_avg,
            "regime":       regime,
            "confirmation": 1.5 <= rvol <= 2.5,
            "exhaustion":   rvol > 3.0,
            "available":    True,
        }

    except Exception:
        return _rvol_default()
