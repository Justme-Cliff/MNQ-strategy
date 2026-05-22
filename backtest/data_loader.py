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
    ticker = yf.Ticker("NQ=F")
    df = ticker.history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        raise RuntimeError(f"yfinance returned no data for NQ=F ({period}/{interval})")

    # Ensure UTC index
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df


def label_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Add EST hour/minute columns and session label flags."""
    df = df.copy()
    est_idx = df.index.tz_convert(EST)
    df["est_hour"]   = est_idx.hour
    df["est_minute"] = est_idx.minute
    df["est_date"]   = est_idx.date

    h, m = df["est_hour"], df["est_minute"]
    minutes = h * 60 + m

    df["in_asia"] = (h >= 20) | (h < 0)          # 8 PM – midnight
    df["in_ny"]   = (minutes >= 9 * 60 + 30) & (minutes < 16 * 60)
    df["in_trade_window"] = (minutes >= 9 * 60 + 30) & (minutes < 11 * 60 + 30)

    return df
