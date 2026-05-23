"""
Live Signal Detector — real-time via Tradovate feed, falls back to yfinance.

Run at 9:00 AM EST: python3 live_detector.py
"""
import asyncio
import threading
import time
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from fast_feed import get_feed, get_price as _get_rt_price
from briefing import print_morning_briefing, print_session_summary
from news_check import print_news_warning
from strategy.asia_range import build_asia_ranges
from strategy.mss_detector import detect_mss
from strategy.fvg_detector import find_fvgs, get_active_fvg
from strategy.vwap import compute_vwap
from strategy.confluence_scorer import score_setup
from strategy.smart_filter import SmartFilter
from risk.position_sizer import calculate_size, calculate_targets
from risk.prop_firm_rules import TradeifyState
from notifications import alert_sweep, alert_signal
from config import (
    MAX_TRADES_PER_DAY, MAX_DAILY_LOSS, MAX_STOP_POINTS,
    MIN_CONFLUENCE_SCORE, MNQ_DOLLARS_PER_POINT,
)

smart = SmartFilter()

EST = ZoneInfo("America/New_York")
console = Console()

# ── Account state — update already_lost each morning ─────────────────────────
state = TradeifyState()
state.setup(already_lost=330.20)  # balance $24,669.80 — updated 2026-05-21


