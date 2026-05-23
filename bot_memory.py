"""
Persistent bot memory — JSON-backed cross-session learning.

Tracks everything the bot has seen and done so the smart filter
uses real observed win rates instead of hardcoded guesses.

File: memory/bot_memory.json  (auto-created on first run)

What gets remembered across restarts:
  - Account state: balance, peak, P&L, trailing floor
  - Streaks: consecutive wins/losses, last result, last trade date
  - Pattern stats: win rate by day, hour, score, london, mss, sweep depth
  - Recent trades: last 50 with full context (for pattern analysis)
  - Daily history: last 60 session summaries
  - Adaptive thresholds: min score per day auto-tuned from real data
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")
MEMORY_DIR  = Path(__file__).parent / "memory"
MEMORY_FILE = MEMORY_DIR / "bot_memory.json"

# Min trades before we trust observed win rate over the hardcoded baseline
MIN_SAMPLE = 8

# Baseline win rates used until MIN_SAMPLE trades are seen for that bucket
BASELINE_DOW = {0: 0.86, 1: 0.20, 2: 0.65, 3: 0.25, 4: 0.67}


def _empty_bucket() -> dict:
    return {"wins": 0, "losses": 0, "total": 0}


def _empty_memory() -> dict:
    from config import STARTING_BALANCE, TRAILING_MAX_DRAWDOWN
    return {
        "account": {
            "starting_balance": STARTING_BALANCE,
            "current_balance":  STARTING_BALANCE,
            "peak_balance":     STARTING_BALANCE,
            "total_pnl":        0.0,
            "trailing_floor":   STARTING_BALANCE - TRAILING_MAX_DRAWDOWN,
            "last_updated":     date.today().isoformat(),
        },
        "streaks": {
            "consecutive_wins":   0,
            "consecutive_losses": 0,
            "last_result":        None,
            "last_trade_date":    None,
        },
        "session_today": {
            "date":            date.today().isoformat(),
            "trades_taken":    0,
            "daily_pnl":       0.0,
            "signals_seen":    0,
            "signals_skipped": 0,
            "london_direction": "neutral",
        },
        "pattern_stats": {
            "by_dow": {str(i): _empty_bucket() for i in range(5)},
            "by_score": {str(s): _empty_bucket() for s in range(4, 8)},
            "by_hour": {str(h): _empty_bucket() for h in range(9, 12)},
            "by_london": {
                "aligned":  _empty_bucket(),
                "opposed":  _empty_bucket(),
                "neutral":  _empty_bucket(),
            },
            "by_mss": {
                "strong": _empty_bucket(),
                "weak":   _empty_bucket(),
            },
            "by_sweep_depth": {
                "shallow": _empty_bucket(),   # 8-15 pts
                "normal":  _empty_bucket(),   # 15-30 pts
                "deep":    _empty_bucket(),   # 30-80 pts
            },
            "by_entry_type": {
                "order_block": _empty_bucket(),
                "fixed":       _empty_bucket(),
            },
            "by_direction": {
                "long":  _empty_bucket(),
                "short": _empty_bucket(),
            },
        },
        "adaptive_thresholds": {
            "dow_min_score": {str(i): None for i in range(5)},
            "last_recalculated": None,
        },
        "recent_trades": [],     # last 50 full trade dicts
        "daily_history": [],     # last 60 session summaries
    }


class BotMemory:
    """
    Load once at startup, update after every trade, auto-save.
    The SmartFilter reads win rates from here instead of hardcoded values.
    """

    def __init__(self, path: Path = MEMORY_FILE):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()
        self._sync_session_date()

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    saved = json.load(f)
                base = _empty_memory()
                # Deep-merge saved over base so new keys appear automatically
                _deep_merge(base, saved)
                return base
            except Exception:
                pass
        return _empty_memory()

    def save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)

    # ── Session date sync ─────────────────────────────────────────────────────

    def _sync_session_date(self) -> None:
        today = date.today().isoformat()
        sess = self._data["session_today"]
        if sess["date"] != today:
            # New day: archive yesterday, reset session counters
            self._archive_session()
            sess["date"]            = today
            sess["trades_taken"]    = 0
            sess["daily_pnl"]       = 0.0
            sess["signals_seen"]    = 0
            sess["signals_skipped"] = 0
            sess["london_direction"] = "neutral"
            self.save()

    def _archive_session(self) -> None:
        sess = self._data["session_today"]
        if sess["trades_taken"] == 0:
            return
        entry = {
            "date":         sess["date"],
            "trades":       sess["trades_taken"],
            "pnl":          sess["daily_pnl"],
            "signals_seen": sess["signals_seen"],
            "london":       sess["london_direction"],
        }
        hist = self._data["daily_history"]
        hist.append(entry)
        if len(hist) > 60:
            self._data["daily_history"] = hist[-60:]

    # ── Account ───────────────────────────────────────────────────────────────

    def update_account(self, current_balance: float, total_pnl: float) -> None:
        from config import TRAILING_MAX_DRAWDOWN
        acct = self._data["account"]
        acct["current_balance"] = round(current_balance, 2)
        acct["total_pnl"]       = round(total_pnl, 2)
        if current_balance > acct["peak_balance"]:
            acct["peak_balance"] = round(current_balance, 2)
        acct["trailing_floor"] = round(acct["peak_balance"] - TRAILING_MAX_DRAWDOWN, 2)
        acct["last_updated"]   = date.today().isoformat()
        self.save()

    @property
    def current_balance(self) -> float:
        return self._data["account"]["current_balance"]

    @property
    def total_pnl(self) -> float:
        return self._data["account"]["total_pnl"]

    @property
    def drawdown_buffer(self) -> float:
        a = self._data["account"]
        return a["current_balance"] - a["trailing_floor"]

    # ── Streaks ───────────────────────────────────────────────────────────────

    @property
    def consecutive_wins(self) -> int:
        return self._data["streaks"]["consecutive_wins"]

    @property
    def consecutive_losses(self) -> int:
        return self._data["streaks"]["consecutive_losses"]

    def _update_streak(self, won: bool) -> None:
        s = self._data["streaks"]
        if won:
            s["consecutive_wins"]   += 1
            s["consecutive_losses"]  = 0
            s["last_result"]         = "WIN"
        else:
            s["consecutive_losses"] += 1
            s["consecutive_wins"]    = 0
            s["last_result"]         = "LOSS"
        s["last_trade_date"] = date.today().isoformat()

    # ── Session ───────────────────────────────────────────────────────────────

    def set_london_direction(self, direction: str) -> None:
        self._data["session_today"]["london_direction"] = direction
        self.save()

    def increment_signal_seen(self) -> None:
        self._data["session_today"]["signals_seen"] += 1

    def increment_signal_skipped(self) -> None:
        self._data["session_today"]["signals_skipped"] += 1

    # ── Trade recording ───────────────────────────────────────────────────────

    def record_trade(self, trade: dict) -> None:
        """
        Call this after every closed trade.
        trade dict keys:
            direction, score, signal_hour, day_of_week, pnl,
            london_aligned (bool), mss_strong (bool),
            sweep_depth (float), entry_type ("order_block" | "fixed")
        """
        won = (trade.get("pnl", 0) or 0) > 0

        # Update streaks
        self._update_streak(won)

        # Update session
        sess = self._data["session_today"]
        sess["trades_taken"] += 1
        sess["daily_pnl"]     = round(sess["daily_pnl"] + (trade.get("pnl", 0) or 0), 2)

        # Update all pattern buckets
        stats = self._data["pattern_stats"]
        _hit(stats["by_dow"],   str(trade.get("day_of_week", -1)), won)
        _hit(stats["by_score"], str(trade.get("score", 0)),        won)
        _hit(stats["by_hour"],  str(trade.get("signal_hour", 9)),  won)

        la = trade.get("london_aligned")
        ld = trade.get("london_direction", "neutral")
        if la is True:
            _hit(stats["by_london"], "aligned", won)
        elif la is False:
            _hit(stats["by_london"], "opposed", won)
        else:
            _hit(stats["by_london"], "neutral", won)

        mss_key = "strong" if trade.get("mss_strong") else "weak"
        _hit(stats["by_mss"], mss_key, won)

        d = trade.get("sweep_depth", 0) or 0
        if d < 15:
            _hit(stats["by_sweep_depth"], "shallow", won)
        elif d < 30:
            _hit(stats["by_sweep_depth"], "normal", won)
        else:
            _hit(stats["by_sweep_depth"], "deep", won)

        et = trade.get("entry_type", "fixed")
        _hit(stats["by_entry_type"], et if et in ("order_block", "fixed") else "fixed", won)

        dir_key = trade.get("direction", "long")
        _hit(stats["by_direction"], dir_key if dir_key in ("long", "short") else "long", won)

        # Store in recent_trades (cap at 50)
        recent = self._data["recent_trades"]
        recent.append({**trade, "date": date.today().isoformat(), "won": won})
        if len(recent) > 50:
            self._data["recent_trades"] = recent[-50:]

        # Recalculate adaptive thresholds
        self._recalculate_thresholds()
        self.save()

    # ── Adaptive thresholds ───────────────────────────────────────────────────

    def _recalculate_thresholds(self) -> None:
        """
        Derive min-score-per-day from real win rates.
        Logic: if observed WR < 40% and sample >= MIN_SAMPLE, raise threshold.
               if observed WR >= 70% and sample >= MIN_SAMPLE, can stay at base.
        """
        stats   = self._data["pattern_stats"]["by_dow"]
        thresh  = self._data["adaptive_thresholds"]["dow_min_score"]

        for dow_str, bucket in stats.items():
            n = bucket["total"]
            if n < MIN_SAMPLE:
                thresh[dow_str] = None   # not enough data yet, use baseline
                continue
            wr = bucket["wins"] / n
            if wr < 0.30:
                thresh[dow_str] = 7      # near 0% win rate: require perfect
            elif wr < 0.45:
                thresh[dow_str] = 5      # below average: require extra conf
            elif wr < 0.60:
                thresh[dow_str] = 4      # average: base threshold
            else:
                thresh[dow_str] = 4      # above average: base threshold

        self._data["adaptive_thresholds"]["last_recalculated"] = datetime.now(tz=EST).isoformat()

    def min_score_for_dow(self, dow: int) -> int:
        """
        Returns the data-driven min score for this day of week.
        Falls back to baseline (hardcoded) if not enough samples.
        """
        thresh  = self._data["adaptive_thresholds"]["dow_min_score"]
        learned = thresh.get(str(dow))
        if learned is not None:
            return learned

        # Not enough data yet: use baseline
        baseline_wr = BASELINE_DOW.get(dow, 0.60)
        if baseline_wr < 0.30:
            return 7
        if baseline_wr < 0.45:
            return 5
        return 4

    # ── Win rate helpers ──────────────────────────────────────────────────────

    def win_rate(self, category: str, key: str) -> float | None:
        """
        Returns observed win rate for a bucket or None if < MIN_SAMPLE trades.
        category: "by_dow" | "by_score" | "by_hour" | "by_london" | "by_mss" | etc.
        key: the bucket key as a string.
        """
        bucket = self._data["pattern_stats"].get(category, {}).get(str(key))
        if not bucket or bucket["total"] < MIN_SAMPLE:
            return None
        return round(bucket["wins"] / bucket["total"], 3)

    def total_trades(self) -> int:
        recent = self._data["recent_trades"]
        return len(recent)

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        a    = self._data["account"]
        s    = self._data["streaks"]
        sess = self._data["session_today"]
        from config import TRAILING_MAX_DRAWDOWN, PROFIT_TARGET
        return {
            "current_balance":    a["current_balance"],
            "peak_balance":       a["peak_balance"],
            "total_pnl":          a["total_pnl"],
            "trailing_floor":     a["trailing_floor"],
            "drawdown_buffer":    self.drawdown_buffer,
            "consecutive_wins":   s["consecutive_wins"],
            "consecutive_losses": s["consecutive_losses"],
            "last_result":        s["last_result"],
            "daily_pnl":          sess["daily_pnl"],
            "trades_today":       sess["trades_taken"],
            "total_trades_seen":  self.total_trades(),
            "progress_pct":       round(max(0, a["total_pnl"]) / PROFIT_TARGET * 100, 1) if PROFIT_TARGET else 0,
            "london_today":       sess["london_direction"],
        }

    def print_pattern_report(self) -> None:
        """Print a formatted win-rate breakdown to the terminal."""
        from rich.console import Console
        from rich.table import Table
        from rich import box
        console = Console()
        stats = self._data["pattern_stats"]
        DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

        console.rule("[bold cyan]Bot Memory: Pattern Stats[/bold cyan]")

        t = Table(box=box.SIMPLE_HEAD, title="Win Rate by Day")
        t.add_column("Day"); t.add_column("W"); t.add_column("L"); t.add_column("WR"); t.add_column("Threshold")
        for i in range(5):
            b = stats["by_dow"].get(str(i), _empty_bucket())
            wr = f"{b['wins']/b['total']*100:.0f}%" if b["total"] >= MIN_SAMPLE else "n/a"
            thr = str(self.min_score_for_dow(i)) + "/7"
            t.add_row(DAYS[i], str(b["wins"]), str(b["losses"]), wr, thr)
        console.print(t)

        t2 = Table(box=box.SIMPLE_HEAD, title="Win Rate by Score")
        t2.add_column("Score"); t2.add_column("W"); t2.add_column("L"); t2.add_column("WR")
        for s in range(4, 8):
            b = stats["by_score"].get(str(s), _empty_bucket())
            wr = f"{b['wins']/b['total']*100:.0f}%" if b["total"] >= MIN_SAMPLE else "n/a"
            t2.add_row(f"{s}/7", str(b["wins"]), str(b["losses"]), wr)
        console.print(t2)

        t3 = Table(box=box.SIMPLE_HEAD, title="London Alignment")
        t3.add_column("Alignment"); t3.add_column("W"); t3.add_column("L"); t3.add_column("WR")
        for k in ("aligned", "opposed", "neutral"):
            b = stats["by_london"].get(k, _empty_bucket())
            wr = f"{b['wins']/b['total']*100:.0f}%" if b["total"] >= MIN_SAMPLE else "n/a"
            t3.add_row(k, str(b["wins"]), str(b["losses"]), wr)
        console.print(t3)

        t4 = Table(box=box.SIMPLE_HEAD, title="MSS Strength")
        t4.add_column("MSS"); t4.add_column("W"); t4.add_column("L"); t4.add_column("WR")
        for k in ("strong", "weak"):
            b = stats["by_mss"].get(k, _empty_bucket())
            wr = f"{b['wins']/b['total']*100:.0f}%" if b["total"] >= MIN_SAMPLE else "n/a"
            t4.add_row(k, str(b["wins"]), str(b["losses"]), wr)
        console.print(t4)

        t5 = Table(box=box.SIMPLE_HEAD, title="Entry Type")
        t5.add_column("Entry"); t5.add_column("W"); t5.add_column("L"); t5.add_column("WR")
        for k in ("order_block", "fixed"):
            b = stats["by_entry_type"].get(k, _empty_bucket())
            wr = f"{b['wins']/b['total']*100:.0f}%" if b["total"] >= MIN_SAMPLE else "n/a"
            t5.add_row(k, str(b["wins"]), str(b["losses"]), wr)
        console.print(t5)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hit(stats_dict: dict, key: str, won: bool) -> None:
    if key not in stats_dict:
        stats_dict[key] = _empty_bucket()
    stats_dict[key]["total"] += 1
    if won:
        stats_dict[key]["wins"] += 1
    else:
        stats_dict[key]["losses"] += 1


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base in-place."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
