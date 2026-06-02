"""
COT Report — CFTC Commitment of Traders for NQ Futures.

Uses the Traders in Financial Futures (TFF) report — more granular than
the Legacy report for equity index futures. Tracks Leveraged Funds
(hedge funds, CTAs) net position as the primary signal.

Data: CFTC.gov free download, updated every Friday at 3:30 PM ET.
      Reflects positions as of prior Tuesday (3-day lag).

Edge (per research):
  COT Index > 90th pct (extreme net long):  contrarian SHORT warning.
  COT Index < 10th pct (extreme net short): contrarian LONG support.
  Effective lead time: 1-3 weeks (weekly regime context, NOT intraday).

Speed: data cached to disk, re-downloaded at most once per week.
       Zero network calls during signal evaluation.
"""
from __future__ import annotations
import io
import json
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

CACHE_DIR  = Path.home() / ".cache" / "tjrbot"
CACHE_FILE = CACHE_DIR / "cot_nq.json"
NQ_KEYWORD = "NASDAQ MINI"
COT_EXTREME_HIGH = 90.0   # COT Index above this = crowded long = bearish warning
COT_EXTREME_LOW  = 10.0   # COT Index below this = panic short = bullish support


def _cftc_url(year: int) -> str:
    return f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"


def _download_year(year: int) -> Optional[pd.DataFrame]:
    """Download and parse one year of CFTC TFF futures-only data."""
    try:
        resp = requests.get(_cftc_url(year), timeout=30)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            fname = z.namelist()[0]
            raw   = z.read(fname)
        df = pd.read_csv(io.BytesIO(raw), low_memory=False)
        return df
    except Exception:
        return None


def _load_nq_cot_raw(years: int = 2) -> Optional[pd.DataFrame]:
    """Download last N years of TFF data and filter for NQ."""
    current_year = date.today().year
    frames = []
    for y in range(current_year - years + 1, current_year + 1):
        df = _download_year(y)
        if df is not None:
            frames.append(df)
    if not frames:
        return None

    all_data = pd.concat(frames, ignore_index=True)

    # Filter for NQ
    name_col = None
    for col in ["Market_and_Exchange_Names", "Market and Exchange Names"]:
        if col in all_data.columns:
            name_col = col
            break
    if name_col is None:
        return None

    nq = all_data[all_data[name_col].str.contains(NQ_KEYWORD, na=False)].copy()
    if nq.empty:
        return None

    # Find date column
    date_col = None
    for col in ["Report_Date_as_YYYY-MM-DD", "Report Date as of Date in Year-Month-Day"]:
        if col in nq.columns:
            date_col = col
            break
    if date_col is None:
        return None

    nq["report_date"] = pd.to_datetime(nq[date_col], errors="coerce").dt.date

    # Leveraged funds columns
    long_col  = "Lev_Money_Positions_Long_All"
    short_col = "Lev_Money_Positions_Short_All"
    missing   = [c for c in [long_col, short_col] if c not in nq.columns]
    if missing:
        return None

    nq = nq[["report_date", long_col, short_col]].copy()
    nq.columns = ["report_date", "lev_long", "lev_short"]
    nq["net"] = pd.to_numeric(nq["lev_long"], errors="coerce") - \
                pd.to_numeric(nq["lev_short"], errors="coerce")
    nq = nq.dropna(subset=["net"]).sort_values("report_date")
    return nq[["report_date", "net"]].reset_index(drop=True)


def _cache_is_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    mtime = CACHE_FILE.stat().st_mtime
    age_days = (date.today().toordinal() - date.fromtimestamp(mtime).toordinal())
    return age_days < 7


def _load_cache() -> Optional[pd.DataFrame]:
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
        return df
    except Exception:
        return None


def _save_cache(df: pd.DataFrame) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        rows = [{"report_date": str(r["report_date"]), "net": float(r["net"])}
                for _, r in df.iterrows()]
        with open(CACHE_FILE, "w") as f:
            json.dump(rows, f)
    except Exception:
        pass


def _get_nq_cot() -> Optional[pd.DataFrame]:
    """Load COT data from cache or CFTC download."""
    if _cache_is_fresh():
        df = _load_cache()
        if df is not None:
            return df

    df = _load_nq_cot_raw(years=2)
    if df is not None:
        _save_cache(df)
    return df


def _cot_index(series: pd.Series, window: int = 52) -> pd.Series:
    """
    Rolling percentile rank over `window` observations.
    Returns 0–100 where 100 = highest net long in the window.
    """
    def pct_rank(x):
        if len(x) < 5:
            return 50.0
        mn, mx = x.min(), x.max()
        if mx == mn:
            return 50.0
        return (x.iloc[-1] - mn) / (mx - mn) * 100.0

    return series.rolling(window, min_periods=5).apply(pct_rank, raw=False)


def get_cot_bias(today: date, _df: Optional[pd.DataFrame] = None) -> dict:
    """
    Weekly COT bias for NQ as of the most recent report before `today`.

    Returns:
      net_position : int   — leveraged funds net long/short contracts
      cot_index    : float — 0-100 percentile vs 52-week range
      bias         : "extreme_long" | "extreme_short" | "neutral"
      long_ok      : bool  — True unless crowded long
      short_boost  : bool  — True if shorts have contrarian COT support
      available    : bool
    """
    default = {
        "net_position": 0, "cot_index": 50.0, "bias": "neutral",
        "long_ok": True, "short_boost": False, "available": False,
    }

    try:
        df = _df if _df is not None else _get_nq_cot()
        if df is None or df.empty:
            return default

        past = df[df["report_date"] < today]
        if past.empty:
            return default

        idx = _cot_index(past["net"].reset_index(drop=True))
        cot_val  = float(idx.iloc[-1])
        net_pos  = int(past["net"].iloc[-1])

        if cot_val > COT_EXTREME_HIGH:
            bias       = "extreme_long"
            long_ok    = False    # crowded long = fade risk
            short_boost = True
        elif cot_val < COT_EXTREME_LOW:
            bias       = "extreme_short"
            long_ok    = True     # institutions panic-short = contrarian long
            short_boost = False
        else:
            bias       = "neutral"
            long_ok    = True
            short_boost = False

        return {
            "net_position": net_pos,
            "cot_index":    cot_val,
            "bias":         bias,
            "long_ok":      long_ok,
            "short_boost":  short_boost,
            "available":    True,
        }

    except Exception:
        return default


# Module-level cache
_cot_df_cache: Optional[pd.DataFrame] = None


def load_cot_data() -> Optional[pd.DataFrame]:
    """Load and cache COT DataFrame for the session."""
    global _cot_df_cache
    if _cot_df_cache is None:
        _cot_df_cache = _get_nq_cot()
    return _cot_df_cache
