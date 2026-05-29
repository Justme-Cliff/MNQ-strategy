"""
Bot Memory — adaptive signal scoring and self-improvement via JSON trade log.

What this does:
  1. Logs every signal fired (before user confirms taking it)
  2. Updates when user confirms: taken=True/False
  3. Updates when user reports outcome: WIN / LOSS
  4. Uses real trade history to:
       - Adjust per-strategy confidence (regime-contextual WR)
       - Auto-pause after 3 consecutive losses or daily loss limit
       - Flag weak strategies underperforming in current regime
  5. Shows what it learned at each session open

The bot is NOT a fish — every trade it remembers improves the next one.

File: journal/bot_memory.json
"""
from __future__ import annotations
import json
import os
import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

MEMORY_PATH = os.path.join(os.path.dirname(__file__), "..", "journal", "bot_memory.json")

# Thresholds
WR_SIZE_UP      = 0.75   # recent WR >= 75% on real trades → 2 contracts
WR_SIZE_DOWN    = 0.50   # recent WR <  50% → flag strategy as weak
LOOKBACK        = 20     # trades to look back for global WR
REGIME_LOOKBACK = 10     # trades per regime context for regime-specific WR
MAX_CONSEC_L    = 3      # consecutive losses before pausing
DAILY_LIMIT     = 150.0  # daily loss limit ($)
MIN_TRADES_LEARN = 5     # minimum trades before trusting a WR estimate


