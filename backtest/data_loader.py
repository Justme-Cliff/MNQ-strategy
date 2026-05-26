"""
Load historical MNQ proxy data via yfinance (NQ=F).
NQ and MNQ have the same price — we scale P&L by $2/point (MNQ).

yfinance limits:
  1m  → last 7 days
  5m  → last 60 days
  1h  → last 730 days
"""
from __future__ import annotations
import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")


def load_nq(interval: str = "5m", period: str = "60d") -> pd.DataFrame:
    """
    Download NQ futures 5-minute bars.
    Returns DataFrame with DatetimeIndex (UTC) and standard OHLCV columns.
    """
    ticker = yf.Ticker("MNQ=F")  # same price as NQ=F; NQ=F intermittently delisted on yfinance
    df = ticker.history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        raise RuntimeError(f"yfinance returned no data for NQ=F ({period}/{interval})")

    # Ensure UTC index
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # Validate OHLC integrity — corrupt yfinance bars can fire false signals
    bad_hl = (df["High"] < df["Low"]).sum()
    if bad_hl > 0:
        df = df[df["High"] >= df["Low"]]
    nan_ohlc = df[["Open", "High", "Low", "Close"]].isna().any(axis=1).sum()
    if nan_ohlc > 0:
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

    return df


def load_es(interval: str = "5m", period: str = "60d") -> pd.DataFrame:
    """
    Download ES futures 5-minute bars (MES=F proxy).
    Used for ES/NQ lead-lag confirmation.
    Returns empty DataFrame on failure — caller must handle gracefully.
    """
    try:
        ticker = yf.Ticker("MES=F")
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df
    except Exception:
        return pd.DataFrame()


def load_daily_closes(ticker: str = "MNQ=F", period: str = "90d") -> "pd.Series":
    """
    Download daily closing prices for HMM / HAR-RV training.
    Returns a pd.Series indexed by date.
    """
    try:
        data = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if data.empty:
            return pd.Series(dtype=float)
        closes = data["Close"]
        closes.index = [ts.date() if hasattr(ts, "date") else ts for ts in closes.index]
        return closes
    except Exception:
        return pd.Series(dtype=float)


def _nyse_holidays() -> set:
    """Return a set of NYSE holiday dates using pandas holiday calendar."""
    try:
        from pandas.tseries.holiday import USFederalHolidayCalendar
        cal = USFederalHolidayCalendar()
        holidays = cal.holidays(
            start=pd.Timestamp("2020-01-01"),
            end=pd.Timestamp("2030-12-31"),
        )
        return set(d.date() for d in holidays)
    except Exception:
        return set()


def label_sessions(df: pd.DataFrame, interval: str = "5m") -> pd.DataFrame:
    """Add EST hour/minute columns and session label flags.

    For 1h bars the 9:00 AM bar represents 9:00-10:00 AM (covers the NY open),
    so we start the trade window at 9:00 instead of 9:30 to avoid missing it.
    """
    df = df.copy()
    est_idx = df.index.tz_convert(EST)
    df["est_hour"]   = est_idx.hour
    df["est_minute"] = est_idx.minute
    df["est_date"]   = est_idx.date

    h, m = df["est_hour"], df["est_minute"]
    minutes = h * 60 + m

    # 1h bar at 9:00 AM already represents the 9:30 AM open — include it
    trade_start = 9 * 60 if interval == "1h" else 9 * 60 + 30

    # NYSE holiday check: mark holiday bars as non-tradeable
    holidays = _nyse_holidays()
    is_holiday = pd.Series(
        [d in holidays for d in df["est_date"]], index=df.index
    )

    df["in_asia"]         = (h >= 20) | (h == 0)   # 8 PM – midnight (hour 0 = 12 AM bar)
    df["in_ny"]           = (minutes >= 9 * 60 + 30) & (minutes < 16 * 60) & ~is_holiday
    df["in_am_window"]    = (minutes >= trade_start) & (minutes < 12 * 60) & ~is_holiday
    df["in_pm_window"]    = (minutes >= 13 * 60 + 30) & (minutes < 16 * 60) & ~is_holiday
    # 1h bars: extend trade window to full RTH (9 AM–4 PM) so PM MSS confirmations are visible
    if interval == "1h":
        df["in_trade_window"] = (minutes >= trade_start) & (minutes < 16 * 60) & ~is_holiday
    else:
        df["in_trade_window"] = df["in_am_window"] | df["in_pm_window"]

    return df
