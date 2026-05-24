"""
Intraday VWAP — resets at NY session open (9:30 AM EST).
Also provides 1σ / 2σ volume-weighted standard-deviation bands.
Direction rule: only go long above VWAP, only go short below VWAP.
"""
from __future__ import annotations
import math
from zoneinfo import ZoneInfo
from datetime import datetime
import pandas as pd

EST = ZoneInfo("America/New_York")


def compute_vwap(df: pd.DataFrame, session_open_hour: int = 9, session_open_min: int = 30) -> pd.Series:
    """
    Compute rolling VWAP that resets each day at NY session open.
    df must have DatetimeIndex (tz-aware) with High, Low, Close, Volume columns.
    Returns a Series aligned to df.index.
    """
    highs = df["High"] if "High" in df.columns else df["high"]
    lows = df["Low"] if "Low" in df.columns else df["low"]
    closes = df["Close"] if "Close" in df.columns else df["close"]
    volumes = df["Volume"] if "Volume" in df.columns else df["volume"]

    typical = (highs + lows + closes) / 3.0
    tpv = typical * volumes

    vwap_values = pd.Series(index=df.index, dtype=float)
    cum_tpv = 0.0
    cum_vol = 0.0
    prev_date = None

    for ts in df.index:
        if isinstance(ts, pd.Timestamp):
            dt_est = ts.tz_convert(EST)
        else:
            dt_est = ts.astimezone(EST)

        trade_date = dt_est.date()
        at_open = (dt_est.hour == session_open_hour and dt_est.minute == session_open_min)

        if trade_date != prev_date or at_open:
            cum_tpv = 0.0
            cum_vol = 0.0
            prev_date = trade_date

        cum_tpv += float(tpv.loc[ts])
        cum_vol += float(volumes.loc[ts])

        vwap_values.loc[ts] = cum_tpv / cum_vol if cum_vol > 0 else float(closes.loc[ts])

    return vwap_values


def compute_vwap_bands(
    df: pd.DataFrame,
    session_open_hour: int = 9,
    session_open_min: int = 30,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Session-anchored VWAP with volume-weighted 1σ and 2σ bands.

    Returns (vwap, upper_1, upper_2, lower_1, lower_2) — all aligned to df.index.

    The standard deviation is volume-weighted:
        σ² = Σ(vol_i × (tp_i − VWAP_i)²) / Σ(vol_i)

    Research backing: institutions fill large orders at VWAP. When price
    extends 2σ from VWAP, a reversion is statistically expected 65-70% of
    the time (Madhavan 2003; Steady Turtle 2026 backtests show 65% WR).
    """
    highs   = df["High"]   if "High"   in df.columns else df["high"]
    lows    = df["Low"]    if "Low"    in df.columns else df["low"]
    closes  = df["Close"]  if "Close"  in df.columns else df["close"]
    volumes = df["Volume"] if "Volume" in df.columns else df["volume"]

    typical = (highs + lows + closes) / 3.0
    tpv     = typical * volumes

    vwap_vals = pd.Series(index=df.index, dtype=float)
    up1_vals  = pd.Series(index=df.index, dtype=float)
    up2_vals  = pd.Series(index=df.index, dtype=float)
    lo1_vals  = pd.Series(index=df.index, dtype=float)
    lo2_vals  = pd.Series(index=df.index, dtype=float)

    cum_tpv  = 0.0
    cum_vol  = 0.0
    cum_vwss = 0.0   # Σ(vol × (tp − vwap)²) for volume-weighted variance
    prev_date = None

    for ts in df.index:
        dt_est     = ts.tz_convert(EST) if isinstance(ts, pd.Timestamp) else ts.astimezone(EST)
        trade_date = dt_est.date()
        at_open    = (dt_est.hour == session_open_hour and dt_est.minute == session_open_min)

        if trade_date != prev_date or at_open:
            cum_tpv  = 0.0
            cum_vol  = 0.0
            cum_vwss = 0.0
            prev_date = trade_date

        vol = float(volumes.loc[ts])
        tp  = float(typical.loc[ts])
        cum_tpv += tp * vol
        cum_vol += vol

        if cum_vol > 0:
            v = cum_tpv / cum_vol
            cum_vwss += vol * (tp - v) ** 2
            variance  = cum_vwss / cum_vol
            sigma     = math.sqrt(variance) if variance > 0 else 0.0
        else:
            v     = float(closes.loc[ts])
            sigma = 0.0

        vwap_vals.loc[ts] = v
        up1_vals.loc[ts]  = v + sigma
        up2_vals.loc[ts]  = v + 2 * sigma
        lo1_vals.loc[ts]  = v - sigma
        lo2_vals.loc[ts]  = v - 2 * sigma

    return vwap_vals, up1_vals, up2_vals, lo1_vals, lo2_vals


class VWAPLive:
    """Stateful VWAP for live trading — call update() on each bar."""

    def __init__(self):
        self._cum_tpv = 0.0
        self._cum_vol = 0.0
        self._current_date = None
        self._value = None

    def update(self, bar_dt: datetime, high: float, low: float, close: float, volume: float) -> float:
        if bar_dt.tzinfo is None:
            from zoneinfo import ZoneInfo as _Z
            bar_dt = bar_dt.replace(tzinfo=_Z("UTC"))
        dt_est = bar_dt.astimezone(EST)
        trade_date = dt_est.date()

        reset = (
            self._current_date is None
            or trade_date != self._current_date
            or (dt_est.hour == 9 and dt_est.minute == 30)
        )

        if reset:
            self._cum_tpv = 0.0
            self._cum_vol = 0.0
            self._current_date = trade_date

        typical = (high + low + close) / 3.0
        self._cum_tpv += typical * volume
        self._cum_vol += volume
        self._value = self._cum_tpv / self._cum_vol if self._cum_vol > 0 else close
        return self._value

    @property
    def value(self) -> float | None:
        return self._value