# ── Load / Save ───────────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return _blank_memory()
    try:
        with open(MEMORY_PATH, "r") as f:
            data = json.load(f)
        # Migrate old format if needed
        if "signals" not in data:
            data["signals"] = []
        if "regime_stats" not in data:
            data["regime_stats"] = {}
        if "insights" not in data:
            data["insights"] = []
        return data
    except Exception:
        return _blank_memory()


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    with open(MEMORY_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _blank_memory() -> dict:
    return {
        "trades":      [],        # legacy backtest trades (kept)
        "signals":     [],        # live signals: fired → taken? → outcome
        "session":     _blank_session(),
        "adaptive":    _blank_adaptive(),
        "regime_stats": {},       # {strategy+regime_key: {wins, losses}}
        "insights":    [],        # what the bot learned this week
    }


def _blank_session() -> dict:
    return {
        "date":              str(date.today()),
        "confirmed_trades":  0,     # only trades user actually confirmed taking
        "daily_pnl":         0.0,
        "paused":            False,
        "pause_reason":      "",
        "pending_signal_id": None,  # signal waiting for outcome report
    }


def _blank_adaptive() -> dict:
    return {
        "contracts":           1,
        "last_update":         str(date.today()),
        "recent_wr":           None,
        "consecutive_losses":  0,
        "weak_strategies":     [],
        "conf_adjustments":    {},  # {strategy: delta} — applied to 12-pt scoring
        "notes":               "Starting fresh — no real trade history yet.",
    }


# ── Session management ────────────────────────────────────────────────────────

def _get_session(data: dict) -> dict:
    if data["session"]["date"] != str(date.today()):
        data["session"] = _blank_session()
    return data["session"]


# ── Regime key builder ────────────────────────────────────────────────────────

def _regime_key(vix_regime: str = "", trend: str = "", day_name: str = "") -> str:
    """
    Build a regime context key for regime-specific learning.
    Granular enough to be useful, coarse enough to accumulate data quickly.
    e.g. "vix:normal|trend:bull|day:Mon"
    """
    parts = []
    if vix_regime:
        parts.append(f"vix:{vix_regime}")
    if trend in ("strong_bull", "bull", "neutral", "bear", "strong_bear"):
        # Simplify to 3 buckets to accumulate data faster
        simplified = "bull" if "bull" in trend else ("bear" if "bear" in trend else "neutral")
        parts.append(f"trend:{simplified}")
    return "|".join(parts) if parts else "regime:any"


# ── Log a fired signal (before confirmation) ─────────────────────────────────

def log_signal(
    strategy:   str,
    direction:  str,
    entry:      float,
    stop:       float,
    target:     float,
    vix:        float = 0.0,
    atr:        float = 0.0,
    trend:      str   = "",
    vix_regime: str   = "",
    day_name:   str   = "",
    confidence_score: int = 0,
) -> str:
    """
    Log a signal the bot fired. Returns a signal_id for later updates.
    Call this immediately when displaying a signal to the user.
    """
    data    = _load()
    session = _get_session(data)

    signal_id = str(uuid.uuid4())[:8]
    signal = {
        "id":               signal_id,
        "timestamp":        datetime.now().isoformat(timespec="seconds"),
        "date":             str(date.today()),
        "day":              day_name,
        "strategy":         strategy,
        "direction":        direction,
        "entry":            round(entry, 2),
        "stop":             round(stop, 2),
        "target":           round(target, 2),
        "vix":              round(vix, 1),
        "atr":              round(atr, 1),
        "trend":            trend,
        "vix_regime":       vix_regime,
        "confidence_score": confidence_score,
        "taken":            None,   # True/False — set by user confirmation
        "outcome":          None,   # "WIN"/"LOSS" — set by user report
        "pnl":              None,
        "exit_price":       None,
        "regime_key":       _regime_key(vix_regime, trend, day_name),
    }

    data["signals"].append(signal)
    session["pending_signal_id"] = signal_id
    _save(data)
    return signal_id


# ── Update: did user take it? ─────────────────────────────────────────────────

def confirm_signal_taken(signal_id: str, taken: bool) -> None:
    """
    Mark whether the user actually took the trade.
    If taken=False, the slot stays free (doesn't count toward daily limit).
    """
    data    = _load()
    session = _get_session(data)

    for sig in data["signals"]:
        if sig["id"] == signal_id:
            sig["taken"] = taken
            break

    if taken:
        session["confirmed_trades"] += 1

    _save(data)


# ── Update: report outcome ────────────────────────────────────────────────────

def report_outcome(
    signal_id:   str,
    outcome:     str,    # "WIN" or "LOSS"
    pnl:         float,
    exit_price:  float = 0.0,
) -> None:
    """
    Record the actual trade result. Call this when user types the outcome.
    Updates regime stats and adaptive scoring.
    """
    data    = _load()
    session = _get_session(data)

    for sig in data["signals"]:
        if sig["id"] == signal_id:
            sig["outcome"]    = outcome.upper()
            sig["pnl"]        = round(pnl, 2)
            sig["exit_price"] = round(exit_price, 2)
            break

    session["daily_pnl"] = round(session["daily_pnl"] + pnl, 2)
    session["pending_signal_id"] = None

    _update_regime_stats(data)
    _update_adaptive(data)
    _generate_insights(data)
    _save(data)


# ── Update regime stats ───────────────────────────────────────────────────────

def _update_regime_stats(data: dict) -> None:
    """Rebuild per-strategy regime win rate from all real trades taken."""
    stats: dict = defaultdict(lambda: {"wins": 0, "losses": 0})

    for sig in data["signals"]:
        if sig.get("taken") is not True or sig.get("outcome") is None:
            continue
        key = f"{sig['strategy']}|{sig.get('regime_key', 'regime:any')}"
        if sig["outcome"] == "WIN":
            stats[key]["wins"]   += 1
        else:
            stats[key]["losses"] += 1

    data["regime_stats"] = {k: dict(v) for k, v in stats.items()}


# ── Adaptive logic ────────────────────────────────────────────────────────────

def _update_adaptive(data: dict) -> None:
    """
    Recalculate contract sizing, strategy confidence adjustments, and pause logic
    from real trade history (signals where taken=True and outcome is known).
    """
    real_trades = [
        s for s in data["signals"]
        if s.get("taken") is True and s.get("outcome") is not None
    ]
    session = data["session"]
    adap    = data["adaptive"]

    if not real_trades:
        adap["notes"] = "No real trades yet — using default sizing."
        return

    recent = real_trades[-LOOKBACK:]
    wins   = [t for t in recent if t["outcome"] == "WIN"]
    wr     = len(wins) / len(recent)
    adap["recent_wr"] = round(wr, 3)

    # Consecutive losses
    consec = 0
    for t in reversed(real_trades):
        if t["outcome"] == "LOSS":
            consec += 1
        else:
            break
    adap["consecutive_losses"] = consec

    # Contract sizing from real WR
    if wr >= WR_SIZE_UP and consec == 0:
        adap["contracts"] = 2
        adap["notes"] = f"REAL EDGE: {wr*100:.0f}% WR on {len(recent)} real trades → 2 contracts"
    else:
        adap["contracts"] = 1
        if consec >= MAX_CONSEC_L:
            adap["notes"] = f"{consec} consecutive real losses → 1 contract, consider stopping"
        else:
            adap["notes"] = f"WR {wr*100:.0f}% on {len(recent)} real trades → 1 contract"

    # Auto-pause
    if consec >= MAX_CONSEC_L:
        session["paused"]       = True
        session["pause_reason"] = f"{consec} consecutive losses"
    if session["daily_pnl"] <= -DAILY_LIMIT:
        session["paused"]       = True
        session["pause_reason"] = f"Daily loss limit hit (${abs(session['daily_pnl']):.0f})"

    # Per-strategy confidence adjustments
    strat_recent: dict = defaultdict(list)
    for t in recent:
        strat_recent[t["strategy"]].append(t)

    conf_adjustments: dict[str, int] = {}
    weak: list[str] = []

    for s, ts in strat_recent.items():
        if len(ts) < MIN_TRADES_LEARN:
            conf_adjustments[s] = 0
            continue
        s_wr = sum(1 for t in ts if t["outcome"] == "WIN") / len(ts)
        if s_wr >= 0.80:
            conf_adjustments[s] = +1   # hot — boost confidence score
        elif s_wr < WR_SIZE_DOWN:
            conf_adjustments[s] = -1   # cold — reduce confidence score
            weak.append(f"{s} ({s_wr*100:.0f}% on {len(ts)} real trades)")
        else:
            conf_adjustments[s] = 0

    adap["conf_adjustments"] = conf_adjustments
    adap["weak_strategies"]  = weak
    adap["last_update"]      = str(date.today())


# ── Insights generator ────────────────────────────────────────────────────────

def _generate_insights(data: dict) -> None:
    """
    Generate human-readable insights from the regime stats.
    Shown at session open so the bot tells you what it learned.
    """
    insights: list[str] = []
    stats = data.get("regime_stats", {})

    for key, s in stats.items():
        total = s["wins"] + s["losses"]
        if total < MIN_TRADES_LEARN:
            continue
        wr = s["wins"] / total
        strategy, regime = key.split("|", 1) if "|" in key else (key, "")
        regime_str = regime.replace("|", " + ").replace(":", "=")

        if wr >= 0.80:
            insights.append(f"✓ {strategy} {wr*100:.0f}% WR in [{regime_str}] ({total} trades) — HOT")
        elif wr < 0.45:
            insights.append(f"✗ {strategy} {wr*100:.0f}% WR in [{regime_str}] ({total} trades) — AVOID")

    data["insights"] = insights[-10:]  # keep last 10 insights


# ── Query functions ───────────────────────────────────────────────────────────

def get_sizing() -> int:
    """Return current contract count (1 or 2) based on REAL trade history."""
    data = _load()
    _get_session(data)
    return data["adaptive"]["contracts"]


def is_paused() -> tuple[bool, str]:
    """Return (paused, reason). Check before taking any trade."""
    data    = _load()
    session = _get_session(data)
    return session["paused"], session.get("pause_reason", "")


def get_confirmed_trades_today() -> int:
    """Number of trades user actually confirmed taking today."""
    data    = _load()
    session = _get_session(data)
    return session["confirmed_trades"]


def get_conf_adjustment(strategy: str) -> int:
    """
    Returns a delta (-1, 0, +1) to apply to the 12-point confidence score
    for this strategy, based on its recent real-trade performance.
    """
    data = _load()
    adj  = data["adaptive"].get("conf_adjustments", {})
    return int(adj.get(strategy, 0))


def get_status() -> dict:
    """Full status snapshot for display."""
    data    = _load()
    session = _get_session(data)
    adap    = data["adaptive"]

    real_trades = [
        s for s in data["signals"]
        if s.get("taken") is True and s.get("outcome") is not None
    ]
    today_real = [
        s for s in data["signals"]
        if s["date"] == str(date.today()) and s.get("taken") is True
    ]
    today_pnl = sum(s.get("pnl", 0) or 0 for s in today_real if s.get("pnl") is not None)

    return {
        "total_real_trades":    len(real_trades),
        "confirmed_today":      session["confirmed_trades"],
        "daily_pnl":            today_pnl,
        "paused":               session["paused"],
        "pause_reason":         session.get("pause_reason", ""),
        "contracts_next":       adap["contracts"],
        "recent_wr":            adap["recent_wr"],
        "consecutive_losses":   adap["consecutive_losses"],
        "weak_strategies":      adap["weak_strategies"],
        "conf_adjustments":     adap.get("conf_adjustments", {}),
        "notes":                adap["notes"],
        "insights":             data.get("insights", []),
        "all_time_pnl":         round(sum(s.get("pnl", 0) or 0 for s in real_trades), 2),
        "all_time_wr":          round(
            sum(1 for s in real_trades if s["outcome"] == "WIN") / max(len(real_trades), 1), 3
        ),
    }


def get_pending_signal_id() -> Optional[str]:
    """Returns signal_id of the trade waiting for an outcome report, if any."""
    data    = _load()
    session = _get_session(data)
    return session.get("pending_signal_id")


def print_status() -> None:
    s = get_status()
    paused_txt = f" ⚠  PAUSED: {s['pause_reason']}" if s["paused"] else "  ACTIVE"

    print("\n" + "─" * 60)
    print(f"  BOT MEMORY{paused_txt}")
    print("─" * 60)
    print(f"  Today:       {s['confirmed_today']} real trades   P&L ${s['daily_pnl']:+.2f}")
    print(f"  Next trade:  {s['contracts_next']} contract(s)")
    if s["recent_wr"] is not None:
        print(f"  Real WR:     {s['recent_wr']*100:.1f}%  (last {LOOKBACK} confirmed trades)")
    else:
        print("  Real WR:     n/a (need more real trades)")
    print(f"  Consec loss: {s['consecutive_losses']}")
    print(f"  All-time:    {s['total_real_trades']} trades  ${s['all_time_pnl']:+.2f}")
    if s["weak_strategies"]:
        print(f"  Weak strats: {', '.join(s['weak_strategies'])}")
    if s["conf_adjustments"]:
        active_adj = {k: v for k, v in s["conf_adjustments"].items() if v != 0}
        if active_adj:
            adj_str = "  ".join(f"{k}:{v:+d}" for k, v in active_adj.items())
            print(f"  Score adj:   {adj_str}")
    print(f"  Notes:       {s['notes']}")
    if s["insights"]:
        print("  Learned:")
        for insight in s["insights"][:5]:
            print(f"    {insight}")
    print("─" * 60)


# ── Legacy compatibility (backtest log_trade) ─────────────────────────────────

def log_trade(
    strategy:  str,
    direction: str,
    entry:     float,
    stop:      float,
    target:    float,
    outcome:   str,
    pnl:       float,
    contracts: int,
    vix:       float = 0.0,
    atr:       float = 0.0,
    trend:     str   = "",
    day_name:  str   = "",
) -> None:
    """Legacy: log a backtest/completed trade directly (no user confirmation flow)."""
    data = _load()
    _get_session(data)

    trade = {
        "id":        len(data["trades"]) + 1,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "date":      str(date.today()),
        "day":       day_name,
        "strategy":  strategy,
        "direction": direction,
        "entry":     round(entry, 2),
        "stop":      round(stop, 2),
        "target":    round(target, 2),
        "outcome":   outcome,
        "pnl":       round(pnl, 2),
        "contracts": contracts,
        "vix":       round(vix, 1),
        "atr":       round(atr, 1),
        "trend":     trend,
    }
    data["trades"].append(trade)
    _save(data)
