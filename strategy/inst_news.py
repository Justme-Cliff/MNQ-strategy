"""
Session News & Economic Calendar Reader.

Runs at monitor startup (~2 seconds). Fetches:
  1. News headlines for NQ-relevant tickers via yfinance
  2. Today's high-impact economic events via ForexFactory free JSON API
     (https://nfs.faireconomy.media/ff_calendar_thisweek.json)

Classifies the day into one of five types and prints a one-line brief
at session open so you know what you're walking into before 9:30 AM.

Day types:
  normal         — nothing significant, trade normally
  data_release   — CPI / NFP / GDP / PCE / jobless claims / PPI today
  fomc           — Fed meeting, rate decision, or Powell speech
  earnings       — mega-cap Nasdaq earnings (AAPL, NVDA, MSFT, AMZN, GOOGL, META, TSLA)
  macro_stress   — geopolitical shock, debt ceiling, banking crisis in headlines

Risk levels:
  low      → trade normally
  elevated → reduce size, avoid mean-rev, prefer Gap Fill / ORB
  high     → skip VWAP Rev and FVG; ORB only with tight stops
  extreme  → consider sitting out entirely
"""
from __future__ import annotations
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import yfinance as yf

try:
    import urllib.request as _urllib
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

EST = ZoneInfo("America/New_York")

