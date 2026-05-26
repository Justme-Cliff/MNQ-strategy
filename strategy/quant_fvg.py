"""
Fair Value Gap (FVG) — Institutional Imbalance Fills.

Research basis:
  Edgeful study on YM futures: 60-75% WR on FVG fills
  Advanced filtering (imbalance degree): >75% WR
  30-45% of FVGs produce no reaction — quality filtering is critical.

Why this works in ANY market regime:
  CRASH:    Large bearish FVGs form on the way down → short when price bounces into them
  RECOVERY: Large bullish FVGs form on the way up   → long when price dips into them
  SIDEWAYS: Smaller FVGs on both sides              → fade the FVG creation candle

Definition (3-candle imbalance):
  Bullish FVG: bar[i+2].Low > bar[i].High   (gap between bar 1 and bar 3 highs/lows)
  Bearish FVG: bar[i+2].High < bar[i].Low
  The "FVG zone" is the gap region that price skipped over.

Entry: when price RETURNS to test the FVG zone from outside.
  Bullish FVG: price drops into zone → enter LONG at zone top (bar[i].High)
  Bearish FVG: price rallies into zone → enter SHORT at zone bottom (bar[i].Low)

Target: 100% of gap width past the entry edge (conservative, full fill + equal extension).
Stop: just beyond the far edge of the FVG zone + buffer.

Quality filters:
  1. Min FVG size = max(3, atr × 0.015) — must be institutionally meaningful
  2. Max FVG size = atr × 0.25          — too wide = news spike, not institution
  3. FVG must be unfilled since creation
  4. Trend-aligned FVGs only:
       In bullish trend: only bullish FVGs (buy the dip into gap)
       In bearish trend: only bearish FVGs (sell the rally into gap)
       Neutral trend:    both directions (fade extremes)
  5. Only the HIGHEST-QUALITY (largest) unfilled FVG per direction per session
  6. Window: 9:45–11:30 ET (avoid opening chaos and end-of-morning fade)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import pandas as pd
from zoneinfo import ZoneInfo
from strategy.quant_regime import session_vwap

EST = ZoneInfo("America/New_York")

MAX_RISK_PTS = 25.0


@dataclass
class FVGZone:
    direction: str    # "bullish" or "bearish"
    zone_low: float   # bottom of the gap
    zone_high: float  # top of the gap
    zone_size: float  # zone_high - zone_low
    formed_at: int    # bar index when the 3rd candle closed (confirming the FVG)
    filled: bool = False


@dataclass
class FVGSignal:
    direction: str    # "long" (entering bullish FVG) or "short" (entering bearish FVG)
    entry: float
    stop: float
    target: float
    zone_low: float
    zone_high: float
    zone_size: float
    signal_bar_idx: int


def _detect_fvg_zones(
    today_df: pd.DataFrame,
    atr: float,
    trend_direction: str,  # "strong_bull"|"bull"|"neutral"|"bear"|"strong_bear"
) -> list[FVGZone]:
    """
    Scan today's bars for Fair Value Gap formations.
    Returns all valid (unfiltered-for-fills) FVG zones in chronological order.
    """
    min_size = max(12.0, atr * 0.06)  # at least 6% of ATR — institutions don't leave 6pt imbalances
    max_size = min(60.0, atr * 0.30)  # at most 30% of ATR — wider = news spike, not institution

    zones: list[FVGZone] = []
    bars = today_df.reset_index(drop=True)

    for i in range(len(bars) - 2):
        bar0_high = float(bars.loc[i,   "High"])
        bar0_low  = float(bars.loc[i,   "Low"])
        # bar1 is the "impulse" candle (we don't check it directly)
        bar2_high = float(bars.loc[i+2, "High"])
        bar2_low  = float(bars.loc[i+2, "Low"])

        # Bullish FVG: bar2.Low > bar0.High — gap above bar0
        if bar2_low > bar0_high:
            size = bar2_low - bar0_high
            if min_size <= size <= max_size:
                # Direction filter: in bearish trend, skip bullish FVGs
                if trend_direction in ("strong_bear",):
                    pass  # skip bullish FVGs in strongly bearish market
                else:
                    zones.append(FVGZone(
                        direction="bullish",
                        zone_low=bar0_high,
                        zone_high=bar2_low,
                        zone_size=size,
                        formed_at=i + 2,
                    ))

        # Bearish FVG: bar2.High < bar0.Low — gap below bar0
        elif bar2_high < bar0_low:
            size = bar0_low - bar2_high
            if min_size <= size <= max_size:
                # Direction filter: in bullish trend, skip bearish FVGs
                if trend_direction in ("strong_bull",):
                    pass  # skip bearish FVGs in strongly bullish market
                else:
                    zones.append(FVGZone(
                        direction="bearish",
                        zone_low=bar2_high,
                        zone_high=bar0_low,
                        zone_size=size,
                        formed_at=i + 2,
                    ))

    return zones


def detect(
    df: pd.DataFrame,
    today: date,
    atr: float,
    trend_direction: str = "neutral",
) -> Optional[FVGSignal]:
    """
    Detect the best FVG fill opportunity for today.
    Returns the first high-quality fill signal or None.

    atr: adaptive ATR for sizing filters.
    trend_direction: from classify_market_full()["ema_trend"]["direction"]
    """
    est_idx = df.index.tz_convert(EST)
    today_mask = est_idx.date == today
    today_df = df[today_mask].copy()

    if len(today_df) < 10:
        return None

    if atr <= 0:
        return None

    # Detect all FVG zones from today's bars (formed before we enter them)
    all_zones = _detect_fvg_zones(today_df, atr, trend_direction)

    if not all_zones:
        return None

    # Sort by zone_size descending — largest FVGs have highest institutional significance
    all_zones.sort(key=lambda z: z.zone_size, reverse=True)

    vwap_series = session_vwap(today_df)

    long_fired  = False
    short_fired = False

    # Walk forward through bars in the trading window
    for pos, (ts, row) in enumerate(today_df.iterrows()):
        dt = ts.astimezone(EST)
        mins = dt.hour * 60 + dt.minute

        if mins < 9 * 60 + 45:
            continue
        if mins >= 11 * 60 + 30:
            break

        close = float(row["Close"])
        high  = float(row["High"])
        low   = float(row["Low"])
        vwap_now = float(vwap_series.iloc[pos])

        # Check each FVG zone to see if price is currently testing it
        for zone in all_zones:
            # Zone must be FULLY FORMED before we can trade it
            # (the 3rd candle of the pattern must be complete before this bar)
            if zone.formed_at >= pos:
                continue

            # Mark zone as filled if price has passed through it
            if not zone.filled:
                if zone.direction == "bullish" and low < zone.zone_low:
                    zone.filled = True   # price broke below → gap filled / invalidated
                elif zone.direction == "bearish" and high > zone.zone_high:
                    zone.filled = True

            if zone.filled:
                continue

            # Entry condition: price is testing the FVG zone
            if zone.direction == "bullish" and not long_fired:
                # Bullish FVG: price dips INTO the zone → enter long
                if close <= zone.zone_high and high >= zone.zone_low:
                    if pos + 1 >= len(today_df):
                        break
                    entry_bar = today_df.iloc[pos + 1]
                    entry  = max(float(entry_bar["Open"]), zone.zone_low)
                    # Natural stop: below zone_low — if it would be capped, skip this trade
                    # (capped stop sits ABOVE zone_low, making the trade instantly fragile)
                    natural_stop = zone.zone_low - max(3.0, zone.zone_size * 0.3)
                    if entry - natural_stop > MAX_RISK_PTS:
                        continue
                    stop = natural_stop
                    # Target: zone_high + zone_size (100% extension past the zone)
                    target = zone.zone_high + zone.zone_size
                    if abs(entry - target) < 3.0:
                        continue
                    if entry >= target:
                        continue
                    long_fired = True
                    global_idx = df.index.get_loc(entry_bar.name)
                    zone.filled = True  # mark as used
                    return FVGSignal(
                        direction="long", entry=entry, stop=stop, target=target,
                        zone_low=zone.zone_low, zone_high=zone.zone_high,
                        zone_size=zone.zone_size, signal_bar_idx=global_idx,
                    )

            elif zone.direction == "bearish" and not short_fired:
                # Bearish FVG: price rallies INTO the zone → enter short
                if close >= zone.zone_low and low <= zone.zone_high:
                    if pos + 1 >= len(today_df):
                        break
                    entry_bar = today_df.iloc[pos + 1]
                    entry  = min(float(entry_bar["Open"]), zone.zone_high)
                    natural_stop = zone.zone_high + max(3.0, zone.zone_size * 0.3)
                    if natural_stop - entry > MAX_RISK_PTS:
                        continue
                    stop = natural_stop
                    target = zone.zone_low - zone.zone_size
                    if abs(entry - target) < 3.0:
                        continue
                    if entry <= target:
                        continue
                    short_fired = True
                    global_idx = df.index.get_loc(entry_bar.name)
                    zone.filled = True
                    return FVGSignal(
                        direction="short", entry=entry, stop=stop, target=target,
                        zone_low=zone.zone_low, zone_high=zone.zone_high,
                        zone_size=zone.zone_size, signal_bar_idx=global_idx,
                    )

        if long_fired and short_fired:
            break

    return None
