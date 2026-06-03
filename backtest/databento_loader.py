"""
Databento historical NQ futures loader — 10-year 5-minute OHLCV.

Fetches NQ continuous front-month (NQ.c.0) 1-minute bars from
CME Globex (GLBX.MDP3), resamples to 5-minute, caches locally.

Cost: ~$12-13 one-time for 10 years of 1-minute data.
Subsequent runs use the local cache — zero additional cost.

Usage:
    from backtest.databento_loader import load_nq_databento
    df = load_nq_databento(years=10)   # returns 5-min DataFrame
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()
EST       = ZoneInfo("America/New_York")
CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_FILE = CACHE_DIR / "nq_5m_10yr.parquet"


def _fetch_from_databento(start: str, end: str) -> pd.DataFrame:
    """Download 1-min NQ continuous bars and resample to 5-min."""
    import databento as db

    key = os.getenv("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("DATABENTO_API_KEY not set in .env")

    client = db.Historical(key)

    print(f"\n{'='*60}")
    print(f"  Databento: downloading 10yr NQ 1-min bars")
    print(f"  Range : {start[:10]}  ->  {end[:10]}")
    print(f"  Cost  : ~$12 one-time  (cached after this, free to re-run)")
    print(f"{'='*60}")
    print("  Downloading... (30-60 seconds)", flush=True)

    data = client.timeseries.get_range(
        dataset="GLBX.MDP3",
        symbols=["NQ.c.0"],
        schema="ohlcv-1m",
        stype_in="continuous",
        start=start,
        end=end,
    )

    df1m = data.to_df()
    print(f"  Downloaded {len(df1m):,} 1-minute bars  ✓")

    if df1m.empty:
        raise RuntimeError("Databento returned empty DataFrame")

    # Databento ohlcv-1m: prices already in float dollars, index = ts_event (UTC)
    # Extra columns (rtype, publisher_id, etc.) are dropped — keep OHLCV only
    df1m = df1m.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    df1m = df1m[["Open", "High", "Low", "Close", "Volume"]].copy()

    # Ensure UTC DatetimeIndex
    if df1m.index.tz is None:
        df1m.index = df1m.index.tz_localize("UTC")
    else:
        df1m.index = df1m.index.tz_convert("UTC")

    df1m = df1m.dropna()

    # ── Resample 1-min -> 5-min ──────────────────────────────────────────────
    print("  Resampling 1-min -> 5-min...", flush=True)
    df5m = df1m.resample("5min", closed="left", label="left").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }).dropna(subset=["Open", "Close"])

    # Remove bars with zero volume or obviously bad prices
    df5m = df5m[df5m["Volume"] > 0]
    df5m = df5m[df5m["High"] >= df5m["Low"]]
    df5m = df5m[df5m["Close"] > 1000]

    print(f"  {len(df5m):,} 5-minute bars ready  ✓")
    return df5m


def load_nq_databento(years: int = 10, force_refresh: bool = False) -> pd.DataFrame:
    """
    Load 10-year NQ 5-min bars from Databento (cached locally).

    First call: downloads from Databento (~$12, ~30 seconds).
    Subsequent calls: loads from local parquet cache (instant, free).

    Returns DataFrame with UTC DatetimeIndex and OHLCV columns,
    compatible with existing backtest engine.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use cache if available and not forcing refresh
    if CACHE_FILE.exists() and not force_refresh:
        print(f"[DB] Loading from cache: {CACHE_FILE}")
        df = pd.read_parquet(CACHE_FILE)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        print(f"[DB] Cache loaded: {len(df):,} bars  "
              f"({df.index[0].date()} -> {df.index[-1].date()})")
        return df

    # Fetch from Databento
    # CME data requires end >= 2 days ago (Databento delayed-data policy)
    end   = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    start = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%dT%H:%M:%S")

    df = _fetch_from_databento(start, end)

    # Cache locally
    df.to_parquet(CACHE_FILE)
    size_mb = CACHE_FILE.stat().st_size / 1_048_576
    print(f"  Cached to .cache/nq_5m_10yr.parquet  ({size_mb:.1f} MB)  ✓")
    print(f"  Next run will load from cache instantly (free)\n")

    return df


def label_sessions_db(df: pd.DataFrame, interval: str = "5m") -> pd.DataFrame:
    """Same as data_loader.label_sessions but works on Databento data."""
    from backtest.data_loader import label_sessions
    return label_sessions(df, interval=interval)