class LiveDetector:
    def __init__(self):
        self.df: pd.DataFrame = pd.DataFrame()
        self.asia_ranges: dict = {}
        self.vwap_series: pd.Series = pd.Series(dtype=float)

        # Daily state (resets each morning)
        self.today = date.today()
        self.last_rt_price: float | None = None
        self.last_rt_time: datetime | None = None
        self.prev_day: dict = {}
        self.today_signals: list = []    # track taken/skipped signals
        self.today_missed: list = []     # track missed trade outcomes
        self.bull_sweep = False
        self.bear_sweep = False
        self.bull_sweep_idx: int | None = None
        self.bear_sweep_idx: int | None = None
        self.bull_mss = False
        self.bear_mss = False
        self.signal_fired = {"long": False, "short": False}
        self.last_bar_time = None

    def fetch(self) -> bool:
        """Load bars for Asia range + VWAP context. Runs once on startup then every 5 min."""
        try:
            raw = yf.Ticker("NQ=F").history(period="3d", interval="1m", auto_adjust=True)
            if raw.empty:
                return False
            if raw.index.tz is None:
                raw.index = raw.index.tz_localize("UTC")
            else:
                raw.index = raw.index.tz_convert("UTC")
            raw = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
            if len(raw) == 0:
                return False
            self.df = raw
            self.asia_ranges = build_asia_ranges(self.df)
            self.vwap_series = compute_vwap(self.df)
            return True
        except Exception as e:
            console.print(f"[yellow]Bar fetch error: {e}[/yellow]")
            return False

    def get_live_price(self) -> float | None:
        """Read latest cached price — instant, never blocks."""
        return _get_rt_price()

    def _reset_day(self):
        self.bull_sweep = False
        self.bear_sweep = False
        self.bull_sweep_idx = None
        self.bear_sweep_idx = None
        self.bull_mss = False
        self.bear_mss = False
        self.signal_fired = {"long": False, "short": False}
        state.daily_pnl = 0.0
        state.trades_today = 0
        smart.reset_day()

    def check(self) -> dict | None:
        """Run strategy on latest bar. Returns signal dict or None."""
        if self.df.empty:
            return None

        now_est = datetime.now(tz=EST)
        today = now_est.date()

        # New day reset
        if today != self.today:
            self.today = today
            self._reset_day()

        # Time window check
        hour, minute = now_est.hour, now_est.minute
        mins = hour * 60 + minute
        in_window = (9 * 60 + 30) <= mins < (11 * 60 + 30)
        if not in_window:
            return None

        # Max trades / daily loss guard
        if state.trades_today >= 2:  # 2 trades per day max, 1 contract each
            return None
        if state.daily_pnl <= -MAX_DAILY_LOSS:
            return None

        # Get Asia range
        ar = self.asia_ranges.get(today)
        if ar is None:
            return None
        asia_high = ar["high"]
        asia_low  = ar["low"]

        # Get last two bars (current bar = -1, previous = -2)
        closes = self.df["Close"]
        highs  = self.df["High"]
        lows   = self.df["Low"]
        n = len(self.df)

        price = float(closes.iloc[-1])
        high  = float(highs.iloc[-1])
        low   = float(lows.iloc[-1])
        vwap  = float(self.vwap_series.iloc[-1]) if n > 0 else None

        # ── Detect sweeps ──────────────────────────────────────────────────────
        if not self.bull_sweep and low < asia_low:
            self.bull_sweep = True
            self.bull_sweep_idx = n - 1
            console.print()
            console.print(Panel(
                f"[bold yellow]⚠  SWEEP LOW — GET READY[/bold yellow]\n\n"
                f"  Price swept below Asia Low {asia_low:.2f} → hit {low:.2f}\n"
                f"  Waiting for MSS confirmation...\n\n"
                f"  [dim]Have TradingView open. Signal coming shortly.[/dim]",
                border_style="yellow", box=box.HEAVY, padding=(1, 2)
            ))
            console.print()

        if not self.bear_sweep and high > asia_high:
            self.bear_sweep = True
            self.bear_sweep_idx = n - 1
            console.print()
            console.print(Panel(
                f"[bold yellow]⚠  SWEEP HIGH — GET READY[/bold yellow]\n\n"
                f"  Price swept above Asia High {asia_high:.2f} → hit {high:.2f}\n"
                f"  Waiting for MSS confirmation...\n\n"
                f"  [dim]Have TradingView open. Signal coming shortly.[/dim]",
                border_style="yellow", box=box.HEAVY, padding=(1, 2)
            ))
            console.print()

        # ── Detect MSS ────────────────────────────────────────────────────────
        for direction, swept, sweep_idx, mss_done, signal_dir in [
            ("bullish", self.bull_sweep, self.bull_sweep_idx, self.bull_mss, "long"),
            ("bearish", self.bear_sweep, self.bear_sweep_idx, self.bear_mss, "short"),
        ]:
            if not swept or mss_done or sweep_idx is None:
                continue
            if n - 1 <= sweep_idx:
                continue

            mss = detect_mss(self.df, sweep_idx, direction, lookback=30, pivot_strength=2)
            if not mss["detected"]:
                continue

            if direction == "bullish":
                self.bull_mss = True
            else:
                self.bear_mss = True

            _print_event(f"MSS {'▲' if direction == 'bullish' else '▼'} confirmed at {price:.2f}", "cyan")

            # Already fired a signal this direction today? Skip
            if self.signal_fired[signal_dir]:
                continue

            # ── Score ──────────────────────────────────────────────────────────
            fvgs = find_fvgs(self.df, signal_dir, sweep_idx, n - 1, min_size_points=2.0)
            fvg_active = get_active_fvg(fvgs, price, signal_dir) is not None

            confluence = score_setup(
                asia_sweep=True,
                mss_confirmed=True,
                fvg_active=fvg_active,
                price=price,
                vwap=vwap,
                direction=signal_dir,
                bar_hour=hour,
                bar_minute=minute,
            )

            min_score = smart.min_score_required(hour, minute, datetime.now(tz=EST).weekday())
            if confluence.score < min_score:
                _print_event(
                    f"Score {confluence.score}/5 — need {min_score}/5 "
                    f"({'loss streak' if smart.consecutive_losses >= 2 else 'late session' if minute >= 11*60 else 'waiting'})",
                    "dim"
                )
                continue

            # ── Position sizing ────────────────────────────────────────────────
            if signal_dir == "long":
                stop_level = round(float(lows.iloc[sweep_idx:n].min()) - 1.0, 2)
                limit_entry = round(stop_level + MAX_STOP_POINTS, 2)
            else:
                stop_level = round(float(highs.iloc[sweep_idx:n].max()) + 1.0, 2)
                limit_entry = round(stop_level - MAX_STOP_POINTS, 2)

            size = calculate_size(limit_entry, stop_level)
            if not size["valid"]:
                _print_event(f"Stop too wide: {size['reason']}", "yellow")
                continue

            targets = calculate_targets(limit_entry, stop_level, signal_dir)

            # Fire sound + popup notification
            alert_signal(signal_dir, limit_entry, stop_level, targets["tp2"], confluence.score)

            self.signal_fired[signal_dir] = True
            state.trades_today += 1

            return {
                "direction":   signal_dir,
                "entry":       limit_entry,
                "stop":        stop_level,
                "tp1":         targets["tp1"],
                "tp2":         targets["tp2"],
                "contracts":   size["contracts"],
                "risk":        size["risk_dollars"],
                "stop_points": size["stop_points"],
                "score":       confluence.score,
                "reason":      confluence.reason,
                "asia_high":   asia_high,
                "asia_low":    asia_low,
                "vwap":        vwap,
                "price":       price,
            }

        return None

    def check_price(self, price: float, ts: datetime) -> dict | None:
        """Real-time tick check — called on every Tradovate price update."""
        now_est = ts.astimezone(EST)
        hour, minute = now_est.hour, now_est.minute
        mins = hour * 60 + minute
        if not ((9 * 60 + 30) <= mins < (11 * 60 + 30)):
            return None
        if state.trades_today >= 2 or state.daily_pnl <= -MAX_DAILY_LOSS:
            return None

        today = now_est.date()
        if today != self.today:
            self.today = today
            self._reset_day()

        ar = self.asia_ranges.get(today)
        if not ar:
            return None

        asia_high = ar["high"]
        asia_low  = ar["low"]

        # Sweep detection on live tick
        smart.update_price(price)

        if not self.bull_sweep and price < asia_low:
            valid, reason = smart.is_sweep_valid(price, asia_low, "bull")
            if valid:
                self.bull_sweep = True
                self.bull_sweep_idx = len(self.df) - 1 if not self.df.empty else 0
                console.print()
                console.print(Panel(
                    f"[bold yellow]⚠  SWEEP LOW — GET READY[/bold yellow]\n\n"
                    f"  Price swept below Asia Low {asia_low:.2f} → now at {price:.2f}\n"
                    f"  Sweep quality: {reason}\n"
                    f"  Waiting for MSS confirmation...\n\n"
                    f"  [dim]Have TradingView open. Signal coming shortly.[/dim]",
                    border_style="yellow", box=box.HEAVY, padding=(1, 2)
                ))
                alert_sweep("bull", price, asia_low)
            else:
                _print_event(f"Sweep LOW ignored: {reason}", "dim")

        if not self.bear_sweep and price > asia_high:
            valid, reason = smart.is_sweep_valid(price, asia_high, "bear")
            if valid:
                self.bear_sweep = True
                self.bear_sweep_idx = len(self.df) - 1 if not self.df.empty else 0
                console.print()
                console.print(Panel(
                    f"[bold yellow]⚠  SWEEP HIGH — GET READY[/bold yellow]\n\n"
                    f"  Price swept above Asia High {asia_high:.2f} → now at {price:.2f}\n"
                    f"  Sweep quality: {reason}\n"
                    f"  Waiting for MSS confirmation...\n\n"
                    f"  [dim]Have TradingView open. Signal coming shortly.[/dim]",
                    border_style="yellow", box=box.HEAVY, padding=(1, 2)
                ))
                alert_sweep("bear", price, asia_high)
            else:
                _print_event(f"Sweep HIGH ignored: {reason}", "dim")

        # Delegate full signal check to bar-based logic
        return self.check()

    def ingest_bar(self, bar: dict):
        """Add a completed 1-minute bar from Tradovate feed into df."""
        new_row = pd.DataFrame([{
            "Open":   bar["open"],  "High": bar["high"],
            "Low":    bar["low"],   "Close": bar["close"],
            "Volume": bar["volume"],
        }], index=pd.DatetimeIndex([bar["time"]]))
        self.df = pd.concat([self.df, new_row]).iloc[-500:]  # keep last 500 bars
        # Rebuild Asia ranges and VWAP with new data
        self.asia_ranges  = build_asia_ranges(self.df)
        self.vwap_series  = compute_vwap(self.df)


