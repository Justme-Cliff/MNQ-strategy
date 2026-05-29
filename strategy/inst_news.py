"""
Session News & Economic Calendar Reader.

Runs at monitor startup (~2-4 seconds). Fetches:
  1. News headlines for NQ-relevant tickers via yfinance
  2. Today's high-impact USD economic events via ForexFactory free JSON API

Classification:
  PRIMARY  — Claude Haiku (claude-haiku-4-5-20251001) if ANTHROPIC_API_KEY is set in .env
  FALLBACK — hardcoded keyword matching (no API key needed)

Haiku reads all headlines + calendar events and returns structured JSON:
  day_type, risk_level, key_events, skip_strategies, size_warning, brief, sentiment

Day types:
  normal         — nothing significant, trade normally
  data_release   — CPI / NFP / GDP / PCE / jobless claims / PPI today
  fomc           — Fed meeting, rate decision, or Powell speech
  earnings       — mega-cap Nasdaq earnings (NVDA, AAPL, MSFT, AMZN, GOOGL, META, TSLA)
  macro_stress   — geopolitical shock, banking crisis, debt ceiling

Risk levels:
  low      → trade normally
  elevated → reduce size, avoid mean-rev
  high     → skip VWAP Rev and FVG; ORB + Gap Fill only
  extreme  → consider sitting out entirely
"""
from __future__ import annotations
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

import yfinance as yf

# Load .env so ANTHROPIC_API_KEY is available
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass

try:
    import urllib.request as _urllib
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

EST = ZoneInfo("America/New_York")

HAIKU_MODEL    = "claude-haiku-4-5-20251001"
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
MAX_AGE_HOURS   = 18

