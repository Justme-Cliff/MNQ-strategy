"""
Daily market context for adaptive filtering.

Four layers of intelligence beyond price alone:

  1. VIX REGIME
     Low vol (<15): reversals work cleanly, standard thresholds.
     Medium vol (15-25): normal conditions, slight caution.
     High vol (>25): trend-following dominates, reversals fail more.
     Extreme vol (>30): skip unless near-perfect setup.

  2. ES/NQ SMT DIVERGENCE (Smart Money Technique)
     When NQ sweeps a level but ES does NOT confirm, it is a fake.
     Institutions use ES as the primary instrument. When they reverse
     NQ, ES shows the real direction 2-5 seconds earlier.
     - NQ sweeps Asia Low but ES holds above its range: weak bull signal
     - NQ sweeps Asia High but ES holds below its range: weak bear signal
     SMT alignment required for highest-probability setups.

  3. ECONOMIC CALENDAR
     Recurring high-impact events that cause unpredictable moves:
     - Thursday 8:30 AM: Initial Jobless Claims (every week)
     - First Friday 8:30 AM: Non-Farm Payrolls
     - 8:30 AM days: CPI, PPI, GDP, Retail Sales (monthly)
     - 2:00 PM: FOMC decisions (8x per year)
     Rule: within 20 min of a known release, raise min score or skip.

  4. WEEKLY LEVELS (Power of 3)
     Previous week high/low are the primary weekly liquidity targets.
     ICT weekly model: Monday accumulates, Tuesday manipulates (Judas
     Swing fake move), Wednesday-Thursday distributes, Friday closes.
     When the weekly sweep also takes out a weekly level, it is a
     much stronger signal because two liquidity pools are being cleared.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

EST = ZoneInfo("America/New_York")

# ── VIX thresholds ─────────────────────────────────────────────────────────────
VIX_LOW      = 15.0
VIX_MEDIUM   = 20.0
VIX_HIGH     = 25.0
VIX_EXTREME  = 30.0


def get_vix_regime(as_of: date | None = None) -> dict:
    """
    Download latest VIX close and classify the volatility regime.
    Returns regime string and the raw VIX value.
    """
    try:
        df = yf.Ticker("^VIX").history(period="5d", interval="1d", auto_adjust=True)
        if df.empty:
            return {"vix": None, "regime": "unknown", "score_penalty": 0}
        vix = float(df["Close"].iloc[-1])
        if vix < VIX_LOW:
            regime, penalty = "low", 0
        elif vix < VIX_MEDIUM:
            regime, penalty = "medium", 0
        elif vix < VIX_HIGH:
            regime, penalty = "high", 1
        elif vix < VIX_EXTREME:
            regime, penalty = "very_high", 2
        else:
            regime, penalty = "extreme", 3
        return {"vix": round(vix, 2), "regime": regime, "score_penalty": penalty}
    except Exception:
        return {"vix": None, "regime": "unknown", "score_penalty": 0}


# ── Weekly levels ──────────────────────────────────────────────────────────────

def get_weekly_levels(df: pd.DataFrame, trade_date: date) -> dict:
    """
    Compute the previous week's high and low from the provided bar data.
    Returns prev_week_high, prev_week_low, and this week's Mon-to-date high/low.
    """
    est_idx = df.index.tz_convert(EST)
    weekly: dict[int, dict] = {}

    for i, ts in enumerate(est_idx):
        if not (9 * 60 + 30 <= ts.hour * 60 + ts.minute < 16 * 60):
            continue
        iso = ts.isocalendar()
        wk = iso[0] * 100 + iso[1]  # year*100 + week_number
        h = float(df["High"].iloc[i])
        l = float(df["Low"].iloc[i])
        if wk not in weekly:
            weekly[wk] = {"high": h, "low": l, "days": set()}
        else:
            weekly[wk]["high"] = max(weekly[wk]["high"], h)
            weekly[wk]["low"]  = min(weekly[wk]["low"],  l)
        weekly[wk]["days"].add(ts.date())

    trade_iso    = date.fromisoformat(str(trade_date)).isocalendar()
    current_week = trade_iso[0] * 100 + trade_iso[1]
    prev_week    = current_week - 1
    # Handle year boundary simply — use sorted keys
    sorted_weeks = sorted(weekly.keys())
    cur_idx      = sorted_weeks.index(current_week) if current_week in sorted_weeks else -1
    prev_data    = weekly.get(sorted_weeks[cur_idx - 1]) if cur_idx > 0 else None

    if prev_data:
        return {
            "prev_week_high": round(prev_data["high"], 2),
            "prev_week_low":  round(prev_data["low"], 2),
        }
    return {"prev_week_high": None, "prev_week_low": None}


def weekly_level_confluence(
    sweep_price: float,
    direction: str,
    prev_week_high: float | None,
    prev_week_low: float | None,
) -> bool:
    """
    True if the sweep also took out a previous week level.
    Long sweep (below Asia Low): did it also break prev week low?
    Short sweep (above Asia High): did it also break prev week high?
    """
    if direction == "long" and prev_week_low is not None:
        return sweep_price <= prev_week_low
    if direction == "short" and prev_week_high is not None:
        return sweep_price >= prev_week_high
    return False


# ── SMT Divergence ─────────────────────────────────────────────────────────────

def get_es_data(period: str = "60d", interval: str = "5m") -> pd.DataFrame | None:
    """Download ES (E-mini S&P 500) bars for SMT comparison."""
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


def check_smt_divergence(
    nq_df: pd.DataFrame,
    es_df: pd.DataFrame | None,
    sweep_bar_idx: int,
    direction: str,
    lookback: int = 10,
) -> dict:
    """
    Check whether ES confirms or diverges from the NQ sweep.

    For a LONG setup (NQ swept Asia Low):
      ES confirms   = ES also printed a new low in the same window (same structural weakness)
      ES diverges   = ES held above its recent low while NQ broke down (divergence = fake NQ sweep)

    For a SHORT setup (NQ swept Asia High):
      ES confirms   = ES also printed a new high in the same window
      ES diverges   = ES stayed below its recent high while NQ broke up

    Returns:
      confirmed: bool    - True = ES and NQ agree
      divergent: bool    - True = ES and NQ disagree (lower quality signal)
      detail:    str
    """
    if es_df is None:
        return {"confirmed": True, "divergent": False, "detail": "ES data unavailable"}

    try:
        nq_est = nq_df.index.tz_convert(EST)
        es_est = es_df.index.tz_convert(EST) if es_df.index.tz else es_df.index

        if sweep_bar_idx >= len(nq_df):
            return {"confirmed": True, "divergent": False, "detail": "sweep_bar out of range"}

        sweep_time = nq_est[sweep_bar_idx]

        # Find the matching ES bar at the same time
        time_diff = abs(es_est - sweep_time)
        closest_es = time_diff.argmin()

        window_start = max(0, closest_es - lookback)
        window_end   = closest_es + 1

        es_window_high = float(es_df["High"].iloc[window_start:window_end].max())
        es_window_low  = float(es_df["Low"].iloc[window_start:window_end].min())
        es_current_low = float(es_df["Low"].iloc[closest_es])
        es_current_high= float(es_df["High"].iloc[closest_es])

        nq_window_high = float(nq_df["High"].iloc[max(0, sweep_bar_idx - lookback):sweep_bar_idx + 1].max())
        nq_window_low  = float(nq_df["Low"].iloc[max(0, sweep_bar_idx - lookback):sweep_bar_idx + 1].min())

        if direction == "long":
            nq_broke_low = float(nq_df["Low"].iloc[sweep_bar_idx]) <= nq_window_low
            es_broke_low = es_current_low <= es_window_low
            if nq_broke_low and es_broke_low:
                return {"confirmed": True,  "divergent": False, "detail": "ES confirms NQ low sweep"}
            if nq_broke_low and not es_broke_low:
                return {"confirmed": False, "divergent": True,  "detail": "SMT: NQ swept low but ES held — divergence, weaker long"}
            return {"confirmed": True, "divergent": False, "detail": "No clean divergence detected"}

        else:  # short
            nq_broke_high = float(nq_df["High"].iloc[sweep_bar_idx]) >= nq_window_high
            es_broke_high = es_current_high >= es_window_high
            if nq_broke_high and es_broke_high:
                return {"confirmed": True,  "divergent": False, "detail": "ES confirms NQ high sweep"}
            if nq_broke_high and not es_broke_high:
                return {"confirmed": False, "divergent": True,  "detail": "SMT: NQ swept high but ES held — divergence, weaker short"}
            return {"confirmed": True, "divergent": False, "detail": "No clean divergence detected"}

    except Exception as e:
        return {"confirmed": True, "divergent": False, "detail": f"SMT check error: {e}"}


# ── OTE (Optimal Trade Entry) ──────────────────────────────────────────────────

def compute_ote_zone(
    swing_origin: float,
    sweep_extreme: float,
    direction: str,
) -> dict:
    """
    Compute the ICT Optimal Trade Entry zone (61.8% to 78.6% retracement).

    For a LONG setup:
      swing_origin   = last significant swing HIGH before the sweep
      sweep_extreme  = the sweep low (lowest point of the sweep)
      OTE zone       = price retraces BACK UP from sweep_extreme toward swing_origin
      Entry zone     = [61.8% retrace, 78.6% retrace]

    For a SHORT setup:
      swing_origin   = last significant swing LOW before the sweep
      sweep_extreme  = the sweep high
      Entry zone     = [78.6% retrace DOWN from sweep_extreme, 61.8% retrace DOWN]
    """
    total_range = abs(swing_origin - sweep_extreme)
    if total_range < 0.25:
        return {"ote_high": None, "ote_low": None, "valid": False}

    fib_618 = 0.618
    fib_786 = 0.786

    if direction == "long":
        # Retracing UP from sweep_extreme toward swing_origin
        ote_low  = round(sweep_extreme + total_range * fib_618, 2)
        ote_high = round(sweep_extreme + total_range * fib_786, 2)
    else:
        # Retracing DOWN from sweep_extreme toward swing_origin
        ote_high = round(sweep_extreme - total_range * fib_618, 2)
        ote_low  = round(sweep_extreme - total_range * fib_786, 2)

    return {
        "ote_high": ote_high,
        "ote_low":  ote_low,
        "range":    round(total_range, 2),
        "valid":    True,
    }


def price_in_ote(price: float, ote: dict) -> bool:
    """True if current price is inside the OTE zone."""
    if not ote.get("valid") or ote["ote_high"] is None:
        return False
    return ote["ote_low"] <= price <= ote["ote_high"]


# ── Economic calendar ──────────────────────────────────────────────────────────

# Hardcoded 2026 high-impact events (update annually)
# Format: (month, day, description, impact)
# impact: "extreme" = skip, "high" = raise threshold
_HARDCODED_2026 = [
    # NFP (first Friday of each month at 8:30 AM)
    (1,  2,  "NFP",          "extreme"),
    (2,  6,  "NFP",          "extreme"),
    (3,  6,  "NFP",          "extreme"),
    (4,  3,  "NFP",          "extreme"),
    (5,  1,  "NFP",          "extreme"),
    (6,  5,  "NFP",          "extreme"),
    (7,  2,  "NFP",          "extreme"),
    (8,  7,  "NFP",          "extreme"),
    (9,  4,  "NFP",          "extreme"),
    (10, 2,  "NFP",          "extreme"),
    (11, 6,  "NFP",          "extreme"),
    (12, 4,  "NFP",          "extreme"),
    # CPI (approximate monthly dates)
    (1,  15, "CPI",          "extreme"),
    (2,  12, "CPI",          "extreme"),
    (3,  12, "CPI",          "extreme"),
    (4,  10, "CPI",          "extreme"),
    (5,  13, "CPI",          "extreme"),
    (6,  11, "CPI",          "extreme"),
    (7,   9, "CPI",          "extreme"),
    (8,  12, "CPI",          "extreme"),
    (9,   9, "CPI",          "extreme"),
    (10, 13, "CPI",          "extreme"),
    (11, 12, "CPI",          "extreme"),
    (12, 10, "CPI",          "extreme"),
    # FOMC (approximate 2026 dates)
    (1,  29, "FOMC",         "extreme"),
    (3,  19, "FOMC",         "extreme"),
    (5,   7, "FOMC",         "extreme"),
    (6,  18, "FOMC",         "extreme"),
    (7,  30, "FOMC",         "extreme"),
    (9,  17, "FOMC",         "extreme"),
    (11,  5, "FOMC",         "extreme"),
    (12, 10, "FOMC",         "extreme"),
]


def check_news_calendar(now_est: datetime) -> dict:
    """
    Check if there is a high-impact news event near the current time.

    Rules:
      - Within 20 min BEFORE a known 8:30 AM release: raise min score by 2
      - Within 15 min AFTER  a known 8:30 AM release: skip entirely
      - Thursday 8:30 AM (jobless claims): raise min score by 1 always
      - FOMC/NFP/CPI day: raise min score by 1 for the full session

    Returns:
      skip:         bool  - True = do not take any trade right now
      score_penalty: int  - add this to min required score
      reason:        str
    """
    d   = now_est.date()
    tod = now_est.hour * 60 + now_est.minute

    # Thursday 8:30 AM jobless claims — every single Thursday
    is_thursday = now_est.weekday() == 3
    if is_thursday:
        # Hard blackout: 8:10-8:45 AM (15 min before + 15 min after)
        if 8 * 60 + 10 <= tod <= 8 * 60 + 45:
            return {"skip": True, "score_penalty": 0, "reason": "Jobless claims blackout window (8:10-8:45 AM)"}
        # Raised threshold all session on Thursday
        return {"skip": False, "score_penalty": 1, "reason": "Thursday: jobless claims day, +1 required"}

    # Check hardcoded calendar
    for month, day, label, impact in _HARDCODED_2026:
        if d.month == month and d.day == day:
            release_time = 8 * 60 + 30  # 8:30 AM
            if impact == "extreme":
                # 20 min before
                if release_time - 20 <= tod < release_time:
                    return {"skip": True,  "score_penalty": 0, "reason": f"{label} in {release_time - tod} min — blackout"}
                # 15 min after
                if release_time <= tod <= release_time + 15:
                    return {"skip": True,  "score_penalty": 0, "reason": f"{label} just released — blackout"}
                # Entire session elevated
                return {"skip": False, "score_penalty": 2, "reason": f"{label} day — extreme event, +2 required"}

    return {"skip": False, "score_penalty": 0, "reason": "No major news"}


# ── Power of 3 weekly profile ──────────────────────────────────────────────────

def get_weekly_profile(now_est: datetime) -> dict:
    """
    ICT Power of 3 weekly model.
    Returns the expected weekly phase and trading guidance for today.

    Monday (0):    Accumulation — range forms, both sides swept, choppy
    Tuesday (1):   Manipulation (Judas Swing) — fake move against real direction
    Wednesday (2): Distribution starts — real weekly move begins
    Thursday (3):  Continuation — news-driven, can extend or retrace
    Friday (4):    Close — profit taking, reversals common near close
    """
    dow = now_est.weekday()
    profiles = {
        0: {
            "phase":    "accumulation",
            "guidance": "Range forming. Sweeps may be noise. Wait for clean MSS.",
            "quality":  "normal",
            "note":     "Best day historically. Trust clean 4+ point setups.",
        },
        1: {
            "phase":    "manipulation",
            "guidance": "Judas Swing day. First sweep is often the fake. Wait for SECOND sweep or reversal of the first sweep before entering.",
            "quality":  "low",
            "note":     "Require SMT confirmation and OTE alignment. Skip if London is neutral.",
        },
        2: {
            "phase":    "distribution",
            "guidance": "Real weekly direction typically starts today. Good for sweep-reversal entries.",
            "quality":  "good",
            "note":     "Trade in the direction of London bias. OTE entries preferred.",
        },
        3: {
            "phase":    "continuation",
            "guidance": "Jobless claims at 8:30. Direction often set by 9:30. Trade with claims direction.",
            "quality":  "moderate",
            "note":     "Watch 8:30 AM claims direction. Score raised +1 automatically.",
        },
        4: {
            "phase":    "close",
            "guidance": "Profit taking near EOD. Good reversal potential in morning. Watch for week-closing liquidity sweep.",
            "quality":  "normal",
            "note":     "Normal rules apply. Avoid holding past 11:00 AM on large positions.",
        },
    }
    return profiles.get(dow, profiles[0])


# ── Master context builder ─────────────────────────────────────────────────────

def build_daily_context(
    nq_df: pd.DataFrame,
    trade_date: date,
    now_est: datetime | None = None,
    sweep_bar_idx: int | None = None,
    direction: str | None = None,
    swing_origin: float | None = None,
    sweep_extreme: float | None = None,
) -> dict:
    """
    Build the full market context for the current session.
    Call once at startup (for static data) and update during the session
    when sweep/MSS data becomes available.

    Returns a dict that live_detector and smart_filter can read.
    """
    if now_est is None:
        now_est = datetime.now(tz=EST)

    vix      = get_vix_regime()
    weekly   = get_weekly_levels(nq_df, trade_date)
    profile  = get_weekly_profile(now_est)
    news     = check_news_calendar(now_est)

    # SMT divergence requires sweep context
    smt = {"confirmed": True, "divergent": False, "detail": "not yet evaluated"}
    if sweep_bar_idx is not None and direction is not None:
        es_df = get_es_data()
        smt   = check_smt_divergence(nq_df, es_df, sweep_bar_idx, direction)

    # OTE zone requires swing origin and sweep extreme
    ote = {"valid": False}
    if swing_origin is not None and sweep_extreme is not None and direction is not None:
        ote = compute_ote_zone(swing_origin, sweep_extreme, direction)

    return {
        "vix":          vix,
        "weekly":       weekly,
        "profile":      profile,
        "news":         news,
        "smt":          smt,
        "ote":          ote,
        "trade_date":   trade_date.isoformat(),
        "dow":          now_est.weekday(),
    }


def context_score_penalty(ctx: dict) -> tuple[bool, int, str]:
    """
    Given a full context dict, return:
      skip:    True = do not trade at all right now
      penalty: int = extra points to add to min required score
      reason:  explanation string

    Penalty breakdown:
      News blackout:     skip=True
      Extreme VIX (>30): +3
      Very high VIX:     +2
      High VIX (>20):    +1
      Thursday:          +1 (from news check)
      SMT divergence:    +1
      NFP/CPI/FOMC day:  +2 (from news check)
    """
    news = ctx.get("news", {})
    if news.get("skip"):
        return True, 0, news.get("reason", "news blackout")

    total_penalty = 0
    reasons = []

    # News penalty
    np = news.get("score_penalty", 0)
    if np:
        total_penalty += np
        reasons.append(news.get("reason", "news"))

    # VIX penalty
    vp = ctx.get("vix", {}).get("score_penalty", 0)
    if vp:
        total_penalty += vp
        vix_val = ctx["vix"].get("vix")
        reasons.append(f"VIX {vix_val} ({ctx['vix']['regime']})")

    # SMT divergence penalty
    if ctx.get("smt", {}).get("divergent"):
        total_penalty += 1
        reasons.append(ctx["smt"]["detail"])

    reason = "  |  ".join(reasons) if reasons else "clean context"
    return False, total_penalty, reason
