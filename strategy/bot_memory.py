"""
Bot Memory — adaptive sizing and self-improvement via JSON trade log.

The bot reads its own history and adjusts:
  - Contracts (1 or 2) based on recent win rate
  - Strategy confidence (flags underperformers)
  - Daily pause after 3 consecutive losses or $150 daily loss

File: journal/bot_memory.json
"""
from __future__ import annotations
import json
import os
from datetime import date, datetime
from typing import Optional

MEMORY_PATH = os.path.join(os.path.dirname(__file__), "..", "journal", "bot_memory.json")

# Adaptive thresholds
WR_SIZE_UP   = 0.75   # recent WR >= 75% → 2 contracts
WR_SIZE_DOWN = 0.55   # recent WR <  55% → flag strategy as weak
LOOKBACK     = 20     # trades to look back for WR calculation
MAX_CONSEC_L = 3      # consecutive losses before pausing the day
DAILY_LIMIT  = 150.0  # daily loss limit in dollars


# ── Load / Save ──────────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return {"trades": [], "session": _blank_session(), "adaptive": _blank_adaptive()}
    with open(MEMORY_PATH, "r") as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    with open(MEMORY_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _blank_session() -> dict:
    return {
        "date": str(date.today()),
        "trades_today": 0,
        "daily_pnl": 0.0,
        "paused": False,
        "pause_reason": "",
    }


def _blank_adaptive() -> dict:
    return {
        "contracts": 1,
        "last_update": str(date.today()),
        "recent_wr": None,
        "consecutive_losses": 0,
        "weak_strategies": [],
        "notes": "Starting fresh — no history yet.",
    }


# ── Session management ────────────────────────────────────────────────────────

def _get_session(data: dict) -> dict:
    """Reset session if it's a new day."""
    if data["session"]["date"] != str(date.today()):
        data["session"] = _blank_session()
    return data["session"]


# ── Log a trade ───────────────────────────────────────────────────────────────

def log_trade(
    strategy:  str,
    direction: str,
    entry:     float,
    stop:      float,
    target:    float,
    outcome:   str,        # "WIN" or "LOSS"
    pnl:       float,
    contracts: int,
    vix:       float = 0.0,
    atr:       float = 0.0,
    trend:     str   = "",
    day_name:  str   = "",
) -> None:
    """Log one completed trade and update adaptive state."""
    data = _load()
    session = _get_session(data)

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

    session["trades_today"] += 1
    session["daily_pnl"]    = round(session["daily_pnl"] + pnl, 2)

    _update_adaptive(data)
    _save(data)


# ── Adaptive logic ────────────────────────────────────────────────────────────

def _update_adaptive(data: dict) -> None:
    """Recalculate contract sizing and strategy flags from recent history."""
    trades  = data["trades"]
    session = data["session"]
    adap    = data["adaptive"]

    recent = trades[-LOOKBACK:] if len(trades) >= LOOKBACK else trades
    if not recent:
        return

    wins       = [t for t in recent if t["outcome"] == "WIN"]
    recent_wr  = len(wins) / len(recent)
    adap["recent_wr"] = round(recent_wr, 3)

    # Count consecutive losses from the END of history
    consec = 0
    for t in reversed(trades):
        if t["outcome"] == "LOSS":
            consec += 1
        else:
            break
    adap["consecutive_losses"] = consec

    # Contract sizing
    if recent_wr >= WR_SIZE_UP and consec == 0:
        adap["contracts"] = 2
        adap["notes"] = f"Hot streak: {recent_wr*100:.0f}% WR on last {len(recent)} trades → 2 contracts"
    else:
        adap["contracts"] = 1
        if consec >= MAX_CONSEC_L:
            adap["notes"] = f"{consec} consecutive losses → back to 1 contract, consider pausing"
        else:
            adap["notes"] = f"WR {recent_wr*100:.0f}% on last {len(recent)} trades → 1 contract"

    # Pause session?
    if consec >= MAX_CONSEC_L:
        session["paused"]       = True
        session["pause_reason"] = f"{consec} consecutive losses"
    if session["daily_pnl"] <= -DAILY_LIMIT:
        session["paused"]       = True
        session["pause_reason"] = f"Daily loss limit hit (${abs(session['daily_pnl']):.0f})"

    # Flag weak strategies (< WR_SIZE_DOWN in recent history)
    from collections import defaultdict
    strat_trades: dict = defaultdict(list)
    for t in recent:
        strat_trades[t["strategy"]].append(t)

    weak = []
    for s, ts in strat_trades.items():
        if len(ts) >= 5:
            wr = sum(1 for t in ts if t["outcome"] == "WIN") / len(ts)
            if wr < WR_SIZE_DOWN:
                weak.append(f"{s} ({wr*100:.0f}% on {len(ts)} trades)")
    adap["weak_strategies"] = weak
    adap["last_update"]     = str(date.today())


# ── Query functions ───────────────────────────────────────────────────────────

def get_sizing() -> int:
    """Return current contract count (1 or 2) based on recent performance."""
    data = _load()
    _get_session(data)  # ensure session is for today
    return data["adaptive"]["contracts"]


def is_paused() -> tuple[bool, str]:
    """Return (paused, reason). Check before taking any trade."""
    data    = _load()
    session = _get_session(data)
    return session["paused"], session.get("pause_reason", "")


def get_status() -> dict:
    """Full status snapshot for display."""
    data    = _load()
    session = _get_session(data)
    adap    = data["adaptive"]
    trades  = data["trades"]

    today_trades = [t for t in trades if t["date"] == str(date.today())]

    return {
        "total_trades":         len(trades),
        "trades_today":         len(today_trades),
        "daily_pnl":            session["daily_pnl"],
        "paused":               session["paused"],
        "pause_reason":         session.get("pause_reason", ""),
        "contracts_next":       adap["contracts"],
        "recent_wr":            adap["recent_wr"],
        "consecutive_losses":   adap["consecutive_losses"],
        "weak_strategies":      adap["weak_strategies"],
        "notes":                adap["notes"],
        "all_time_pnl":         round(sum(t["pnl"] for t in trades), 2),
        "all_time_wr":          round(
            sum(1 for t in trades if t["outcome"] == "WIN") / max(len(trades), 1), 3
        ),
    }


def print_status() -> None:
    """Print a readable memory status report."""
    s = get_status()
    paused_txt = f" ⚠  PAUSED: {s['pause_reason']}" if s["paused"] else "  ACTIVE"

    print("\n" + "─" * 60)
    print(f"  BOT MEMORY STATUS{paused_txt}")
    print("─" * 60)
    print(f"  Today:          {s['trades_today']} trades   P&L ${s['daily_pnl']:+.2f}")
    print(f"  Next trade:     {s['contracts_next']} contract(s)")
    print(f"  Recent WR:      {s['recent_wr']*100:.1f}%  (last {LOOKBACK} trades)"
          if s["recent_wr"] is not None else "  Recent WR:      n/a (not enough history)")
    print(f"  Consec losses:  {s['consecutive_losses']}")
    print(f"  All-time:       {s['total_trades']} trades  {s['all_time_wr']*100:.1f}% WR  ${s['all_time_pnl']:+.2f}")
    if s["weak_strategies"]:
        print(f"  Weak strats:    {', '.join(s['weak_strategies'])}")
    print(f"  Notes:          {s['notes']}")
    print("─" * 60)