# Tickers to pull news from — NQ proxy + top Nasdaq weights
NEWS_TICKERS = ["QQQ", "NQ=F", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA"]

# ForexFactory free calendar JSON (USD events only, current week)
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Max age of a news article to be considered relevant (hours)
MAX_AGE_HOURS = 18

# ── Keyword classifiers ───────────────────────────────────────────────────────

_FOMC_KEYWORDS = [
    "fed ", "federal reserve", "fomc", "powell", "rate decision", "rate hike",
    "rate cut", "interest rate", "monetary policy", "fed minutes", "beige book",
    "fed chair", "hawkish", "dovish", "basis points", "fed meeting",
]

_DATA_KEYWORDS = {
    "CPI":      ["cpi", "consumer price index", "inflation data", "inflation report"],
    "NFP":      ["nonfarm payroll", "non-farm payroll", "jobs report", "employment report", "payrolls"],
    "PCE":      ["pce", "personal consumption expenditure", "core pce"],
    "GDP":      ["gdp", "gross domestic product"],
    "PPI":      ["ppi", "producer price index"],
    "CLAIMS":   ["jobless claims", "unemployment claims", "initial claims"],
    "RETAIL":   ["retail sales"],
    "ISM":      ["ism manufacturing", "ism services", "pmi"],
    "HOUSING":  ["housing starts", "existing home", "new home sales"],
}

_EARNINGS_TICKERS = {
    "NVDA": ["nvidia", "nvda"],
    "AAPL": ["apple", "aapl"],
    "MSFT": ["microsoft", "msft"],
    "AMZN": ["amazon", "amzn"],
    "GOOGL": ["alphabet", "google", "googl", "goog"],
    "META": ["meta platforms", "meta ", "facebook"],
    "TSLA": ["tesla", "tsla"],
    "NFLX": ["netflix", "nflx"],
    "AMD":  ["amd", "advanced micro"],
    "INTC": ["intel", "intc"],
    "QCOM": ["qualcomm", "qcom"],
    "AVGO": ["broadcom", "avgo"],
}

_STRESS_KEYWORDS = [
    "bank run", "banking crisis", "contagion", "credit default", "sovereign debt",
    "debt ceiling", "government shutdown", "geopolitical", "war escalat",
    "sanctions", "tariff shock", "flash crash", "circuit breaker",
    "recession fears", "liquidity crisis", "margin call",
]

_POSITIVE_KEYWORDS = [
    "beat estimates", "strong earnings", "record revenue", "buyback",
    "upgrade", "ai boom", "chip demand", "strong gdp", "soft landing",
]


# ── Fetch news from yfinance ──────────────────────────────────────────────────

def _fetch_yf_headlines(max_age_hours: int = MAX_AGE_HOURS) -> list[dict]:
    """
    Pull recent news headlines from yfinance for NQ-relevant tickers.
    Returns list of {title, ticker, age_hours, url}.
    """
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    seen: set[str] = set()
    articles: list[dict] = []

    for ticker_sym in NEWS_TICKERS:
        try:
            t = yf.Ticker(ticker_sym)
            news = t.news or []
            for item in news:
                # yfinance ≥0.2.50 nests content under item["content"]
                content = item.get("content", item)
                title   = content.get("title", "") or item.get("title", "")
                if not title or title in seen:
                    continue

                # Parse publish time — new API uses ISO string, old uses unix int
                pub_date_str = content.get("pubDate", "") or content.get("displayTime", "")
                if pub_date_str:
                    try:
                        pub_time = datetime.fromisoformat(
                            pub_date_str.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        pub_time = 0
                else:
                    pub_time = item.get("providerPublishTime", 0)

                if pub_time and pub_time < cutoff:
                    continue

                seen.add(title)
                age_h = (datetime.now().timestamp() - pub_time) / 3600 if pub_time else 0
                url = (content.get("canonicalUrl") or {}).get("url", "") \
                      or item.get("link", "")
                articles.append({
                    "title":     title,
                    "ticker":    ticker_sym,
                    "age_hours": round(age_h, 1),
                    "url":       url,
                })
        except Exception:
            continue

    # Sort newest first
    articles.sort(key=lambda x: x["age_hours"])
    return articles


# ── Fetch ForexFactory economic calendar ─────────────────────────────────────

def _fetch_ff_calendar(today: date) -> list[dict]:
    """
    Fetch USD economic events for today from ForexFactory's free JSON feed.
    Returns list of {time, title, impact, forecast, previous}.
    """
    if not _HAS_URLLIB:
        return []

    try:
        req = _urllib.Request(
            FF_CALENDAR_URL,
            headers={"User-Agent": "Mozilla/5.0 NQQuantSystem/5.0"}
        )
        with _urllib.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    today_str = today.strftime("%Y-%m-%d")
    events: list[dict] = []

    for item in data:
        # ForexFactory date format: "May 29, 2026" or "2026-05-29"
        raw_date = item.get("date", "")
        try:
            if "-" in raw_date:
                event_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            else:
                event_date = datetime.strptime(raw_date, "%B %d, %Y").date()
        except Exception:
            continue

        if event_date != today:
            continue

        country = item.get("country", "").upper()
        if country and country != "USD":
            continue

        impact = item.get("impact", "").lower()
        events.append({
            "time":     item.get("time", ""),
            "title":    item.get("title", ""),
            "impact":   impact,
            "forecast": item.get("forecast", ""),
            "previous": item.get("previous", ""),
        })

    return events


# ── Classify the day ──────────────────────────────────────────────────────────

def _match_keywords(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw in t for kw in keywords)


def classify_news_day(
    headlines: list[dict],
    calendar_events: list[dict],
    today: date,
) -> dict:
    """
    Classify the session day type from headlines and calendar events.

    Returns:
      day_type          : "normal"|"data_release"|"fomc"|"earnings"|"macro_stress"
      risk_level        : "low"|"elevated"|"high"|"extreme"
      key_events        : list[str] — most important items for display
      skip_strategies   : list[str] — strategy names to skip today
      size_warning      : bool — True if sizing should be reduced
      brief             : str — one-line summary for monitor display
      headlines_shown   : list[str] — top 5 headlines for display
    """
    all_text = " ".join(h["title"] for h in headlines).lower()
    cal_titles = " ".join(e["title"] for e in calendar_events).lower()
    combined = all_text + " " + cal_titles

    day_type   = "normal"
    risk_level = "low"
    key_events: list[str] = []
    skip_strats: list[str] = []

    # ── Check calendar events first (most reliable) ───────────────────────────
    high_impact_cal = [e for e in calendar_events if e["impact"] in ("high", "red")]
    medium_impact_cal = [e for e in calendar_events if e["impact"] in ("medium", "orange")]

    for event in high_impact_cal:
        t = event["title"].lower()
        time_str = event.get("time", "")
        label = f"{event['title']} at {time_str}" if time_str else event["title"]

        if any(kw in t for kw in ["fomc", "fed", "rate decision", "fomc minutes", "federal open"]):
            day_type = "fomc"
            risk_level = "high"
            key_events.append(f"[FOMC] {label}")
        elif any(kw in t for kw in ["cpi", "consumer price", "pce", "gdp", "nonfarm", "payroll",
                                     "employment", "retail sales", "ppi", "ism"]):
            if day_type != "fomc":
                day_type = "data_release"
            risk_level = max(risk_level, "elevated", key=lambda x: ["low","elevated","high","extreme"].index(x))
            key_events.append(f"[DATA] {label}")
        elif "jobless" in t or "claims" in t:
            risk_level = max(risk_level, "elevated", key=lambda x: ["low","elevated","high","extreme"].index(x))
            key_events.append(f"[DATA] {label}")

    for event in medium_impact_cal:
        t = event["title"]
        key_events.append(f"[CAL] {t}")

    # ── Scan news headlines ───────────────────────────────────────────────────
    if _match_keywords(combined, _FOMC_KEYWORDS) and day_type == "normal":
        day_type = "fomc"
        risk_level = "high"
        key_events.insert(0, "Fed/FOMC activity detected in headlines")

    # Data releases from headlines (if calendar missed it)
    for release_name, kws in _DATA_KEYWORDS.items():
        if _match_keywords(combined, kws) and day_type == "normal":
            day_type = "data_release"
            if risk_level == "low":
                risk_level = "elevated"
            key_events.append(f"[DATA] {release_name} in news")

    # Mega-cap earnings
    earnings_companies: list[str] = []
    for company, kws in _EARNINGS_TICKERS.items():
        if _match_keywords(combined, kws + ["earnings", "results", "beat", "miss"]):
            earnings_companies.append(company)
    if earnings_companies:
        if day_type == "normal":
            day_type = "earnings"
        if risk_level == "low":
            risk_level = "elevated"
        key_events.append(f"[EARNINGS] {', '.join(earnings_companies[:3])}")

    # Macro stress
    if _match_keywords(combined, _STRESS_KEYWORDS):
        if risk_level in ("low", "elevated"):
            risk_level = "high"
        if day_type == "normal":
            day_type = "macro_stress"
        key_events.insert(0, "Macro stress keywords detected")

    # ── Determine strategy adjustments ───────────────────────────────────────
    if risk_level == "elevated":
        skip_strats = ["vwap_rev"]
    elif risk_level in ("high", "extreme"):
        skip_strats = ["vwap_rev", "fvg", "ib_breakout"]

    if risk_level == "extreme":
        skip_strats = ["vwap_rev", "fvg", "ib_breakout", "vwap_bounce", "vwap_pm"]

    size_warning = risk_level in ("high", "extreme")

    # ── Build one-line brief ──────────────────────────────────────────────────
    if day_type == "normal" and risk_level == "low":
        brief = "NEWS: Clean — no high-impact events today. Trade normally."
    elif day_type == "fomc":
        brief = f"NEWS: FOMC/FED DAY — risk HIGH. Skip VWAP/FVG. ORB + Gap Fill only."
    elif day_type == "data_release":
        event_names = [e for e in key_events if e.startswith("[DATA]")]
        data_str = event_names[0].replace("[DATA] ", "") if event_names else "data release"
        brief = f"NEWS: {data_str} today — risk ELEVATED. Avoid mean-rev at release time."
    elif day_type == "earnings":
        comp_str = ", ".join(earnings_companies[:2])
        brief = f"NEWS: {comp_str} earnings — vol spike risk. ORB range may be wide."
    elif day_type == "macro_stress":
        brief = "NEWS: Macro stress detected — reduce sizing, prefer breakout over mean-rev."
    else:
        brief = f"NEWS: {day_type.upper()} day — risk {risk_level.upper()}. Stay alert."

    # ── Top 5 headlines for display ───────────────────────────────────────────
    top_headlines = [h["title"] for h in headlines[:5]]

    return {
        "day_type":        day_type,
        "risk_level":      risk_level,
        "key_events":      key_events[:6],
        "skip_strategies": skip_strats,
        "size_warning":    size_warning,
        "brief":           brief,
        "headlines_shown": top_headlines,
        "calendar_events": calendar_events,
        "earnings_today":  earnings_companies,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_session_news(today: Optional[date] = None) -> dict:
    """
    Fetch + classify all session news. Call once at monitor startup.
    Typically completes in 1-3 seconds.

    Returns the full classification dict from classify_news_day().
    On any failure, returns a safe 'normal/low' default so the monitor
    never crashes due to a news fetch error.
    """
    if today is None:
        today = date.today()

    default = {
        "day_type": "normal", "risk_level": "low",
        "key_events": [], "skip_strategies": [], "size_warning": False,
        "brief": "NEWS: Could not fetch (offline?) — assuming normal day.",
        "headlines_shown": [], "calendar_events": [], "earnings_today": [],
    }

    try:
        headlines = _fetch_yf_headlines()
    except Exception:
        headlines = []

    try:
        calendar = _fetch_ff_calendar(today)
    except Exception:
        calendar = []

    try:
        return classify_news_day(headlines, calendar, today)
    except Exception:
        return default