def _print_event(msg: str, color: str = "white"):
    now = datetime.now(tz=EST).strftime("%H:%M:%S")
    console.print(f"[dim]{now}[/dim]  [{color}]{msg}[/{color}]")


def _print_signal(sig: dict):
    direction = sig["direction"].upper()
    color = "green" if direction == "LONG" else "red"
    arrow = "▲" if direction == "LONG" else "▼"
    now = datetime.now(tz=EST).strftime("%H:%M:%S EST")

    console.print()
    console.print(Panel(
        f"[bold {color}]{arrow}  {direction} MNQ — PLACE THIS TRADE NOW  {arrow}[/bold {color}]\n\n"
        f"  Step 1 — Click [bold]{'BUY' if direction == 'LONG' else 'SELL'}[/bold] on TradingView\n"
        f"  Step 2 — Set order type to [bold]LIMIT[/bold]\n"
        f"  Step 3 — Enter these exact numbers:\n\n"
        f"  {'🟢' if direction == 'LONG' else '🔴'} Entry (Limit price):  [bold white]{sig['entry']:.2f}[/bold white]\n"
        f"  🔴 Stop Loss:          [bold red]{sig['stop']:.2f}[/bold red]   → max loss ${sig['risk']:.0f}\n"
        f"  🟡 Take Profit 1:      [bold yellow]{sig['tp1']:.2f}[/bold yellow]   → when hit, move stop to {sig['entry']:.2f}\n"
        f"  🟢 Take Profit 2:      [bold green]{sig['tp2']:.2f}[/bold green]   → close trade, pocket ${sig['stop_points'] * 3 * 2:.0f}\n\n"
        f"  Size: [bold]1 MNQ contract[/bold]   |   Score: {sig['score']}/5",
        title=f"[bold white] TJR SIGNAL — {now} [/bold white]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print()


def _input_timeout(prompt: str, timeout: int = 60) -> str | None:
    """Ask for input without blocking the program. Returns None on timeout."""
    result = [None]
    def ask():
        try:
            result[0] = input(prompt)
        except Exception:
            pass
    t = threading.Thread(target=ask, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


def _wait_for_input(prompt: str) -> str:
    """Wait indefinitely for user input — no timeout."""
    while True:
        try:
            val = input(prompt).strip()
            if val:
                return val
        except Exception:
            time.sleep(1)


class TradeMonitor:
    """
    Runs in the background while a trade is open.
    Watches price every second and alerts on TP1 / TP2 / stop hit.
    """
    def __init__(self, sig: dict, get_price_fn):
        self.sig          = sig
        self.get_price    = get_price_fn
        self.tp1_hit      = False
        self.running      = True
        self.suggestion   = None   # "win" / "loss" / "be" when detected

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def _run(self):
        d    = self.sig["direction"]
        entry = self.sig["entry"]
        stop  = self.sig["stop"]
        tp1   = self.sig["tp1"]
        tp2   = self.sig["tp2"]

        while self.running:
            price = self.get_price()
            if price is None:
                time.sleep(2)
                continue

            if d == "long":
                if not self.tp1_hit and price >= tp1:
                    self.tp1_hit = True
                    from notifications import _sound, _popup
                    _sound("Ping")
                    _popup("🟡 TP1 HIT", f"Move stop to {entry:.2f} (break-even) NOW", "Ping")
                    console.print()
                    console.print(Panel(
                        f"[bold yellow]🟡  TP1 HIT — {price:.2f}[/bold yellow]\n\n"
                        f"  Move your stop loss to [bold]{entry:.2f}[/bold] RIGHT NOW\n"
                        f"  You are now risk-free. Let it run to TP2 [bold green]{tp2:.2f}[/bold green]",
                        border_style="yellow", padding=(1, 2)
                    ))
                if price >= tp2 and self.tp1_hit:
                    from notifications import _sound, _popup
                    _sound("Hero"); _sound("Hero")
                    _popup("🟢 TP2 HIT — WIN!", f"+$150 — Close your trade now!", "Hero")
                    console.print(Panel(
                        f"[bold green]🟢  TP2 HIT — CLOSE YOUR TRADE![/bold green]\n\n"
                        f"  Price: {price:.2f}  |  TP2 was: {tp2:.2f}\n"
                        f"  Go to TradingView and close the position.\n"
                        f"  Then type [bold]win[/bold] below.",
                        border_style="green", padding=(1, 2)
                    ))
                    self.suggestion = "win"
                    self.running = False
                    return
                if price <= stop:
                    from notifications import _sound, _popup
                    _sound("Basso"); _sound("Basso")
                    outcome = "be" if self.tp1_hit else "loss"
                    label   = "BREAK EVEN" if self.tp1_hit else "STOPPED OUT"
                    _popup(f"🔴 {label}", f"Stop hit at {price:.2f}", "Basso")
                    console.print(Panel(
                        f"[bold red]🔴  {label} — {price:.2f}[/bold red]\n\n"
                        f"  Stop was: {stop:.2f}"
                        + (f"\n  P&L: $0 (break-even)" if self.tp1_hit else f"\n  P&L: -${self.sig['risk']:.0f}"),
                        border_style="red", padding=(1, 2)
                    ))
                    self.suggestion = outcome
                    self.running = False
                    return

            else:  # short
                if not self.tp1_hit and price <= tp1:
                    self.tp1_hit = True
                    from notifications import _sound, _popup
                    _sound("Ping")
                    _popup("🟡 TP1 HIT", f"Move stop to {entry:.2f} (break-even) NOW", "Ping")
                    console.print()
                    console.print(Panel(
                        f"[bold yellow]🟡  TP1 HIT — {price:.2f}[/bold yellow]\n\n"
                        f"  Move your stop loss to [bold]{entry:.2f}[/bold] RIGHT NOW\n"
                        f"  You are now risk-free. Let it run to TP2 [bold green]{tp2:.2f}[/bold green]",
                        border_style="yellow", padding=(1, 2)
                    ))
                if price <= tp2 and self.tp1_hit:
                    from notifications import _sound, _popup
                    _sound("Hero"); _sound("Hero")
                    _popup("🟢 TP2 HIT — WIN!", f"+$150 — Close your trade now!", "Hero")
                    console.print(Panel(
                        f"[bold green]🟢  TP2 HIT — CLOSE YOUR TRADE![/bold green]\n\n"
                        f"  Price: {price:.2f}  |  TP2 was: {tp2:.2f}\n"
                        f"  Go to TradingView and close the position.\n"
                        f"  Then type [bold]win[/bold] below.",
                        border_style="green", padding=(1, 2)
                    ))
                    self.suggestion = "win"
                    self.running = False
                    return
                if price >= stop:
                    from notifications import _sound, _popup
                    _sound("Basso"); _sound("Basso")
                    outcome = "be" if self.tp1_hit else "loss"
                    label   = "BREAK EVEN" if self.tp1_hit else "STOPPED OUT"
                    _popup(f"🔴 {label}", f"Stop hit at {price:.2f}", "Basso")
                    console.print(Panel(
                        f"[bold red]🔴  {label} — {price:.2f}[/bold red]\n\n"
                        f"  Stop was: {stop:.2f}"
                        + (f"\n  P&L: $0 (break-even)" if self.tp1_hit else f"\n  P&L: -${self.sig['risk']:.0f}"),
                        border_style="red", padding=(1, 2)
                    ))
                    self.suggestion = outcome
                    self.running = False
                    return

            time.sleep(1)


def _log_trade_base(sig: dict, status: str) -> int:
    from journal.trade_journal import TradeJournal
    return TradeJournal().log_trade({
        "timestamp":          datetime.now(tz=EST).isoformat(),
        "direction":          sig["direction"],
        "entry_price":        sig["entry"],
        "stop_price":         sig["stop"],
        "tp1_price":          sig["tp1"],
        "tp2_price":          sig["tp2"],
        "contracts":          sig["contracts"],
        "risk_dollars":       sig["risk"],
        "score":              sig["score"],
        "score_reason":       sig["reason"],
        "status":             status,
        "drawdown_remaining": state.drawdown_buffer,
        "daily_pnl":          state.daily_pnl,
        "total_pnl":          state.total_realized_pnl,
    })


def _ask_trade(sig: dict):
    """After signal fires: ask if taken, monitor live, wait for result, update balance."""
    from journal.trade_journal import TradeJournal
    journal = TradeJournal()

    console.print()
    console.print("[bold cyan]→ Did you take this trade?[/bold cyan] [dim](y/n — auto-skips in 60s)[/dim]")
    took = _input_timeout("  Your answer: ", timeout=60)

    if took is None or took.strip().lower() not in ("y", "yes"):
        console.print("[dim]Skipped — logged. Tracking what would have happened...[/dim]\n")
        _log_trade_base(sig, "SKIPPED")
        # Track missed trade outcome in background
        _track_missed(sig)
        return

    # ── Took the trade ────────────────────────────────────────────────────────
    trade_id = _log_trade_base(sig, "OPEN")
    console.print("[green]✓ Trade is OPEN — bot is now watching price for you[/green]")
    console.print(f"  [dim]TP1: {sig['tp1']:.2f}  |  TP2: {sig['tp2']:.2f}  |  Stop: {sig['stop']:.2f}[/dim]\n")

    # Start price monitor in background
    monitor = TradeMonitor(sig, _get_rt_price)
    monitor.start()

    # Wait for result
    pnl_map = {"win": 150.0, "w": 150.0, "be": 0.0, "loss": -50.0, "l": -50.0}

    console.print("[dim]Bot is watching TP1/TP2/stop for you. When trade closes:[/dim]")
    console.print("[dim]  win / be / loss   OR   exact amount like +150 or -50[/dim]")

    while True:
        # If monitor already detected the outcome, suggest it
        hint = f" (detected: {monitor.suggestion})" if monitor.suggestion else ""
        result_raw = _wait_for_input(f"  Result{hint}: ")
        r = result_raw.strip().lower()

        # Accept empty = use monitor suggestion
        if r == "" and monitor.suggestion:
            r = monitor.suggestion

        if r in pnl_map:
            pnl = pnl_map[r]
            break
        try:
            pnl = float(r)
            break
        except ValueError:
            console.print("[yellow]  Type: win / be / loss / or a number like +150 or -50[/yellow]")

    monitor.stop()

    outcome = "WIN" if pnl > 0 else ("BE" if pnl == 0 else "LOSS")
    state.record_trade(pnl)
    smart.record_result(pnl > 0)

    journal.update_trade(trade_id, {
        "pnl_dollars":        pnl,
        "outcome":            outcome,
        "status":             "CLOSED",
        "daily_pnl":          state.daily_pnl,
        "total_pnl":          state.total_realized_pnl,
        "drawdown_remaining": state.drawdown_buffer,
    })

    color = "green" if pnl > 0 else ("yellow" if pnl == 0 else "red")
    console.print()
    console.print(Panel(
        f"[{color}]Trade closed: {outcome}   PnL = {'+'if pnl>=0 else ''}{pnl:.0f}[/{color}]\n\n"
        f"  Buffer:     ${state.drawdown_buffer:.0f} remaining\n"
        f"  Total PnL:  ${state.total_realized_pnl:+.2f}\n"
        f"  Progress:   {state.progress_pct:.1f}% toward $1,500 target",
        border_style=color, padding=(1, 2)
    ))
    console.print()


def _track_missed(sig: dict):
    """Background thread — watches if a skipped trade would have won or lost."""
    def _run():
        d     = sig["direction"]
        entry = sig["entry"]
        stop  = sig["stop"]
        tp2   = sig["tp2"]
        tp1   = sig["tp1"]
        tp1_hit = False

        for _ in range(300):   # watch for up to 5 minutes
            price = _get_rt_price()
            if price is None:
                time.sleep(1)
                continue

            if d == "long":
                if not tp1_hit and price >= tp1:
                    tp1_hit = True
                if price >= tp2:
                    pnl = 150.0
                    _announce_missed("WIN", pnl, sig)
                    return
                if price <= stop:
                    pnl = 0.0 if tp1_hit else -sig["risk"]
                    _announce_missed("BE" if tp1_hit else "LOSS", pnl, sig)
                    return
            else:
                if not tp1_hit and price <= tp1:
                    tp1_hit = True
                if price <= tp2:
                    pnl = 150.0
                    _announce_missed("WIN", pnl, sig)
                    return
                if price >= stop:
                    pnl = 0.0 if tp1_hit else -sig["risk"]
                    _announce_missed("BE" if tp1_hit else "LOSS", pnl, sig)
                    return
            time.sleep(1)

    threading.Thread(target=_run, daemon=True).start()


def _announce_missed(outcome: str, pnl: float, sig: dict):
    color = "green" if pnl > 0 else ("yellow" if pnl == 0 else "red")
    icon  = "🟢" if pnl > 0 else ("🟡" if pnl == 0 else "🔴")
    console.print()
    console.print(Panel(
        f"[{color}]{icon}  MISSED TRADE RESULT: {outcome}  ({pnl:+.0f})[/{color}]\n\n"
        f"  That {sig['direction'].upper()} signal you skipped → would have been "
        f"[{color}]{'+'if pnl>=0 else ''}{pnl:.0f}[/{color}]\n"
        f"  [dim]Info only — not counted in your balance[/dim]",
        border_style=color, padding=(1, 2)
    ))


def _handle_keyboard(cmd: str, detector: LiveDetector):
    cmd = cmd.strip().lower()
    if cmd == "s":
        _print_status(detector)
    elif cmd == "j":
        show_journal()
    elif cmd == "q":
        console.print("[yellow]Stopping bot...[/yellow]")
        sys.exit(0)
    elif cmd == "h":
        console.print(
            "\n[bold]Commands:[/bold]\n"
            "  [cyan]s[/cyan] → current status\n"
            "  [cyan]j[/cyan] → trade journal\n"
            "  [cyan]q[/cyan] → quit\n"
            "  [cyan]h[/cyan] → this help\n"
        )
    elif cmd:
        console.print("[dim]Unknown command. Type h for help.[/dim]")


def _start_keyboard_listener(detector: LiveDetector):
    """Background thread — listen for keyboard commands while bot runs."""
    def _run():
        while True:
            try:
                cmd = input()
                _handle_keyboard(cmd, detector)
            except Exception:
                time.sleep(1)
    threading.Thread(target=_run, daemon=True).start()


def _print_status(detector: LiveDetector):
    now = datetime.now(tz=EST)
    ar = detector.asia_ranges.get(date.today())
    s = state.summary()
    buf = s["drawdown_buffer"]
    buf_color = "red" if buf < 200 else ("yellow" if buf < 400 else "green")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("k", style="dim")
    table.add_column("v")
    table.add_row("Time (EST)", now.strftime("%H:%M:%S"))
    table.add_row("Asia High",    f"[orange1]{ar['high']:.2f}[/orange1]" if ar else "not set yet")
    table.add_row("Asia Low",     f"[orange1]{ar['low']:.2f}[/orange1]"  if ar else "not set yet")
    pd = getattr(detector, "prev_day", {})
    if pd.get("high"):
        table.add_row("Prev Day H",  f"[dim]{pd['high']:.2f}[/dim]")
        table.add_row("Prev Day L",  f"[dim]{pd['low']:.2f}[/dim]")
    table.add_row("Sweep",      f"Bull={'YES' if detector.bull_sweep else 'no'}  Bear={'YES' if detector.bear_sweep else 'no'}")
    table.add_row("MSS",        f"Bull={'YES' if detector.bull_mss else 'no'}  Bear={'YES' if detector.bear_mss else 'no'}")
    sf = smart.summary()
    table.add_row("Trades today",  f"{s['trades_today']}/2")
    table.add_row("Win streak",    f"[green]{sf['consecutive_wins']}[/green]" if sf['consecutive_wins'] > 0 else "0")
    table.add_row("Loss streak",   f"[red]{sf['consecutive_losses']}[/red]"   if sf['consecutive_losses'] > 0 else "0")
    now_est = datetime.now(tz=EST)
    table.add_row("Min score now", f"{smart.min_score_required(now_est.hour, now_est.minute, now_est.weekday())}/5")
    table.add_row("Market",        "[red]CHOPPY — careful[/red]" if sf['choppy'] else "[green]OK[/green]")
    table.add_row("Daily P&L",  f"${s['daily_pnl']:.0f}")
    table.add_row("Buffer",     f"[{buf_color}]${buf:.0f}[/{buf_color}] remaining")
    table.add_row("Progress",   f"{s['progress_pct']}% to $1,500 target")
    console.print(table)


async def _run_realtime(detector: LiveDetector):
    """Try Tradovate real-time feed. Returns False if auth fails."""
    from tradovate_feed import TradovateFeed
    from config import TRADOVATE_USERNAME, TRADOVATE_PASSWORD

    if not TRADOVATE_USERNAME or not TRADOVATE_PASSWORD:
        return False

    feed = TradovateFeed(TRADOVATE_USERNAME, TRADOVATE_PASSWORD)
    console.print("[dim]Connecting to Tradovate real-time feed...[/dim]")

    ok = await feed.authenticate()
    if not ok:
        console.print("[yellow]Tradovate real-time auth failed — using yfinance (slower)[/yellow]")
        return False

    console.print("[green]✓ Tradovate real-time feed connected — zero delay[/green]")

    # Determine active contract
    now = datetime.now(tz=EST)
    month_map = {3: "H", 6: "M", 9: "U", 12: "Z"}
    y = str(now.year)[-1]
    symbol = next(f"MNQ{month_map[m]}{y}" for m in [3,6,9,12] if now.month <= m)

    def on_tick(price: float, ts: datetime):
        detector.last_rt_price = price
        detector.last_rt_time  = ts
        # Check sweep on every tick — zero delay
        signal = detector.check_price(price, ts)
        if signal:
            _print_signal(signal)

    def on_bar(bar: dict):
        _print_event(f"Bar closed — O:{bar['open']:.2f} H:{bar['high']:.2f} L:{bar['low']:.2f} C:{bar['close']:.2f}", "dim")
        detector.ingest_bar(bar)

    feed.on_tick      = on_tick
    feed.on_bar_close = on_bar

    await feed.stream(symbol)
    return True


def _run_yfinance_loop(detector: LiveDetector):
    """
    Fast price loop:
    - Every 3 seconds: fetch live price via fast_info (near real-time)
    - Every 5 minutes: refresh bar data for context (Asia range, VWAP)
    """
    console.print("[green]✓ Fast price feed active (updates every 3 seconds)[/green]\n")

    last_status_min  = -1
    last_bar_refresh = 0
    tick_count       = 0

    while True:
        try:
            now_est = datetime.now(tz=EST)
            hour, minute = now_est.hour, now_est.minute
            mins = hour * 60 + minute

            if mins >= (11 * 60 + 35):
                console.print("[dim]Session over. Good job.[/dim]")
                break

            if mins < (9 * 60 + 0):
                time.sleep(30)
                continue

            # Refresh bar data every 5 minutes
            if tick_count % 100 == 0:
                detector.fetch()

            # Get live price every 3 seconds
            price = detector.get_live_price()
            if price:
                signal = detector.check_price(price, now_est)
                if signal:
                    _print_signal(signal)
                    _ask_trade(signal)

            # Status every 5 minutes
            if minute % 5 == 0 and minute != last_status_min:
                if price:
                    _print_event(f"Price: {price:.2f}", "dim")
                _print_status(detector)
                last_status_min = minute

            tick_count += 1
            time.sleep(1)

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped.[/yellow]")
            sys.exit(0)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            time.sleep(5)


def main():
    console.print(Panel(
        "[bold cyan]TJR Live Detector — MNQ[/bold cyan]\n\n"
        "Watching for Asia sweep + MSS setups...\n"
        "Trade window: [bold]9:30 AM – 11:30 AM EST[/bold]\n\n"
        "[yellow]Keep this terminal open all morning.[/yellow]\n"
        "When a signal fires you'll see a big green or red box.\n"
        "Go execute on TradingView immediately.",
        box=box.DOUBLE_EDGE,
        border_style="cyan",
    ))
    console.print()

    detector = LiveDetector()

    # ── Fast feed ──────────────────────────────────────────────────────────────
    console.print("[dim]Starting fast price feed...[/dim]")
    feed = get_feed()
    console.print(f"[green]✓ Fast feed active — price updates every 0.5s  |  Current: {feed.price:.2f}[/green]")

    # ── Bar data for strategy context ──────────────────────────────────────────
    console.print("[dim]Loading bar data...[/dim]")
    detector.fetch()

    # ── Morning briefing ───────────────────────────────────────────────────────
    ar = detector.asia_ranges.get(date.today())
    detector.prev_day = print_morning_briefing(
        asia_high     = ar["high"] if ar else None,
        asia_low      = ar["low"]  if ar else None,
        current_price = feed.price,
        state         = state,
        smart         = smart,
    )
    print_news_warning()
    console.print()
    console.print("[dim]Commands: s=status  j=journal  q=quit  h=help[/dim]")
    console.print()

    # ── Keyboard listener ──────────────────────────────────────────────────────
    _start_keyboard_listener(detector)

    # ── Run ────────────────────────────────────────────────────────────────────
    try:
        success = asyncio.run(_run_realtime(detector))
    except Exception:
        success = False

    if not success:
        _run_yfinance_loop(detector)

    # ── End of session summary ─────────────────────────────────────────────────
    print_session_summary(state, smart, detector.today_signals, detector.today_missed)


def show_journal():
    """Show full trade journal. Run: python3 live_detector.py /journal"""
    from journal.trade_journal import TradeJournal
    journal = TradeJournal()
    trades = journal.get_all_trades()
    stats  = journal.get_stats()

    if not trades:
        console.print("[dim]No trades in journal yet.[/dim]")
        return

    console.rule("[bold cyan]TJR Trade Journal[/bold cyan]")
    console.print()

    table = Table(box=box.SIMPLE_HEAD, show_header=True)
    table.add_column("Date",      style="dim")
    table.add_column("Dir")
    table.add_column("Entry")
    table.add_column("Stop")
    table.add_column("TP2")
    table.add_column("P&L")
    table.add_column("Score")
    table.add_column("Status")
    table.add_column("Reason", style="dim")

    for t in trades:
        pnl = t.get("pnl_dollars")
        status = t.get("status", "?")
        pnl_str = (
            f"[green]+${pnl:.0f}[/green]" if pnl and pnl > 0
            else f"[red]-${abs(pnl):.0f}[/red]" if pnl and pnl < 0
            else "[dim]—[/dim]"
        )
        status_color = (
            "green"  if status in ("CLOSED",) and pnl and pnl > 0
            else "red"    if status == "CLOSED" and pnl and pnl <= 0
            else "yellow" if status == "OPEN"
            else "dim"
        )
        table.add_row(
            str(t.get("timestamp",""))[:16],
            "[green]LONG[/green]"  if t.get("direction") == "long" else "[red]SHORT[/red]",
            f"{t.get('entry_price', 0):.2f}",
            f"{t.get('stop_price',  0):.2f}",
            f"{t.get('tp2_price',   0):.2f}",
            pnl_str,
            f"{t.get('score', 0)}/5",
            f"[{status_color}]{status}[/{status_color}]",
            str(t.get("score_breakdown") or "")[:30],
        )

    console.print(table)
    console.print()
    console.print(
        f"Total: [bold]{stats['total_trades']}[/bold] trades  |  "
        f"[green]{stats['wins']} wins[/green]  [red]{stats['losses']} losses[/red]  |  "
        f"Win rate [bold]{stats['win_rate']}%[/bold]  |  "
        f"Total P&L [bold]${stats['total_pnl']:+.2f}[/bold]"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "/journal":
        show_journal()
    else:
        main()
