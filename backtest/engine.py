"""
Backtest engine — replays 15-minute MNQ bars through the full strategy pipeline.

Assumptions:
  - Limit orders fill at the entry price (no slippage)
  - Stop loss fills at stop price (no slippage on gaps)
  - TP1 at 1:1 → move stop to break-even
  - TP2 at flexible RR (3:1–5:1, setup-aware)
  - P&L uses MNQ = $2/point * contracts
  - Max 2 trades per day, max $100 risk per day
  - Trade window: 9:30 AM – noon EST

Reference levels monitored (same sweep + MSS mechanic):
  - Asia session H/L         (threshold_boost=0, min_depth=15 pts on 15m)
  - PDH/PDL                  (threshold_boost=+1, min_depth=15 pts)
  - Previous PM range H/L    (threshold_boost=varies)
  - London carry-over        (Asia state pre-initialized when London swept 25+ pts)
  - Pre-market 8:00-9:25 AM  (Judas Swing — 15m only)
  - Weekly H/L               (1h only)
  - NY Midnight Range        (1h only)

RR is computed per-trade via quant_signals.compute_trade_rr:
  base 3:1 → upgraded by score, signal type, day of week, and quant bonus.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import yfinance as yf

from backtest.data_loader import load_nq, label_sessions
from strategy.asia_range import build_asia_ranges
from strategy.fvg_detector import find_fvgs, get_active_fvg
from strategy.mss_detector import detect_mss
from strategy.vwap import compute_vwap, compute_vwap_bands
from strategy.confluence_scorer import score_setup
from strategy.london_session import get_london_action, is_london_aligned
from strategy.order_block import find_order_block
from strategy.smart_filter import SmartFilter
from strategy.market_context import (
    get_weekly_levels,
    check_smt_divergence,
    check_news_calendar,
    compute_ote_zone,
    price_in_ote,
)
from risk.position_sizer import calculate_size, calculate_targets
from strategy.quant_signals import quant_bonus_score, compute_trade_rr
from config import (
    MIN_CONFLUENCE_SCORE,
    MAX_TRADES_PER_DAY,
    MAX_DAILY_LOSS,
    MAX_STOP_POINTS,
    MNQ_DOLLARS_PER_POINT,
    STARTING_BALANCE,
    TRAILING_MAX_DRAWDOWN,
    TRADE_END_HOUR,
    TRADE_END_MIN,
    SWEEP_TIMEOUT_MINUTES,
    BACKTEST_INTERVAL,
)

EST = ZoneInfo("America/New_York")


# ── SweepState ─────────────────────────────────────────────────────────────────

class SweepState:
    """
    Tracks sweep + MSS detection for one (signal_dir, level_type) pair.
    Created fresh each trading day. Handles Asia, PDH/PDL, and PM-range sweeps
    with the same logic — only threshold_boost and min_depth differ.
    """

    __slots__ = (
        "signal_dir", "level_type", "threshold_boost", "min_depth", "max_depth",
        "starts_at_mins", "expires_at_mins",
        "ref_level", "done", "bar_idx", "detected_at", "depth",
        "sweep_extreme", "mss_confirmed", "mss_strong", "mss_bar_idx",
        "smt_result", "ote_zone", "trade_fired",
    )

    def __init__(
        self,
        signal_dir: str,         # "long" | "short"
        level_type: str,         # "asia" | "pdh_pdl" | "pm_range"
        threshold_boost: int = 0,
        min_depth: float = 25.0,
        max_depth: float = 80.0,
        starts_at_mins: int = 9 * 60 + 30,   # Don't detect sweep before this time
        expires_at_mins: int = 12 * 60,       # Hard stop for MSS entry (minutes into day)
    ):
        self.signal_dir       = signal_dir
        self.level_type       = level_type
        self.threshold_boost  = threshold_boost
        self.min_depth        = min_depth
        self.max_depth        = max_depth
        self.starts_at_mins   = starts_at_mins
        self.expires_at_mins  = expires_at_mins
        self.ref_level: float = 0.0
        self._clear()

    def _clear(self):
        self.done              = False
        self.bar_idx: int | None = None
        self.detected_at: datetime | None = None
        self.depth: float      = 0.0
        self.sweep_extreme: float = 0.0
        self.mss_confirmed     = False
        self.mss_strong        = False
        self.mss_bar_idx: int | None = None
        self.smt_result        = {"confirmed": True, "divergent": False}
        self.ote_zone: dict    = {"valid": False}
        self.trade_fired       = False

    def full_reset(self, ref_level: float = 0.0):
        self.ref_level = ref_level
        self._clear()

    def timeout_reset(self):
        """Clear sweep state but keep ref_level — allows re-detection of same level."""
        ref = self.ref_level
        self._clear()
        self.ref_level = ref

    @property
    def mss_dir(self) -> str:
        """Direction string expected by detect_mss ("bullish" / "bearish")."""
        return "bullish" if self.signal_dir == "long" else "bearish"


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    date: date
    direction: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    exit_price: float
    contracts: int
    pnl: float
    score: int
    outcome: str          # "WIN_TP2", "WIN_TP1_BE", "LOSS", "TIMEOUT"
    reason: str           # confluence breakdown
    signal_hour: int = 9
    day_of_week: int = 0  # 0=Mon, 4=Fri
    sweep_depth: float = 0.0
    asia_range_width: float = 0.0
    # Context fields
    vix_regime: str = "unknown"
    smt_confirmed: bool = True
    ote_used: bool = False
    news_penalty: int = 0
    setup_mode: str = "normal"    # normal | judas_reversal | post_claims
    level_type: str = "asia"      # asia | pdh_pdl | pm_range | weekly | midnight | premarket
    rr: float = 3.0               # actual RR target used for this trade
    quant_bonus: int = 0          # 0–3 quant scoring points that upgraded the RR


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    daily_pnl: dict = field(default_factory=dict)


# ── Pre-computation helpers ────────────────────────────────────────────────────

def _build_prev_day_levels(df: pd.DataFrame) -> dict:
    """Previous trading day full-session H/L/close keyed by the NEXT trading date."""
    est_idx = df.index.tz_convert(EST)
    daily: dict = {}
    for i, ts in enumerate(est_idx):
        d = ts.date()
        h = float(df["High"].iloc[i])
        l = float(df["Low"].iloc[i])
        c = float(df["Close"].iloc[i])
        mins = ts.hour * 60 + ts.minute
        if 9 * 60 + 30 <= mins < 16 * 60:
            if d not in daily:
                daily[d] = {"high": h, "low": l, "close": c}
            else:
                daily[d]["high"]  = max(daily[d]["high"], h)
                daily[d]["low"]   = min(daily[d]["low"],  l)
                daily[d]["close"] = c  # always overwrite → last RTH bar
    dates = sorted(daily.keys())
    return {dates[i]: daily[dates[i - 1]] for i in range(1, len(dates))}


def _build_pm_range_levels(df: pd.DataFrame) -> dict:
    """Previous PM session (1:30–4 PM) H/L keyed by the NEXT trading date."""
    est_idx = df.index.tz_convert(EST)
    daily: dict = {}
    for i, ts in enumerate(est_idx):
        d = ts.date()
        h = float(df["High"].iloc[i])
        l = float(df["Low"].iloc[i])
        mins = ts.hour * 60 + ts.minute
        if 13 * 60 + 30 <= mins < 16 * 60:
            if d not in daily:
                daily[d] = {"high": h, "low": l}
            else:
                daily[d]["high"] = max(daily[d]["high"], h)
                daily[d]["low"]  = min(daily[d]["low"],  l)
    dates = sorted(daily.keys())
    return {dates[i]: daily[dates[i - 1]] for i in range(1, len(dates))}


def _build_midnight_levels(df: pd.DataFrame) -> dict:
    """NY Midnight range (00:00–03:00 EST) H/L keyed by that same calendar date.

    ICT concept: the 00:00 NY candle creates the 'New York Midnight Open Range' (NYMOR).
    When RTH price sweeps below the midnight low or above the midnight high, price has
    grabbed liquidity from overnight participants and the institutional reversal trade fires.
    """
    est_idx = df.index.tz_convert(EST)
    daily: dict = {}
    for i, ts in enumerate(est_idx):
        d = ts.date()
        h = float(df["High"].iloc[i])
        l = float(df["Low"].iloc[i])
        mins = ts.hour * 60 + ts.minute
        if 0 <= mins < 3 * 60:
            if d not in daily:
                daily[d] = {"high": h, "low": l}
            else:
                daily[d]["high"] = max(daily[d]["high"], h)
                daily[d]["low"]  = min(daily[d]["low"],  l)
    return daily


def _build_premarket_levels(df: pd.DataFrame) -> dict:
    """Pre-RTH range (8:00–9:25 AM EST) H/L keyed by that calendar date.

    The 90-minute pre-market window is the final institutional accumulation / stop-hunt
    before the NY open. When RTH price sweeps below the pre-market low or above the
    pre-market high, it confirms a Judas Swing — the fake open direction — and the
    reversal trade sets up. Works on 5m bars; skipped for 1h (no sub-hourly resolution).
    """
    est_idx = df.index.tz_convert(EST)
    daily: dict = {}
    for i, ts in enumerate(est_idx):
        d = ts.date()
        h = float(df["High"].iloc[i])
        l = float(df["Low"].iloc[i])
        mins = ts.hour * 60 + ts.minute
        if 8 * 60 <= mins < 9 * 60 + 25:
            if d not in daily:
                daily[d] = {"high": h, "low": l}
            else:
                daily[d]["high"] = max(daily[d]["high"], h)
                daily[d]["low"]  = min(daily[d]["low"],  l)
    return daily


def _build_vix_cache(period: str = "60d") -> dict:
    """VIX daily history → date-keyed regime dict."""
    try:
        df = yf.Ticker("^VIX").history(period=period, interval="1d", auto_adjust=True)
        if df.empty:
            return {}
        cache = {}
        for ts, row in df.iterrows():
            vix = float(row["Close"])
            if vix < 15:
                regime, penalty = "low", 0
            elif vix < 20:
                regime, penalty = "medium", 0
            elif vix < 25:
                regime, penalty = "high", 1
            elif vix < 30:
                regime, penalty = "very_high", 3
            else:
                regime, penalty = "extreme", 3
            d = ts.date() if hasattr(ts, "date") else ts.to_pydatetime().date()
            cache[d] = {"vix": round(vix, 2), "regime": regime, "score_penalty": penalty}
        return cache
    except Exception:
        return {}


def _get_es_data(period: str = "60d", interval: str = "5m") -> pd.DataFrame | None:
    """ES futures data for SMT divergence checks."""
    try:
        df = yf.Ticker("ES=F").history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return None
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(EST)
        return df
    except Exception:
        return None


def _swing_origin(df: pd.DataFrame, sweep_bar: int, direction: str, lookback: int = 30) -> float:
    """Highest high (long) or lowest low (short) in lookback bars before sweep."""
    start = max(0, sweep_bar - lookback)
    if direction == "long":
        return float(df["High"].iloc[start:sweep_bar].max()) if sweep_bar > start else float(df["High"].iloc[sweep_bar])
    else:
        return float(df["Low"].iloc[start:sweep_bar].min()) if sweep_bar > start else float(df["Low"].iloc[sweep_bar])


# ── Day sweep-state factory ────────────────────────────────────────────────────

def _build_day_sweep_states(
    ar: dict | None,
    pdl_lvls: dict | None,
    pm_lvls: dict | None,
    london_action: dict,
    trade_date,
    interval: str = "5m",
    weekly_lvls: dict | None = None,
    midnight_lvls: dict | None = None,
    premarket_lvls: dict | None = None,
) -> list[SweepState]:
    """
    Build all SweepState objects for a trading day.
    Up to 10 states: Asia, PDH/PDL, PM-range (1h only), PWH/PWL, midnight range.
    London carry-over pre-initializes Asia states when London swept 25+ pts.

    For 1h bars the 9 AM bar represents 9:00-10:00 AM (covers the NY open), so
    starts_at_mins drops to 9*60 and max_depth is uncapped (1h ranges are naturally large).
    """
    states: list[SweepState] = []
    asia_low  = ar["low"]  if ar else None
    asia_high = ar["high"] if ar else None

    is_hourly = (interval == "1h")
    is_15m    = (interval == "15m")

    # 1h bars: the 9 AM bar covers 9:00-10:00 AM — lower the start gate.
    # 15m and 5m bars: first bar starts at 9:30 AM exactly.
    starts_ny = 9 * 60 if is_hourly else 9 * 60 + 30

    # Sweep depth windows scale with timeframe.
    # 15m: minimum 15 pts (8 pts is too tight for a 15-minute bar's natural range).
    # 5m:  minimum 8 pts (original calibration).
    # 1h:  uncapped (hourly ranges naturally exceed 80 pts in volatile sessions).
    asia_min_d = 15.0 if is_15m else 8.0
    sec_min_d  = 15.0 if is_15m else 8.0
    asia_max_d = 9999.0 if is_hourly else (200.0 if is_15m else 80.0)
    sec_max_d  = 9999.0 if is_hourly else 250.0

    # ── Asia range sweeps ──────────────────────────────────────────────────────
    if ar:
        asia_expiry = 15 * 60 if is_hourly else 13 * 60 + 30
        al = SweepState("long",  "asia", threshold_boost=0, min_depth=asia_min_d, max_depth=asia_max_d,
                        starts_at_mins=starts_ny, expires_at_mins=asia_expiry)
        al.ref_level = asia_low

        as_ = SweepState("short", "asia", threshold_boost=0, min_depth=asia_min_d, max_depth=asia_max_d,
                         starts_at_mins=starts_ny, expires_at_mins=asia_expiry)
        as_.ref_level = asia_high

        # London carry-over: London already took liquidity — NY just needs MSS
        if london_action.get("swept_low") and london_action.get("sweep_depth_low", 0) >= 25.0:
            al.done          = True
            al.depth         = london_action["sweep_depth_low"]
            al.sweep_extreme = asia_low - london_action["sweep_depth_low"]
            # detected_at at NY open so the 90-min timeout is measured from 9:30 AM
            al.detected_at   = datetime(
                trade_date.year, trade_date.month, trade_date.day, 9, 30, tzinfo=EST
            )

        if london_action.get("swept_high") and london_action.get("sweep_depth_high", 0) >= 25.0:
            as_.done          = True
            as_.depth         = london_action["sweep_depth_high"]
            as_.sweep_extreme = asia_high + london_action["sweep_depth_high"]
            as_.detected_at   = datetime(
                trade_date.year, trade_date.month, trade_date.day, 9, 30, tzinfo=EST
            )

        states.extend([al, as_])

    # ── PDH / PDL sweeps ──────────────────────────────────────────────────────
    if pdl_lvls:
        pdh_val = pdl_lvls["high"]
        pdl_val = pdl_lvls["low"]

        # Skip levels too close to Asia range (< 5 pts) to avoid exact duplicates.
        # 5pt threshold (down from 10) catches PDH/PDL that are near but distinct from
        # Asia range — the institutional levels are different even when close.
        add_pdl = asia_low  is None or abs(pdl_val - asia_low)  >= 5.0
        add_pdh = asia_high is None or abs(pdh_val - asia_high) >= 5.0

        pdh_expiry = 15 * 60 if is_hourly else 13 * 60 + 30
        if add_pdl:
            pdl_st = SweepState("long",  "pdh_pdl", threshold_boost=1, min_depth=sec_min_d, max_depth=sec_max_d,
                                starts_at_mins=starts_ny, expires_at_mins=pdh_expiry)
            pdl_st.ref_level = pdl_val
            states.append(pdl_st)

        if add_pdh:
            pdh_st = SweepState("short", "pdh_pdl", threshold_boost=1, min_depth=sec_min_d, max_depth=sec_max_d,
                                starts_at_mins=starts_ny, expires_at_mins=pdh_expiry)
            pdh_st.ref_level = pdh_val
            states.append(pdh_st)

    # ── Previous PM session (1:30–4 PM) range sweeps ─────────────────────────
    # 1h: threshold_boost=0 (100% WR — the hourly structure fully plays out).
    # 5m: threshold_boost=2 (filters down to only score≥6 setups; the 20% WR on
    #     5m comes from low-score trades that get whipsawed by intraday noise).
    if pm_lvls:
        pm_high    = pm_lvls["high"]
        pm_low     = pm_lvls["low"]
        pm_boost   = 0 if is_hourly else 2
        pm_max_d   = 9999.0 if is_hourly else 200.0

        ref_lows  = [v for v in [asia_low,  pdl_lvls["low"]  if pdl_lvls else None] if v is not None]
        ref_highs = [v for v in [asia_high, pdl_lvls["high"] if pdl_lvls else None] if v is not None]

        add_pm_long  = all(abs(pm_low  - r) >= 10.0 for r in ref_lows)
        add_pm_short = all(abs(pm_high - r) >= 10.0 for r in ref_highs)

        if add_pm_long:
            pm_l = SweepState("long",  "pm_range", threshold_boost=pm_boost, min_depth=8.0, max_depth=pm_max_d,
                              starts_at_mins=starts_ny, expires_at_mins=13 * 60 + 30)
            pm_l.ref_level = pm_low
            states.append(pm_l)

        if add_pm_short:
            pm_s = SweepState("short", "pm_range", threshold_boost=pm_boost, min_depth=8.0, max_depth=pm_max_d,
                              starts_at_mins=starts_ny, expires_at_mins=13 * 60 + 30)
            pm_s.ref_level = pm_high
            states.append(pm_s)

    # ── Previous Week High / Low sweeps — 1h ONLY ────────────────────────────
    # PWH/PWL: 75-78% WR on 1h (large structure resolved over hours). On 5m both
    # trades hit TP1 (stop moves to BE) but reversal doesn't reach TP2 before noise
    # stops them out at break-even — the level needs 1h+ bars to fully play out.
    if weekly_lvls and is_hourly:
        pwh = weekly_lvls.get("prev_week_high")
        pwl = weekly_lvls.get("prev_week_low")

        all_refs = [v for v in [
            asia_low, asia_high,
            pdl_lvls["low"]  if pdl_lvls else None,
            pdl_lvls["high"] if pdl_lvls else None,
        ] if v is not None]

        wk_max_d = 9999.0 if is_hourly else 200.0

        if pwl is not None and all(abs(pwl - r) >= 15.0 for r in all_refs):
            pwl_st = SweepState("long", "weekly", threshold_boost=1, min_depth=8.0, max_depth=wk_max_d,
                                starts_at_mins=starts_ny, expires_at_mins=16 * 60)
            pwl_st.ref_level = pwl
            states.append(pwl_st)

        if pwh is not None and all(abs(pwh - r) >= 15.0 for r in all_refs):
            pwh_st = SweepState("short", "weekly", threshold_boost=1, min_depth=8.0, max_depth=wk_max_d,
                                starts_at_mins=starts_ny, expires_at_mins=16 * 60)
            pwh_st.ref_level = pwh
            states.append(pwh_st)

    # ── NY Midnight Range (00:00–03:00 EST) sweeps — 1h ONLY ─────────────────
    # NYMOR: RTH sweep of midnight H/L = overnight liquidity grab → reversal.
    # On 5m the 25pt stop gets whipsawed by bear-trend continuations; on 1h
    # the hourly bar structure absorbs the noise and reaches targets cleanly.
    if midnight_lvls and is_hourly:
        mnh = midnight_lvls.get("high")
        mnl = midnight_lvls.get("low")

        mn_refs = [v for v in [
            asia_low, asia_high,
            pdl_lvls["low"]  if pdl_lvls else None,
            pdl_lvls["high"] if pdl_lvls else None,
        ] if v is not None]

        mn_max_d = 9999.0 if is_hourly else 120.0

        if mnl is not None and all(abs(mnl - r) >= 10.0 for r in mn_refs):
            mn_lo_st = SweepState("long", "midnight", threshold_boost=0, min_depth=8.0, max_depth=mn_max_d,
                                  starts_at_mins=starts_ny, expires_at_mins=13 * 60 + 30)
            mn_lo_st.ref_level = mnl
            states.append(mn_lo_st)

        if mnh is not None and all(abs(mnh - r) >= 10.0 for r in mn_refs):
            mn_hi_st = SweepState("short", "midnight", threshold_boost=0, min_depth=8.0, max_depth=mn_max_d,
                                  starts_at_mins=starts_ny, expires_at_mins=13 * 60 + 30)
            mn_hi_st.ref_level = mnh
            states.append(mn_hi_st)

    # ── Pre-market range (8:00–9:25 AM EST) sweeps — 15m + 5m, not 1h ─────────
    # Final institutional squeeze before RTH open. RTH sweep of pre-market H/L
    # = Judas Swing confirmed → institutional reversal. 1h bars lack the resolution
    # to separate the pre-market range from the 9 AM bar.
    # On 15m: 6 pre-market bars form the range (8:00–9:15 AM), giving a clean H/L.
    if premarket_lvls and not is_hourly:
        pmk_h = premarket_lvls.get("high")
        pmk_l = premarket_lvls.get("low")

        pmk_refs = [v for v in [
            asia_low, asia_high,
            pdl_lvls["low"]  if pdl_lvls else None,
            pdl_lvls["high"] if pdl_lvls else None,
        ] if v is not None]

        if pmk_l is not None and all(abs(pmk_l - r) >= 10.0 for r in pmk_refs):
            pmk_lo_st = SweepState("long", "premarket", threshold_boost=0, min_depth=8.0, max_depth=120.0,
                                   starts_at_mins=9 * 60 + 30, expires_at_mins=12 * 60)
            pmk_lo_st.ref_level = pmk_l
            states.append(pmk_lo_st)

        if pmk_h is not None and all(abs(pmk_h - r) >= 10.0 for r in pmk_refs):
            pmk_hi_st = SweepState("short", "premarket", threshold_boost=0, min_depth=8.0, max_depth=120.0,
                                   starts_at_mins=9 * 60 + 30, expires_at_mins=12 * 60)
            pmk_hi_st.ref_level = pmk_h
            states.append(pmk_hi_st)

    return states


# ── Main backtest ──────────────────────────────────────────────────────────────

def run_backtest(interval: str = BACKTEST_INTERVAL, period: str = "60d") -> BacktestResult:
    print(f"Loading NQ data ({period} / {interval}) ...")
    df = load_nq(interval=interval, period=period)
    df = label_sessions(df, interval=interval)
    print(f"Loaded {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

    print("Loading ES data for SMT divergence ...")
    es_df = _get_es_data(period=period, interval=interval)
    print(f"  ES data: {'loaded' if es_df is not None else 'unavailable (SMT checks skipped)'}")

    print("Loading VIX regime cache ...")
    vix_cache = _build_vix_cache(period=period)
    print(f"  VIX data: {len(vix_cache)} days loaded")

    asia_ranges      = build_asia_ranges(df)
    vwap_series, vwap_up1, vwap_up2, vwap_lo1, vwap_lo2 = compute_vwap_bands(df)
    prev_day_lvls    = _build_prev_day_levels(df)
    prev_pm_lvls     = _build_pm_range_levels(df)
    midnight_cache   = _build_midnight_levels(df)
    premarket_cache  = _build_premarket_levels(df)
    print(f"Asia ranges built for {len(asia_ranges)} trading days")
    print(f"PDH/PDL: {len(prev_day_lvls)} | PM range: {len(prev_pm_lvls)} | Midnight: {len(midnight_cache)} | Pre-mkt: {len(premarket_cache)} days")

    result  = BacktestResult()
    smart   = SmartFilter()
    balance = STARTING_BALANCE - 400
    peak_balance = STARTING_BALANCE
    floor   = STARTING_BALANCE - TRAILING_MAX_DRAWDOWN

    trades_today    = 0
    daily_pnl_today = 0.0
    prev_date       = None

    # Per-day sweep states (rebuilt each day)
    sweep_states: list[SweepState] = []

    # Per-day Judas Swing state (Tuesday)
    tuesday_first_sweep_dir: str | None = None   # "long" or "short"
    tuesday_judas_confirmed: bool = False

    # Per-day context
    midnight_lvls  = None
    premarket_lvls = None
    weekly_lvls    = {"prev_week_high": None, "prev_week_low": None}
    vix_today     = {"vix": None, "regime": "unknown", "score_penalty": 0}
    london_action = {"direction": "neutral", "swept_high": False, "swept_low": False,
                     "sweep_depth_high": 0.0, "sweep_depth_low": 0.0}

    opening_range_open:  float | None = None
    opening_range_close: float | None = None
    opening_range_dir:   str = "neutral"
    opening_range_high:  float | None = None   # Silver Bullet reference
    opening_range_low:   float | None = None   # Silver Bullet reference
    silver_bullet_added: bool = False
    pm_sb_high: float | None = None
    pm_sb_low:  float | None = None
    pm_silver_bullet_added: bool = False
    am_sb_high: float | None = None
    am_sb_low:  float | None = None
    am_silver_bullet_added: bool = False

    # Morning range (9:30-11:30 AM) for afternoon PM session setups
    morning_hi: float | None = None
    morning_lo: float | None = None
    morning_range_locked: bool = False

    # Gap Fill (PDC gap close — 93.1% WR research on small NQ gaps)
    prev_day_close: float | None   = None
    day_open_930:   float | None   = None
    gap_size_pts:   float          = 0.0
    gap_fill_dir:   str | None     = None   # "long" or "short"
    gap_fill_target: float | None  = None   # PDC level to close to
    gap_fill_active: bool          = False
    gap_fill_fired:  bool          = False

    # Initial Balance Breakout (82% WR — first 60-min range, fire after 10:30 AM)
    ib_high:         float | None  = None
    ib_low:          float | None  = None
    ib_locked:       bool          = False
    ib_break_fired:  bool          = False

    closes = df["Close"]
    highs  = df["High"]
    lows   = df["Low"]
    opens  = df["Open"]

    for i, (ts, row) in enumerate(df.iterrows()):
        est_dt     = ts.tz_convert(EST)
        trade_date = est_dt.date()
        mins       = est_dt.hour * 60 + est_dt.minute

        # ── New day reset ──────────────────────────────────────────────────────
        if trade_date != prev_date:
            if prev_date is not None:
                peak_balance = max(peak_balance, balance)
                floor        = peak_balance - TRAILING_MAX_DRAWDOWN
                result.daily_pnl[prev_date] = daily_pnl_today

            trades_today    = 0
            daily_pnl_today = 0.0
            prev_date       = trade_date
            tuesday_first_sweep_dir = None
            tuesday_judas_confirmed = False
            opening_range_open  = None
            opening_range_close = None
            opening_range_dir   = "neutral"
            opening_range_high  = None   # Silver Bullet: max high of 9:30-10 AM
            opening_range_low   = None   # Silver Bullet: min low of 9:30-10 AM
            silver_bullet_added = False
            pm_sb_high          = None   # PM Silver Bullet: max high of 1:30-2 PM
            pm_sb_low           = None   # PM Silver Bullet: min low of 1:30-2 PM
            pm_silver_bullet_added = False
            am_sb_high          = None   # London-close SB: max high of 10-11 AM
            am_sb_low           = None   # London-close SB: min low of 10-11 AM
            am_silver_bullet_added = False
            morning_hi          = None
            morning_lo          = None
            morning_range_locked = False
            # Gap Fill reset
            pdl_today           = prev_day_lvls.get(trade_date)
            prev_day_close      = pdl_today.get("close") if pdl_today else None
            day_open_930        = None
            gap_size_pts        = 0.0
            gap_fill_dir        = None
            gap_fill_target     = None
            gap_fill_active     = False
            gap_fill_fired      = False
            # IB reset
            ib_high             = None
            ib_low              = None
            ib_locked           = False
            ib_break_fired      = False
            smart.reset_day()

            midnight_lvls  = midnight_cache.get(trade_date)
            premarket_lvls = premarket_cache.get(trade_date)
            weekly_lvls    = get_weekly_levels(df, trade_date)
            vix_today   = vix_cache.get(trade_date, {"vix": None, "regime": "unknown", "score_penalty": 0})

            ar = asia_ranges.get(trade_date)
            if ar:
                london_action = get_london_action(df, trade_date, ar["high"], ar["low"])
            else:
                london_action = {"direction": "neutral", "swept_high": False, "swept_low": False,
                                 "sweep_depth_high": 0.0, "sweep_depth_low": 0.0}

            sweep_states = _build_day_sweep_states(
                ar=ar,
                pdl_lvls=prev_day_lvls.get(trade_date),
                pm_lvls=prev_pm_lvls.get(trade_date),
                london_action=london_action,
                trade_date=trade_date,
                interval=interval,
                weekly_lvls=weekly_lvls,
                midnight_lvls=midnight_lvls,
                premarket_lvls=premarket_lvls,
            )

        # ── Opening range tracking ─────────────────────────────────────────────
        if mins == 9 * 60 + 30 and opening_range_open is None:
            opening_range_open = float(closes.iloc[i])
        if 9 * 60 + 30 <= mins < 10 * 60:
            opening_range_close = float(closes.iloc[i])
            bar_h = float(highs.iloc[i])
            bar_l = float(lows.iloc[i])
            if opening_range_high is None or bar_h > opening_range_high:
                opening_range_high = bar_h
            if opening_range_low is None or bar_l < opening_range_low:
                opening_range_low = bar_l

        if mins == 10 * 60 and opening_range_open is not None and opening_range_dir == "neutral":
            if opening_range_close and opening_range_close > opening_range_open:
                opening_range_dir = "bullish"
            elif opening_range_close and opening_range_close < opening_range_open:
                opening_range_dir = "bearish"

        # ── Gap Fill setup at 9:30 AM ──────────────────────────────────────────
        # Research: 93.1% fill rate for small gaps (< 0.3x ATR ≈ 10-80 pts on NQ)
        if mins == 9 * 60 + 30 and prev_day_close is not None:
            day_open_930 = float(opens.iloc[i])
            gap_pts      = day_open_930 - prev_day_close
            gap_size_pts = abs(gap_pts)
            if 10.0 <= gap_size_pts <= 80.0 and trade_date.weekday() != 1:
                gap_fill_target = prev_day_close
                gap_fill_dir    = "short" if gap_pts > 0 else "long"
                gap_fill_active = True

        # ── IB (Initial Balance) tracking: 9:30–10:30 AM ──────────────────────
        if 9 * 60 + 30 <= mins < 10 * 60 + 30:
            bar_h = float(highs.iloc[i])
            bar_l = float(lows.iloc[i])
            if ib_high is None or bar_h > ib_high:
                ib_high = bar_h
            if ib_low is None or bar_l < ib_low:
                ib_low = bar_l

        # Lock IB at 10:30 AM
        if mins == 10 * 60 + 30 and ib_high is not None and not ib_locked:
            ib_locked = True

        # ── Silver Bullet window 1: opening-range (9:30-10 AM) sweep at 10-11 AM ─
        if mins == 10 * 60 and not silver_bullet_added and opening_range_high is not None:
            silver_bullet_added = True
            if trade_date.weekday() != 1:  # Tuesday: 0% WR
                sb_lo = SweepState("long", "silver_bullet", threshold_boost=0,
                                   min_depth=10.0, max_depth=999.0,
                                   starts_at_mins=10 * 60, expires_at_mins=11 * 60)
                sb_lo.ref_level = opening_range_low
                sb_hi = SweepState("short", "silver_bullet", threshold_boost=0,
                                   min_depth=10.0, max_depth=999.0,
                                   starts_at_mins=10 * 60, expires_at_mins=11 * 60)
                sb_hi.ref_level = opening_range_high
                sweep_states.extend([sb_lo, sb_hi])

        # Track 10:00-11:00 AM range for London-close Silver Bullet window
        if 10 * 60 <= mins < 11 * 60:
            bar_h = float(highs.iloc[i])
            bar_l = float(lows.iloc[i])
            if am_sb_high is None or bar_h > am_sb_high:
                am_sb_high = bar_h
            if am_sb_low is None or bar_l < am_sb_low:
                am_sb_low = bar_l

        # ── Silver Bullet window 2: 10-11 AM range sweep at 11 AM - noon ────────
        if mins == 11 * 60 and not am_silver_bullet_added and am_sb_high is not None:
            am_silver_bullet_added = True
            if trade_date.weekday() != 1:
                lc_lo = SweepState("long", "silver_bullet", threshold_boost=0,
                                   min_depth=10.0, max_depth=999.0,
                                   starts_at_mins=11 * 60, expires_at_mins=12 * 60)
                lc_lo.ref_level = am_sb_low
                lc_hi = SweepState("short", "silver_bullet", threshold_boost=0,
                                   min_depth=10.0, max_depth=999.0,
                                   starts_at_mins=11 * 60, expires_at_mins=12 * 60)
                lc_hi.ref_level = am_sb_high
                sweep_states.extend([lc_lo, lc_hi])

        # ── Morning range tracking (9:30–11:30 AM) ────────────────────────────
        if 9 * 60 + 30 <= mins < 11 * 60 + 30:
            h_bar = float(highs.iloc[i])
            l_bar = float(lows.iloc[i])
            if morning_hi is None or h_bar > morning_hi:
                morning_hi = h_bar
            if morning_lo is None or l_bar < morning_lo:
                morning_lo = l_bar

        # At 11:30 AM lock morning range and create PM session sweep states
        # Use >= so 1h bars (which have no 11:30 bar) trigger this at noon (720)
        if mins >= 11 * 60 + 30 and not morning_range_locked and morning_hi is not None and morning_lo is not None:
            morning_range_locked = True
            mr_range = morning_hi - morning_lo
            if mr_range >= 20.0:  # Only create PM states if morning had real range
                mr_lo_st = SweepState("long",  "am_range", threshold_boost=5, min_depth=8.0, max_depth=200.0,
                                      starts_at_mins=13 * 60 + 30, expires_at_mins=16 * 60)
                mr_lo_st.ref_level = morning_lo
                mr_hi_st = SweepState("short", "am_range", threshold_boost=5, min_depth=8.0, max_depth=200.0,
                                      starts_at_mins=13 * 60 + 30, expires_at_mins=16 * 60)
                mr_hi_st.ref_level = morning_hi
                sweep_states.extend([mr_lo_st, mr_hi_st])

        # ── PM Silver Bullet: 1:30-2:00 PM range → sweep at 2-3 PM ──────────────
        if 13 * 60 + 30 <= mins < 14 * 60:
            bar_h = float(highs.iloc[i])
            bar_l = float(lows.iloc[i])
            if pm_sb_high is None or bar_h > pm_sb_high:
                pm_sb_high = bar_h
            if pm_sb_low is None or bar_l < pm_sb_low:
                pm_sb_low = bar_l

        if mins == 14 * 60 and not pm_silver_bullet_added and pm_sb_high is not None:
            pm_silver_bullet_added = True
            if trade_date.weekday() != 1:
                # PM Silver Bullet: short-only (sweep above 1:30-2 PM range high → short)
                # Longs at 2 PM in downtrend have 0% WR — skip
                pm_sb_hi_st = SweepState("short", "silver_bullet", threshold_boost=0,
                                         min_depth=10.0, max_depth=999.0,
                                         starts_at_mins=14 * 60, expires_at_mins=15 * 60)
                pm_sb_hi_st.ref_level = pm_sb_high
                sweep_states.append(pm_sb_hi_st)

        # Hard stop: hit floor
        if balance <= floor:
            break

        if not row["in_trade_window"]:
            continue
        if trades_today >= MAX_TRADES_PER_DAY:
            continue
        if daily_pnl_today <= -MAX_DAILY_LOSS:
            continue

        price    = float(row["Close"])
        high     = float(row["High"])
        low      = float(row["Low"])
        vwap     = float(vwap_series.iloc[i]) if i < len(vwap_series) else None
        vb_up1   = float(vwap_up1.iloc[i])    if i < len(vwap_up1)    else None
        vb_lo1   = float(vwap_lo1.iloc[i])    if i < len(vwap_lo1)    else None
        vb_up2   = float(vwap_up2.iloc[i])    if i < len(vwap_up2)    else None
        vb_lo2   = float(vwap_lo2.iloc[i])    if i < len(vwap_lo2)    else None

        # ── News blackout ──────────────────────────────────────────────────────
        news_check = check_news_calendar(est_dt)
        if news_check["skip"]:
            continue

        ar_today = asia_ranges.get(trade_date)
        fired_this_bar = False

        # ── Process each sweep state ───────────────────────────────────────────

        for state in sweep_states:
            if state.trade_fired or fired_this_bar:
                continue
            if state.ref_level == 0.0:
                continue

            # Skip if we haven't reached this state's active window yet
            if mins < state.starts_at_mins:
                continue

            # ── Sweep timeout: 90 min without MSS → reset for re-detection ──
            if state.done and not state.mss_confirmed and state.detected_at is not None:
                elapsed = (est_dt - state.detected_at).total_seconds() / 60
                if elapsed >= SWEEP_TIMEOUT_MINUTES:
                    # Tuesday Judas tracking (Asia sweeps only)
                    if (state.level_type == "asia"
                            and trade_date.weekday() == 1
                            and tuesday_first_sweep_dir is None):
                        tuesday_first_sweep_dir = state.signal_dir
                        tuesday_judas_confirmed  = True
                    state.timeout_reset()

            # ── Sweep detection ────────────────────────────────────────────────
            if not state.done:
                ref = state.ref_level
                if state.signal_dir == "long" and low < ref:
                    depth = round(ref - low, 2)
                    if state.min_depth <= depth <= state.max_depth:
                        state.done          = True
                        state.bar_idx       = i
                        state.detected_at   = est_dt
                        state.depth         = depth
                        state.sweep_extreme = low
                        state.smt_result    = check_smt_divergence(df, es_df, i, "long")
                        s_origin            = _swing_origin(df, i, "long")
                        state.ote_zone      = compute_ote_zone(s_origin, low, "long")
                        continue  # Wait for next bar before looking for MSS

                elif state.signal_dir == "short" and high > ref:
                    depth = round(high - ref, 2)
                    if state.min_depth <= depth <= state.max_depth:
                        state.done          = True
                        state.bar_idx       = i
                        state.detected_at   = est_dt
                        state.depth         = depth
                        state.sweep_extreme = high
                        state.smt_result    = check_smt_divergence(df, es_df, i, "short")
                        s_origin            = _swing_origin(df, i, "short")
                        state.ote_zone      = compute_ote_zone(s_origin, high, "short")
                        continue

                continue  # Not done, nothing more to do

            # ── MSS detection (state.done is True here) ───────────────────────
            if not state.mss_confirmed:
                sb = state.bar_idx

                if sb is None:
                    # London carry-over: fix bar_idx at first NY bar, compute SMT/OTE
                    state.bar_idx = i
                    state.smt_result = check_smt_divergence(df, es_df, i, state.signal_dir)
                    s_origin         = _swing_origin(df, i, state.signal_dir)
                    s_extreme        = state.sweep_extreme if state.sweep_extreme != 0.0 else state.ref_level
                    state.ote_zone   = compute_ote_zone(s_origin, s_extreme, state.signal_dir)
                    continue  # Look for MSS from next bar

                if i <= sb:
                    continue

                mss_result = detect_mss(df, sb, state.mss_dir, lookback=25)
                if not (mss_result["detected"] and mss_result["mss_bar_idx"] == i):
                    continue

                state.mss_confirmed = True
                state.mss_strong    = mss_result.get("is_strong", False)
                state.mss_bar_idx   = i
                # Fall through to scoring on the same bar MSS is detected

            # ── Score and enter (state.done AND state.mss_confirmed) ───────────

            # Hard expiry: secondary levels must produce MSS before cutoff time
            if mins >= state.expires_at_mins:
                state.trade_fired = True
                continue

            signal_dir = state.signal_dir

            # Thursday shorts: 17% WR in backtest — claims-day volatility stops out
            # shorts before they can run, even in a bear market.
            if signal_dir == "short" and trade_date.weekday() == 3:
                state.trade_fired = True
                continue

            sb = state.bar_idx
            if sb is None:
                continue

            # SMT hard-block: NQ diverging from ES = fake signal
            smt_result = state.smt_result
            smt_ok     = smt_result.get("confirmed", True)
            if smt_result.get("divergent") and not smt_ok:
                state.trade_fired = True
                continue

            fvgs       = find_fvgs(df, signal_dir, sb, i, min_size_points=2.0)
            fvg_active = get_active_fvg(fvgs, price, signal_dir) is not None

            pdl_day_lvl  = prev_day_lvls.get(trade_date)
            pdh          = pdl_day_lvl["high"] if pdl_day_lvl else None
            pdl_lev      = pdl_day_lvl["low"]  if pdl_day_lvl else None
            london_ok    = is_london_aligned(london_action, signal_dir)
            # Silver Bullet is always opening-range-opposed by definition (it IS the sweep)
            open_opposed = (
                state.level_type == "silver_bullet"
                or (opening_range_dir == "bullish" and signal_dir == "short")
                or (opening_range_dir == "bearish" and signal_dir == "long")
            )

            # PDH/PDL confluence: always True for pdh_pdl sweep states
            pdh_pdl_conf = (state.level_type == "pdh_pdl")

            ote_active = price_in_ote(price, state.ote_zone)

            # Judas reversal mode: Tuesday confirmed 2nd-direction Asia trade,
            # OR Silver Bullet on Tuesday (opening range sweep = Judas capture)
            judas_mode = (
                trade_date.weekday() == 1
                and (
                    (tuesday_judas_confirmed and state.level_type == "asia"
                     and signal_dir != tuesday_first_sweep_dir)
                    or state.level_type == "silver_bullet"
                )
            )
            post_claims = (trade_date.weekday() == 3 and est_dt.hour >= 10)
            setup_mode  = (
                "judas_reversal" if judas_mode
                else "post_claims" if post_claims
                else "normal"
            )

            sweep_price_for_score = (
                state.sweep_extreme if state.sweep_extreme != 0.0 else state.ref_level
            )

            confluence = score_setup(
                asia_sweep=True,
                mss_confirmed=True,
                fvg_active=fvg_active,
                price=price,
                vwap=vwap,
                direction=signal_dir,
                bar_hour=est_dt.hour,
                bar_minute=est_dt.minute,
                london_aligned=london_ok,
                pdh_pdl_confluence=pdh_pdl_conf,
                opening_range_opposed=open_opposed,
                mss_strong=state.mss_strong,
                prev_day_high=pdh,
                prev_day_low=pdl_lev,
                sweep_price=sweep_price_for_score,
                prev_week_high=weekly_lvls.get("prev_week_high"),
                prev_week_low=weekly_lvls.get("prev_week_low"),
                ote_zone=ote_active,
                smt_confirmed=smt_ok,
            )

            market_ctx = {
                "news":   news_check,
                "vix":    vix_today,
                "smt":    smt_result,
                "weekly": weekly_lvls,
            }

            min_score = smart.min_score_required(
                est_dt.hour, est_dt.minute,
                day_of_week=trade_date.weekday(),
                london_aligned=london_ok,
                mss_strong=state.mss_strong,
                sweep_depth=state.depth,
                market_context=market_ctx,
                judas_reversal_mode=judas_mode,
                threshold_boost=state.threshold_boost,
            )

            if min_score >= 99 or confluence.score < min_score:
                continue

            # ── Quant bonus & flexible RR ──────────────────────────────────────
            qb = quant_bonus_score(
                df=df, sweep_bar=sb, signal_dir=signal_dir, price=price,
                vwap_upper1=vb_up1, vwap_lower1=vb_lo1,
            )
            trade_rr = compute_trade_rr(
                score=confluence.score,
                signal_type=state.level_type,
                day_of_week=trade_date.weekday(),
                quant_bonus=qb,
            )

            # ── Build entry ────────────────────────────────────────────────────
            mss_idx = state.mss_bar_idx
            ob = None
            if mss_idx is not None:
                ob = find_order_block(df, sb, mss_idx, signal_dir)

            if ob and ob["stop_distance"] <= MAX_STOP_POINTS:
                limit_entry = ob["entry"]
                stop_level  = ob["stop"]
            else:
                if signal_dir == "long":
                    stop_level  = round(float(lows.iloc[max(0, sb):i+1].min()) - 1.0, 2)
                    limit_entry = round(stop_level + MAX_STOP_POINTS, 2)
                else:
                    stop_level  = round(float(highs.iloc[max(0, sb):i+1].max()) + 1.0, 2)
                    limit_entry = round(stop_level - MAX_STOP_POINTS, 2)

            stop_dist = abs(limit_entry - stop_level)
            meta = dict(
                signal_hour=est_dt.hour,
                day_of_week=trade_date.weekday(),
                sweep_depth=state.depth,
                asia_range_width=round(
                    ar_today["high"] - ar_today["low"], 2
                ) if ar_today else 0.0,
                vix_regime=vix_today.get("regime", "unknown"),
                smt_confirmed=smt_ok,
                ote_used=ote_active,
                news_penalty=news_check.get("score_penalty", 0),
                setup_mode=setup_mode,
                level_type=state.level_type,
                rr=trade_rr,
                quant_bonus=qb,
            )

            if signal_dir == "long":
                tp1 = round(limit_entry + stop_dist * 1.0,       2)
                tp2 = round(limit_entry + stop_dist * trade_rr,  2)
                if low > limit_entry:
                    trade = _simulate_limit_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        limit_entry=limit_entry, stop=stop_level, tp1=tp1, tp2=tp2,
                        trade_date=trade_date, score=confluence.score,
                        reason=confluence.reason, meta=meta,
                    )
                else:
                    trade = _simulate_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        entry=limit_entry, stop=stop_level, tp1=tp1, tp2=tp2,
                        contracts=1, trade_date=trade_date, score=confluence.score,
                        reason=confluence.reason, meta=meta,
                    )
            else:
                tp1 = round(limit_entry - stop_dist * 1.0,       2)
                tp2 = round(limit_entry - stop_dist * trade_rr,  2)
                if high < limit_entry:
                    trade = _simulate_limit_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        limit_entry=limit_entry, stop=stop_level, tp1=tp1, tp2=tp2,
                        trade_date=trade_date, score=confluence.score,
                        reason=confluence.reason, meta=meta,
                    )
                else:
                    trade = _simulate_trade(
                        df=df, start_idx=i + 1, direction=signal_dir,
                        entry=limit_entry, stop=stop_level, tp1=tp1, tp2=tp2,
                        contracts=1, trade_date=trade_date, score=confluence.score,
                        reason=confluence.reason, meta=meta,
                    )

            state.trade_fired = True  # Consumed — don't retry this state

            if trade is None:
                continue

            result.trades.append(trade)
            trades_today    += 1
            daily_pnl_today += trade.pnl
            balance         += trade.pnl
            fired_this_bar   = True

            if trades_today >= MAX_TRADES_PER_DAY:
                break

        smart.update_price(price, now_est=est_dt)

    if prev_date:
        result.daily_pnl[prev_date] = daily_pnl_today

    return result


# ── Trade simulators ───────────────────────────────────────────────────────────

def _simulate_trade(
    df: pd.DataFrame,
    start_idx: int,
    direction: str,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    contracts: int,
    trade_date: date,
    score: int,
    reason: str,
    meta: dict | None = None,
) -> BacktestTrade | None:
    meta = meta or {}
    closes    = df["Close"]
    highs     = df["High"]
    lows      = df["Low"]
    est_dates = df.index.tz_convert(EST)

    be_stop        = stop
    tp1_hit        = False
    half_contracts = contracts // 2 if contracts > 1 else 0
    remaining      = contracts

    for j in range(start_idx, min(start_idx + 200, len(df))):
        bar_date = est_dates[j].date()
        if bar_date != trade_date:
            exit_price = float(closes.iloc[j - 1])
            pnl = _calc_pnl(direction, entry, exit_price, remaining) + (
                _calc_pnl(direction, entry, tp1, half_contracts) if tp1_hit else 0
            )
            return BacktestTrade(
                date=trade_date, direction=direction, entry=entry, stop=stop,
                tp1=tp1, tp2=tp2, exit_price=exit_price, contracts=contracts,
                pnl=round(pnl, 2), score=score, outcome="TIMEOUT", reason=reason, **meta,
            )

        bar_low  = float(lows.iloc[j])
        bar_high = float(highs.iloc[j])

        if direction == "long":
            if bar_low <= be_stop:
                exit_price = be_stop
                pnl = _calc_pnl("long", entry, exit_price, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("long", entry, tp1, half_contracts)
                outcome = "WIN_TP1_BE" if tp1_hit and pnl > 0 else "LOSS"
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=exit_price, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome=outcome, reason=reason, **meta,
                )
            if not tp1_hit and bar_high >= tp1:
                tp1_hit   = True
                remaining -= half_contracts
                be_stop   = entry
            if bar_high >= tp2:
                pnl = _calc_pnl("long", entry, tp2, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("long", entry, tp1, half_contracts)
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=tp2, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome="WIN_TP2", reason=reason, **meta,
                )
        else:
            if bar_high >= be_stop:
                exit_price = be_stop
                pnl = _calc_pnl("short", entry, exit_price, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("short", entry, tp1, half_contracts)
                outcome = "WIN_TP1_BE" if tp1_hit and pnl > 0 else "LOSS"
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=exit_price, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome=outcome, reason=reason, **meta,
                )
            if not tp1_hit and bar_low <= tp1:
                tp1_hit   = True
                remaining -= half_contracts
                be_stop   = entry
            if bar_low <= tp2:
                pnl = _calc_pnl("short", entry, tp2, remaining)
                if tp1_hit:
                    pnl += _calc_pnl("short", entry, tp1, half_contracts)
                return BacktestTrade(
                    date=trade_date, direction=direction, entry=entry, stop=stop,
                    tp1=tp1, tp2=tp2, exit_price=tp2, contracts=contracts,
                    pnl=round(pnl, 2), score=score, outcome="WIN_TP2", reason=reason, **meta,
                )

    return None


def _simulate_limit_trade(
    df: pd.DataFrame,
    start_idx: int,
    direction: str,
    limit_entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    trade_date,
    score: int,
    reason: str,
    meta: dict | None = None,
) -> BacktestTrade | None:
    highs     = df["High"]
    lows      = df["Low"]
    est_dates = df.index.tz_convert(EST)

    for j in range(start_idx, min(start_idx + 150, len(df))):
        bar_date = est_dates[j].date()
        if bar_date != trade_date:
            return None

        est_mins = est_dates[j].hour * 60 + est_dates[j].minute
        if not (9 * 60 + 30 <= est_mins < TRADE_END_HOUR * 60 + TRADE_END_MIN):
            return None

        filled = (direction == "long"  and float(lows.iloc[j])  <= limit_entry) or \
                 (direction == "short" and float(highs.iloc[j]) >= limit_entry)

        if filled:
            return _simulate_trade(
                df=df, start_idx=j + 1, direction=direction,
                entry=limit_entry, stop=stop, tp1=tp1, tp2=tp2,
                contracts=1, trade_date=trade_date, score=score, reason=reason,
                meta=meta,
            )

    return None


def _calc_pnl(direction: str, entry: float, exit_price: float, contracts: int) -> float:
    if direction == "long":
        return (exit_price - entry) * contracts * MNQ_DOLLARS_PER_POINT
    return (entry - exit_price) * contracts * MNQ_DOLLARS_PER_POINT