NEWS_TICKERS = ["QQQ", "NQ=F", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA"]

# ── Fallback keyword tables ───────────────────────────────────────────────────

_FOMC_KEYWORDS = [
    "fed ", "federal reserve", "fomc", "powell", "rate decision", "rate hike",
    "rate cut", "interest rate", "monetary policy", "fed minutes", "beige book",
    "hawkish", "dovish", "basis points", "fed meeting", "fed chair",
]
_DATA_KEYWORDS = {
    "CPI":     ["cpi", "consumer price index", "inflation data", "inflation report"],
    "NFP":     ["nonfarm payroll", "non-farm payroll", "jobs report", "employment report", "payrolls"],
    "PCE":     ["pce", "personal consumption expenditure", "core pce"],
    "GDP":     ["gdp", "gross domestic product"],
    "PPI":     ["ppi", "producer price index"],
    "CLAIMS":  ["jobless claims", "unemployment claims", "initial claims"],
    "RETAIL":  ["retail sales"],
    "ISM":     ["ism manufacturing", "ism services", "pmi"],
    "HOUSING": ["housing starts", "existing home", "new home sales"],
}
_EARNINGS_TICKERS = {
    "NVDA":  ["nvidia", "nvda"],
    "AAPL":  ["apple", "aapl"],
    "MSFT":  ["microsoft", "msft"],
    "AMZN":  ["amazon", "amzn"],
    "GOOGL": ["alphabet", "google", "googl"],
    "META":  ["meta platforms", "meta ", "facebook"],
    "TSLA":  ["tesla", "tsla"],
    "NFLX":  ["netflix", "nflx"],
    "AMD":   ["amd", "advanced micro"],
    "INTC":  ["intel", "intc"],
    "QCOM":  ["qualcomm", "qcom"],
    "AVGO":  ["broadcom", "avgo"],
}
_STRESS_KEYWORDS = [
    "bank run", "banking crisis", "contagion", "credit default", "sovereign debt",
    "debt ceiling", "government shutdown", "geopolitical", "war escalat",
    "sanctions", "tariff shock", "flash crash", "circuit breaker",
    "recession fears", "liquidity crisis", "margin call",
]

_RISK_ORDER = ["low", "elevated", "high", "extreme"]


# ── Data fetchers ─────────────────────────────────────────────────────────────

def _fetch_yf_headlines(max_age_hours: int = MAX_AGE_HOURS) -> list[dict]:
    """Pull recent NQ-relevant headlines from yfinance. Handles both old and new API structure."""
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    seen: set[str] = set()
    articles: list[dict] = []

    for ticker_sym in NEWS_TICKERS:
        try:
            news = yf.Ticker(ticker_sym).news or []
            for item in news:
                content  = item.get("content", item)
                title    = content.get("title", "") or item.get("title", "")
                if not title or title in seen:
                    continue

                pub_str = content.get("pubDate", "") or content.get("displayTime", "")
                if pub_str:
                    try:
                        pub_time = datetime.fromisoformat(
                            pub_str.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        pub_time = 0
                else:
                    pub_time = float(item.get("providerPublishTime", 0))

                if pub_time and pub_time < cutoff:
                    continue

                seen.add(title)
                age_h = (datetime.now().timestamp() - pub_time) / 3600 if pub_time else 0
                url = (content.get("canonicalUrl") or {}).get("url", "") or item.get("link", "")
                articles.append({
                    "title":     title,
                    "ticker":    ticker_sym,
                    "age_hours": round(age_h, 1),
                    "url":       url,
                })
        except Exception:
            continue

    articles.sort(key=lambda x: x["age_hours"])
    return articles


def _fetch_ff_calendar(today: date) -> list[dict]:
    """Fetch USD economic events from ForexFactory free JSON feed."""
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

    events: list[dict] = []
    for item in data:
        raw_date = item.get("date", "")
        try:
            event_date = (
                datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                if "-" in raw_date
                else datetime.strptime(raw_date, "%B %d, %Y").date()
            )
        except Exception:
            continue
        if event_date != today:
            continue
        country = item.get("country", "").upper()
        if country and country != "USD":
            continue
        events.append({
            "time":     item.get("time", ""),
            "title":    item.get("title", ""),
            "impact":   item.get("impact", "").lower(),
            "forecast": item.get("forecast", ""),
            "previous": item.get("previous", ""),
        })
    return events


# ── Haiku classifier ──────────────────────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key if key else None


def _classify_with_haiku(
    headlines: list[dict],
    calendar_events: list[dict],
    today: date,
) -> Optional[dict]:
    """
    Use Claude Haiku to classify the trading day from news + calendar.
    Returns the classification dict, or None if the call fails.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    # Build compact context for the prompt
    cal_lines = []
    for e in calendar_events:
        impact = e["impact"].upper()
        time_s = e["time"] or "time TBD"
        cal_lines.append(f"  [{impact}] {time_s} — {e['title']}")
    calendar_text = "\n".join(cal_lines) if cal_lines else "  (none)"

    headline_lines = [f"  · {h['title']}" for h in headlines[:20]]
    headlines_text = "\n".join(headline_lines) if headline_lines else "  (none)"

    prompt = f"""You are an NQ/Nasdaq futures day trading assistant. Analyze today's news and economic calendar for a trader using the 9:30 AM–noon ET morning session.

Today: {today.strftime("%A, %B %d, %Y")}

Economic Calendar (USD events today):
{calendar_text}

Recent Headlines (NQ/Nasdaq-relevant):
{headlines_text}

Classify the trading day and return ONLY valid JSON with these exact fields:
{{
  "day_type": "normal" | "data_release" | "fomc" | "earnings" | "macro_stress",
  "risk_level": "low" | "elevated" | "high" | "extreme",
  "key_events": ["list of 2-5 most important items as short strings"],
  "skip_strategies": ["list from: vwap_rev, fvg, ib_breakout, vwap_bounce, orb"],
  "size_warning": true | false,
  "sentiment": "bullish" | "bearish" | "neutral",
  "brief": "one sentence: what the trader needs to know right now, max 100 chars"
}}

Rules:
- fomc/Fed speeches → risk high, skip vwap_rev + fvg + ib_breakout
- CPI/NFP/PCE/GDP → risk elevated-high, skip vwap_rev
- Mega-cap earnings (NVDA/AAPL/MSFT/AMZN/GOOGL/META) → risk elevated, note vol spike risk
- Banking crisis / geopolitical shock → risk high or extreme
- Normal quiet day → risk low, skip_strategies empty
- Only skip ORB on extreme risk days
Return ONLY the JSON object, no markdown, no explanation."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if Haiku wrapped the JSON
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)

        # Validate and normalise required fields
        valid_day_types = {"normal", "data_release", "fomc", "earnings", "macro_stress"}
        valid_risk      = {"low", "elevated", "high", "extreme"}
        valid_strats    = {"vwap_rev", "fvg", "ib_breakout", "vwap_bounce", "orb", "vwap_pm"}

        return {
            "day_type":        parsed.get("day_type", "normal") if parsed.get("day_type") in valid_day_types else "normal",
            "risk_level":      parsed.get("risk_level", "low")  if parsed.get("risk_level")  in valid_risk      else "low",
            "key_events":      [str(e) for e in parsed.get("key_events", [])][:6],
            "skip_strategies": [s for s in parsed.get("skip_strategies", []) if s in valid_strats],
            "size_warning":    bool(parsed.get("size_warning", False)),
            "sentiment":       parsed.get("sentiment", "neutral"),
            "brief":           str(parsed.get("brief", ""))[:120],
            "headlines_shown": [h["title"] for h in headlines[:5]],
            "calendar_events": calendar_events,
            "earnings_today":  [k for k, v in _EARNINGS_TICKERS.items()
                                 if any(kw in headlines_text.lower() for kw in v)],
            "_source": "haiku",
        }
    except Exception:
        return None


# ── Keyword fallback classifier ───────────────────────────────────────────────

def _classify_keywords(
    headlines: list[dict],
    calendar_events: list[dict],
    today: date,
) -> dict:
    """Hardcoded keyword classification — used when no API key is available."""
    all_text  = " ".join(h["title"] for h in headlines).lower()
    cal_text  = " ".join(e["title"] for e in calendar_events).lower()
    combined  = all_text + " " + cal_text

    day_type   = "normal"
    risk_level = "low"
    key_events: list[str] = []

    def _raise_risk(new_level: str) -> str:
        return new_level if _RISK_ORDER.index(new_level) > _RISK_ORDER.index(risk_level) else risk_level

    # Calendar — high-impact events are the most reliable signal
    for e in calendar_events:
        if e["impact"] not in ("high", "red"):
            continue
        t = e["title"].lower()
        time_s = e.get("time", "")
        label = f"{e['title']} at {time_s}" if time_s else e["title"]

        if any(kw in t for kw in ["fomc", "rate decision", "federal open", "fed minutes"]):
            day_type = "fomc"
            risk_level = _raise_risk("high")
            key_events.append(f"[FOMC] {label}")
        elif any(kw in t for kw in ["cpi", "consumer price", "pce", "nonfarm", "payroll",
                                     "gdp", "retail sales", "ppi", "ism"]):
            if day_type not in ("fomc",):
                day_type = "data_release"
            risk_level = _raise_risk("elevated")
            key_events.append(f"[DATA] {label}")
        elif "jobless" in t or "claims" in t:
            risk_level = _raise_risk("elevated")
            key_events.append(f"[DATA] {label}")

    # Add medium-impact calendar items as info
    for e in calendar_events:
        if e["impact"] in ("medium", "orange"):
            key_events.append(f"[CAL] {e['title']}")

    # Headlines — FOMC
    if any(kw in combined for kw in _FOMC_KEYWORDS) and day_type == "normal":
        day_type = "fomc"
        risk_level = _raise_risk("high")
        key_events.insert(0, "Fed/FOMC activity in headlines")

    # Headlines — data releases
    for name, kws in _DATA_KEYWORDS.items():
        if any(kw in combined for kw in kws) and day_type == "normal":
            day_type = "data_release"
            risk_level = _raise_risk("elevated")
            key_events.append(f"[DATA] {name}")

    # Earnings
    earnings: list[str] = []
    for company, kws in _EARNINGS_TICKERS.items():
        if any(kw in combined for kw in kws):
            earnings.append(company)
    if earnings:
        if day_type == "normal":
            day_type = "earnings"
        risk_level = _raise_risk("elevated")
        key_events.append(f"[EARNINGS] {', '.join(earnings[:4])}")

    # Macro stress
    if any(kw in combined for kw in _STRESS_KEYWORDS):
        risk_level = _raise_risk("high")
        if day_type == "normal":
            day_type = "macro_stress"
        key_events.insert(0, "Macro stress keywords detected")

    # Build skip list and brief
    if risk_level == "elevated":
        skips = ["vwap_rev"]
    elif risk_level == "high":
        skips = ["vwap_rev", "fvg", "ib_breakout"]
    elif risk_level == "extreme":
        skips = ["vwap_rev", "fvg", "ib_breakout", "vwap_bounce", "vwap_pm"]
    else:
        skips = []

    briefs = {
        "normal":       "NEWS: Clean day — no high-impact events. Trade all strategies normally.",
        "fomc":         "NEWS: FOMC/FED DAY — risk HIGH. Skip VWAP/FVG. ORB + Gap Fill only.",
        "data_release": f"NEWS: {key_events[0].replace('[DATA] ','') if key_events else 'Data release'} today — risk ELEVATED. Caution on mean-rev.",
        "earnings":     f"NEWS: {', '.join(earnings[:2])} earnings — vol spike risk. ORB range may be wide.",
        "macro_stress": "NEWS: Macro stress detected — reduce sizing, prefer breakout over mean-rev.",
    }

    return {
        "day_type":        day_type,
        "risk_level":      risk_level,
        "key_events":      key_events[:6],
        "skip_strategies": skips,
        "size_warning":    risk_level in ("high", "extreme"),
        "sentiment":       "neutral",
        "brief":           briefs.get(day_type, f"NEWS: {day_type} day — risk {risk_level}."),
        "headlines_shown": [h["title"] for h in headlines[:5]],
        "calendar_events": calendar_events,
        "earnings_today":  earnings,
        "_source":         "keywords",
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_session_news(today: Optional[date] = None) -> dict:
    """
    Fetch + classify all session news. Call once at monitor startup (~2-4s).

    Flow:
      1. Fetch yfinance headlines + ForexFactory calendar
      2. If ANTHROPIC_API_KEY in .env → classify with Haiku (smart, contextual)
      3. Else → classify with keyword matching (fast, no key needed)
      4. On any error → safe 'normal/low' default (monitor never crashes)
    """
    if today is None:
        today = date.today()

    default = {
        "day_type": "normal", "risk_level": "low",
        "key_events": [], "skip_strategies": [], "size_warning": False,
        "sentiment": "neutral",
        "brief": "NEWS: Could not fetch — assuming normal day.",
        "headlines_shown": [], "calendar_events": [], "earnings_today": [],
        "_source": "default",
    }

    try:
        headlines = _fetch_yf_headlines()
    except Exception:
        headlines = []

    try:
        calendar = _fetch_ff_calendar(today)
    except Exception:
        calendar = []

    # Try Haiku first
    result = _classify_with_haiku(headlines, calendar, today)

    # Fall back to keywords if Haiku unavailable or failed
    if result is None:
        try:
            result = _classify_keywords(headlines, calendar, today)
        except Exception:
            result = default

    return result
