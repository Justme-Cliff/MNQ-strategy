"""
Detects and stores the Asia session high/low for each trading date.
Asia session: 8:00 PM – 12:00 AM EST (spans two calendar days).
The range produced belongs to the NEXT day's NY session.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

EST = ZoneInfo("America/New_York")


def _trading_date_for_asia_bar(bar_dt: datetime) -> date:
    """
    Given a bar timestamp in the Asia session (8 PM – midnight),
    return the NY trading date this range belongs to.
    E.g., Monday 9 PM → Tuesday's trading date.
    """
    dt_est = bar_dt.astimezone(EST)
    if dt_est.hour >= 20:
        return (dt_est + timedelta(days=1)).date()
    return dt_est.date()


def build_asia_ranges(df: pd.DataFrame) -> dict[date, dict]:
    """
    Process a DataFrame with DatetimeIndex (UTC or tz-aware) and OHLCV columns.
    Returns: {trading_date: {"high": float, "low": float}}
    """
    ranges: dict[date, dict] = {}

    for ts, row in df.iterrows():
        if isinstance(ts, pd.Timestamp):
            bar_dt = ts.to_pydatetime()
        else:
            bar_dt = ts

        if bar_dt.tzinfo is None:
            bar_dt = bar_dt.replace(tzinfo=ZoneInfo("UTC"))

        dt_est = bar_dt.astimezone(EST)
        hour = dt_est.hour

        in_asia = hour >= 20 or hour < 0  # 8 PM → midnight
        if not in_asia:
            continue

        tdate = _trading_date_for_asia_bar(bar_dt)
        high = float(row["High"]) if "High" in row else float(row["high"])
        low = float(row["Low"]) if "Low" in row else float(row["low"])

        if tdate not in ranges:
            ranges[tdate] = {"high": high, "low": low}
        else:
            ranges[tdate]["high"] = max(ranges[tdate]["high"], high)
            ranges[tdate]["low"] = min(ranges[tdate]["low"], low)

    return ranges


class AsiaRangeLive:
    """
    Stateful tracker for live trading — call update() on each new bar.
    """

    def __init__(self):
        self._ranges: dict[date, dict] = {}
        self._today: date | None = None

    def update(self, bar_dt: datetime, high: float, low: float) -> None:
        if bar_dt.tzinfo is None:
            bar_dt = bar_dt.replace(tzinfo=ZoneInfo("UTC"))
        dt_est = bar_dt.astimezone(EST)
        hour = dt_est.hour

        if not (hour >= 20 or hour < 0):
            return

        tdate = _trading_date_for_asia_bar(bar_dt)
        if tdate not in self._ranges:
            self._ranges[tdate] = {"high": high, "low": low}
        else:
            self._ranges[tdate]["high"] = max(self._ranges[tdate]["high"], high)
            self._ranges[tdate]["low"] = min(self._ranges[tdate]["low"], low)

    def get(self, trading_date: date) -> dict | None:
        return self._ranges.get(trading_date)

    def get_today(self) -> dict | None:
        from datetime import date as _date
        return self.get(_date.today())
