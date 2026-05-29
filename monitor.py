"""
Live session monitor — run from 9:20 AM ET.

  python3 monitor.py

Features:
  - Real-time NQ price every 0.5s via WebSocket + yfinance fallback
  - Signal detection on each 5-min bar close
  - Trade confirmation: after each signal asks "Did you take it? (y/n)"
    → only confirmed trades count toward the 3-trade daily limit
  - After confirming a trade: "Win or Loss? (w/l/skip)" to teach the bot
  - Direction lock: once a signal fires, opposite-direction signals are
    suppressed for 20 minutes (no more LONG + SHORT spam)
  - Bot memory: every real trade recorded → regime-specific WR improves scoring
  - PDH/PDL/PMH/PML alert levels
  - Day type + overnight classification at session open
  - Bot memory insights shown at session start
"""
from __future__ import annotations
import sys
import time
import json
import threading
import queue
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.panel import Panel

from fast_feed import get_feed
from backtest.quant_engine import run_quant_today, QuantTrade
from backtest.data_loader import load_nq, label_sessions
from backtest.quant_engine import _load_vix
from notifications import (
    alert_signal, alert_session_start, alert_session_end, alert_risk_warning,
    alert_breakeven, alert_warning,
)
from strategy.quant_regime import (
    get_atr_adaptive, classify_market_full, get_overnight_range_type,
    get_expiry_context,
)
from strategy.inst_levels import get_key_levels, KeyLevels
from strategy.bot_memory import (
    log_signal, confirm_signal_taken, report_outcome,
    get_confirmed_trades_today, get_pending_signal_id,
    is_paused, print_status, get_status,
)

EST       = ZoneInfo("America/New_York")
console   = Console()
ACCT_PATH = Path(__file__).parent / "journal" / "account.json"
TICKER    = yf.Ticker("NQ=F")

# ── Direction lock — prevents contradictory signals ───────────────────────────
DIRECTION_LOCK_MINUTES = 20   # after a signal, suppress opposite direction for this long
_session_dir_lock: str | None   = None
_session_dir_lock_until: datetime | None = None

# ── Input queue — background stdin reader ─────────────────────────────────────
_input_q: queue.Queue = queue.Queue()

def _stdin_reader():
    """Background thread: reads user keyboard input without blocking the main loop."""
    while True:
        try:
            line = sys.stdin.readline()
            if line:
                _input_q.put(line.strip().lower())
        except Exception:
            break

threading.Thread(target=_stdin_reader, daemon=True).start()

# ── Pending confirmation state ────────────────────────────────────────────────
_pending_confirm: dict | None   = None   # signal waiting for y/n
_pending_outcome:  dict | None  = None   # confirmed trade waiting for w/l


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(tz=EST)


def _load_balance() -> tuple[float, float]:
    if ACCT_PATH.exists():
        acct = json.loads(ACCT_PATH.read_text())
        bal  = acct.get("current_balance", 25000.0)
        peak = acct.get("peak_eod_balance", 25000.0)
        return bal, bal - (peak - 1000.0)
    return 25000.0, 1000.0


def _signal_key(t: QuantTrade) -> str:
    return f"{t.date}-{t.strategy}-{t.direction}-{round(t.entry, 0)}-{round(t.stop, 0)}"


def _bar_minute(dt: datetime) -> int:
    return (dt.minute // 5) * 5


def _set_direction_lock(direction: str) -> None:
    global _session_dir_lock, _session_dir_lock_until
    _session_dir_lock       = direction
    _session_dir_lock_until = _now() + timedelta(minutes=DIRECTION_LOCK_MINUTES)


def _direction_is_locked(direction: str) -> bool:
    """Returns True if this direction should be suppressed right now."""
    global _session_dir_lock, _session_dir_lock_until
    if _session_dir_lock is None:
        return False
    if _now() >= _session_dir_lock_until:
        _session_dir_lock = None
        return False
    return _session_dir_lock != direction   # True = opposite of locked direction


def _compute_levels(bar_cache: pd.DataFrame) -> dict:
    """ORB high/low, IB high/low, VWAP from today's completed bars."""
    today   = date.today()
    est_idx = bar_cache.index.tz_convert(EST)
    mask    = est_idx.date == today
    td      = bar_cache[mask]
    ti      = est_idx[mask]
    if td.empty:
        return {}

    levels: dict = {}

    orb = td[(ti.hour == 9) & (ti.minute >= 30) & (ti.minute < 35)]
    if not orb.empty:
        levels["orb_high"] = float(orb["High"].max())
        levels["orb_low"]  = float(orb["Low"].min())

    ib = td[((ti.hour == 9) & (ti.minute >= 30)) | ((ti.hour == 10) & (ti.minute < 30))]
    if not ib.empty:
        levels["ib_high"] = float(ib["High"].max())
        levels["ib_low"]  = float(ib["Low"].min())

    if "Volume" in td.columns and td["Volume"].sum() > 0:
        typ  = (td["High"] + td["Low"] + td["Close"]) / 3
        vol  = td["Volume"].replace(0, 1)
        levels["vwap"] = float((typ * vol).sum() / vol.sum())

    recent = bar_cache.tail(20)
    if len(recent) >= 2:
        tr = pd.concat([
            recent["High"] - recent["Low"],
            (recent["High"] - recent["Close"].shift()).abs(),
            (recent["Low"]  - recent["Close"].shift()).abs(),
        ], axis=1).max(axis=1)
        levels["atr"] = float(tr.tail(14).mean())

    # PDH / PDL / PMH / PML
    try:
        key_levels = get_key_levels(bar_cache, today)
        if key_levels:
            levels["pdh"] = key_levels.pdh
            levels["pdl"] = key_levels.pdl
            if key_levels.pmh > 0:
                levels["pmh"] = key_levels.pmh
            if key_levels.pml > 0:
                levels["pml"] = key_levels.pml
    except Exception:
        pass

    return levels


def _fetch_latest_bars() -> pd.DataFrame:
    df = TICKER.history(period="2d", interval="5m", auto_adjust=True)
    return df.tail(10)


def _load_bar_cache() -> pd.DataFrame:
    console.print("Loading bar history...", end=" ")
    df = load_nq(interval="5m", period="10d")
    df = label_sessions(df, interval="5m")
    console.print(f"[green]{len(df)} bars.[/green]")
    return df


def _load_vix_cache() -> dict:
    console.print("Loading VIX...", end=" ")
    vix = _load_vix(period="90d")
    console.print(f"[green]{len(vix)} days.[/green]")
    return vix


def _append_latest(cache: pd.DataFrame) -> pd.DataFrame:
    latest = _fetch_latest_bars()
    if latest.index.tz is not None and str(latest.index.tz) != "UTC":
        latest = latest.copy()
        latest.index = latest.index.tz_convert("UTC")
    combined = pd.concat([cache, latest])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


# ── Session open summary ──────────────────────────────────────────────────────

def _print_session_open_summary(bar_cache: pd.DataFrame, vix_cache: dict, price: float) -> None:
    """Print institutional context at session open: day type, key levels, bot insights."""
    today   = date.today()
    vix     = 18.0
    if today in vix_cache:
        vix = vix_cache[today]

    console.print("\n[bold cyan]━━━ SESSION OPEN BRIEF ━━━[/bold cyan]")

    # Expiry context
    try:
        exp = get_expiry_context(today)
        if exp["is_expiry_day"]:
            products = "+".join(exp["expiry_products"])
            risk = exp["gamma_pin_risk"]
            bias = exp["recommended_bias"].replace("_", "-")
            risk_col = "red" if risk == "high" else "yellow"
            console.print(
                f"  [bold {risk_col}]📅 {products} EXPIRY TODAY[/bold {risk_col}]  "
                f"Pin risk: [{risk_col}]{risk.upper()}[/{risk_col}]  Bias: {bias}"
            )
    except Exception:
        pass

    # Overnight range / day type
    try:
        atr = get_atr_adaptive(bar_cache, today)
        if atr > 0:
            ov = get_overnight_range_type(bar_cache, today, atr)
            bias = ov["day_type_bias"].upper()
            pct  = ov["overnight_pct_atr"] * 100
            if ov["breakout_favored"]:
                col = "green"
                strats = "ORB/IB/Gap favored"
            elif ov["meanrev_favored"]:
                col = "yellow"
                strats = "VWAP/FVG favored"
            else:
                col  = "white"
                strats = "all strategies valid"
            console.print(
                f"  DAY TYPE [bold {col}]{bias}[/bold {col}]  "
                f"Overnight {ov['overnight_range']:.0f}pts ({pct:.0f}% ATR)  →  {strats}"
            )
    except Exception:
        pass

    # Key levels
    try:
        key_levels = get_key_levels(bar_cache, today)
        if key_levels:
            console.print(
                f"  KEY LEVELS  "
                f"[orange1]PDH {key_levels.pdh:.1f}[/orange1]  "
                f"[orange1]PDL {key_levels.pdl:.1f}[/orange1]  "
                + (f"[yellow]PMH {key_levels.pmh:.1f}[/yellow]  " if key_levels.pmh > 0 else "")
                + (f"[yellow]PML {key_levels.pml:.1f}[/yellow]" if key_levels.pml > 0 else "")
            )
    except Exception:
        pass

    # Bot memory status
    try:
        mem = get_status()
        if mem["total_real_trades"] > 0:
            wr_str = f"{mem['recent_wr']*100:.0f}%" if mem["recent_wr"] is not None else "n/a"
            console.print(
                f"  BOT MEMORY  "
                f"{mem['total_real_trades']} real trades  WR {wr_str}  "
                f"Next: {mem['contracts_next']} contract(s)  "
                f"[dim]{mem['notes']}[/dim]"
            )
            for insight in mem["insights"][:3]:
                col = "green" if "HOT" in insight else "red"
                console.print(f"    [{col}]{insight}[/{col}]")
        else:
            console.print("  BOT MEMORY  No real trades yet — memory building from today")
    except Exception:
        pass

    console.print("[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n")


# ── Input processing: y/n confirmation and w/l outcome ───────────────────────

def _process_input(line: str) -> None:
    """Handle user keyboard input in the main loop."""
    global _pending_confirm, _pending_outcome

    if _pending_confirm and line in ("y", "yes", "n", "no"):
        sig_id   = _pending_confirm["signal_id"]
        strategy = _pending_confirm["strategy"]
        taken    = line in ("y", "yes")
        confirm_signal_taken(sig_id, taken)

        if taken:
            console.print(
                f"  [bold green]✓ Logged: {strategy.upper()} taken "
                f"({get_confirmed_trades_today()}/{3} today)[/bold green]"
            )
            # Now ask for outcome
            _pending_outcome   = _pending_confirm.copy()
            _pending_outcome["confirmed"] = True
            console.print(
                "  [dim]Report outcome when trade closes: [bold]w[/bold] = win  "
                "[bold]l[/bold] = loss  [bold]s[/bold] = skip[/dim]"
            )
        else:
            console.print(
                f"  [dim]Skipped — slot still available "
                f"({get_confirmed_trades_today()}/{3} confirmed today)[/dim]"
            )
        _pending_confirm = None
        return

    if _pending_outcome and line in ("w", "win", "l", "loss", "s", "skip"):
        if line in ("s", "skip"):
            console.print("  [dim]Outcome skipped.[/dim]")
            _pending_outcome = None
            return

        outcome    = "WIN"  if line in ("w", "win")  else "LOSS"
        sig_id     = _pending_outcome["signal_id"]
        entry      = _pending_outcome["entry"]
        stop       = _pending_outcome["stop"]
        target     = _pending_outcome["target"]
        direction  = _pending_outcome["direction"]
        strategy   = _pending_outcome["strategy"]

        # Estimate P&L (user can refine — best effort from signal levels)
        if outcome == "WIN":
            pnl = abs(target - entry) * 2.0   # 1 MNQ contract × $2/pt
        else:
            pnl = -abs(entry - stop) * 2.0

        report_outcome(sig_id, outcome, pnl)

        col = "green" if outcome == "WIN" else "red"
        console.print(
            f"  [{col}]Bot learned: {strategy.upper()} {direction.upper()} → "
            f"{outcome}  ${pnl:+.2f}[/{col}]"
        )
        _pending_outcome = None

        # Check if session should pause
        paused, reason = is_paused()
        if paused:
            console.print(f"\n  [bold red]⚠  BOT PAUSED: {reason}[/bold red]")
        return


# ── Main monitor loop ─────────────────────────────────────────────────────────

def run_monitor():
    global _pending_confirm, _pending_outcome

    feed = get_feed()

    console.print(Panel(
        "[bold cyan]NQ Quant System — Live Monitor[/bold cyan]\n"
        "[dim]Real-time price · Signal check on bar close · "
        "Memory-driven self-improvement · Type y/n after signals[/dim]",
        border_style="cyan"
    ))

    console.print("Connecting...", end=" ")
    for _ in range(40):
        if feed.price:
            break
        time.sleep(0.5)
    console.print(f"[green]NQ ${feed.price:,.1f}[/green]")

    bar_cache = _load_bar_cache()
    vix_cache = _load_vix_cache()

    bal, buf = _load_balance()
    buf_col  = "red" if buf < 300 else ("yellow" if buf < 500 else "green")
    console.print(
        f"Balance [bold]${bal:,.2f}[/bold]  "
        f"Buffer [{buf_col}]${buf:.0f}[/{buf_col}]  "
        f"Floor ${bal - buf:,.0f}\n"
    )

    # Print bot memory status
    print_status()

    seen_signals:  set[str] = set()
    be_watches:    list     = []
    warned_start            = False
    warned_end              = False
    session_open_done       = False
    last_bar_min: int       = -1
    key_levels:   dict      = _compute_levels(bar_cache)
    level_alerts: set[str]  = set()

    while True:
        now   = _now()
        h, m  = now.hour, now.minute
        price = feed.price or 0.0

        # ── Process keyboard input (non-blocking) ─────────────────────────────
        try:
            while not _input_q.empty():
                line = _input_q.get_nowait()
                if line:
                    _process_input(line)
        except queue.Empty:
            pass

        # ── 9:25 AM pre-market warning ────────────────────────────────────
        if h == 9 and m == 25 and not warned_start:
            warned_start = True
            bal, buf = _load_balance()
            alert_session_start()
            console.print(
                f"\n[yellow bold]09:25[/yellow bold]  Market opens in 5 min  "
                f"NQ ${price:,.1f}  Buffer ${buf:.0f}"
            )

        # ── 9:30 AM session open brief ────────────────────────────────────
        if h == 9 and m >= 30 and not session_open_done:
            session_open_done = True
            _print_session_open_summary(bar_cache, vix_cache, price)

        # ── 12:00 PM session end ─────────────────────────────────────────
        if h >= 12 and not warned_end:
            warned_end = True
            alert_session_end()
            console.print(f"\n[bold red]12:00[/bold red]  Session over — stop trading.")
            break

        # ── Breakeven watcher ─────────────────────────────────────────────
        if price and be_watches:
            for watch in be_watches:
                if watch["notified"]:
                    continue
                hit = (watch["direction"] == "long"  and price >= watch["be_trigger"]) or \
                      (watch["direction"] == "short" and price <= watch["be_trigger"])
                if hit:
                    watch["notified"] = True
                    alert_breakeven(watch["strategy"], watch["direction"], watch["entry"])
                    console.print(
                        f"\n  [bold cyan]🔒 MOVE SL → {watch['entry']:.1f}  "
                        f"({watch['strategy'].upper()} — you are now risk-free)[/bold cyan]"
                    )

        # ── Real-time level alerts: approaching + crossing ────────────────
        _APPROACH = 10.0
        if price and key_levels and 9 <= h < 12:
            # Pause if bot says so
            paused, pause_reason = is_paused()

            checks = [
                ("ORB HIGH", key_levels.get("orb_high"), "long",  "[cyan]"),
                ("ORB LOW",  key_levels.get("orb_low"),  "short", "[cyan]"),
                ("IB HIGH",  key_levels.get("ib_high"),  "long",  "[blue]"),
                ("IB LOW",   key_levels.get("ib_low"),   "short", "[blue]"),
                ("PDH",      key_levels.get("pdh"),      "short", "[orange1]"),
                ("PDL",      key_levels.get("pdl"),      "long",  "[orange1]"),
                ("PMH",      key_levels.get("pmh"),      "short", "[yellow]"),
                ("PML",      key_levels.get("pml"),      "long",  "[yellow]"),
            ]
            for name, lvl, direction, col_tag in checks:
                if not lvl:
                    continue

                # Direction lock check: suppress if opposite direction is locked
                if _direction_is_locked(direction):
                    continue

                if direction == "long":
                    approaching = (lvl - _APPROACH) <= price < lvl
                    crossed     = price >= lvl
                else:
                    approaching = lvl < price <= (lvl + _APPROACH)
                    crossed     = price <= lvl

                col = col_tag.strip("[]")

                app_key = f"APPROACH_{name}_{lvl:.0f}"
                if approaching and app_key not in level_alerts:
                    level_alerts.add(app_key)
                    atr = key_levels.get("atr", 50.0)
                    if "ORB" in name:
                        orb_h = key_levels.get("orb_high", lvl)
                        orb_l = key_levels.get("orb_low",  lvl)
                        sl = (orb_l - 2) if direction == "long" else (orb_h + 2)
                        tp = lvl + (lvl - sl) * 2 if direction == "long" else lvl - (sl - lvl) * 2
                    elif "IB" in name:
                        sl = (lvl - atr * 0.5) if direction == "long" else (lvl + atr * 0.5)
                        tp = (lvl + atr * 1.5) if direction == "long" else (lvl - atr * 1.5)
                    else:  # PDH/PDL/PMH/PML
                        sl = (lvl - atr * 0.04) if direction == "long" else (lvl + atr * 0.04)
                        tp = (lvl + atr * 0.08) if direction == "long" else (lvl - atr * 0.08)
                    risk = abs(lvl - sl)
                    side = "[green]LONG ▲[/green]" if direction == "long" else "[red]SHORT ▼[/red]"
                    console.print(
                        f"\n  [bold {col}]🎯 {name} {lvl:.1f} APPROACHING → {side}[/bold {col}]\n"
                        f"  [bold]  Entry ~{lvl:.1f}  SL {sl:.1f}  TP {tp:.1f}[/bold]  "
                        f"[dim](risk {risk:.0f}pts — exact levels on bar close)[/dim]"
                    )
                    alert_warning(
                        f"SET LIMIT  E:{lvl:.0f}  SL:{sl:.0f}  TP:{tp:.0f}",
                        f"{name} approaching — place {direction.upper()} limit NOW"
                    )

                cross_key = f"CROSS_{name}_{lvl:.0f}"
                if crossed and cross_key not in level_alerts:
                    level_alerts.add(cross_key)
                    atr   = key_levels.get("atr", 50.0)
                    entry = price
                    if "ORB" in name:
                        orb_h = key_levels.get("orb_high", lvl)
                        orb_l = key_levels.get("orb_low",  lvl)
                        orb_r = orb_h - orb_l
                        sl = (orb_l - 2) if direction == "long" else (orb_h + 2)
                        tp = (orb_h + orb_r * 1.5) if direction == "long" else (orb_l - orb_r * 1.5)
                    elif "IB" in name:
                        ib_h = key_levels.get("ib_high", lvl)
                        ib_l = key_levels.get("ib_low",  lvl)
                        ib_r = ib_h - ib_l
                        sl = (ib_l - 2) if direction == "long" else (ib_h + 2)
                        tp = (ib_h + ib_r * 1.5) if direction == "long" else (ib_l - ib_r * 1.5)
                    else:
                        sl = (lvl - atr * 0.04) if direction == "long" else (lvl + atr * 0.04)
                        tp = (lvl + atr * 0.08) if direction == "long" else (lvl - atr * 0.08)
                    risk = abs(entry - sl)
                    side = "[green]LONG ▲[/green]" if direction == "long" else "[red]SHORT ▼[/red]"
                    console.print(
                        f"\n  [bold yellow]⚡ {name} {lvl:.1f} HIT → {side}[/bold yellow]\n"
                        f"  [bold]  Entry {entry:.1f}  SL {sl:.1f}  TP {tp:.1f}[/bold]  "
                        f"[dim](risk {risk:.0f}pts — enter at market NOW)[/dim]"
                    )
                    alert_signal(name, direction, entry, sl, tp)

            # ── VWAP bounce pre-alert ─────────────────────────────────────
            vwap = key_levels.get("vwap")
            atr  = key_levels.get("atr", 50.0)
            if vwap and (h > 9 or (h == 9 and m >= 30)):
                dist = price - vwap
                vwap_key = round(vwap / 5) * 5

                last_vwap_alert = getattr(run_monitor, "_last_vwap_alert", None)
                last_vwap_dir   = getattr(run_monitor, "_last_vwap_dir", None)
                cooldown_ok = True
                if last_vwap_alert is not None:
                    elapsed = (now - last_vwap_alert).total_seconds()
                    if elapsed < 300 and last_vwap_dir != (dist > 0):
                        cooldown_ok = False

                if 0 < dist <= _APPROACH and cooldown_ok and not _direction_is_locked("long"):
                    app_key = f"APPROACH_VWAP_LONG_{vwap_key}"
                    if app_key not in level_alerts:
                        level_alerts.add(app_key)
                        run_monitor._last_vwap_alert = now
                        run_monitor._last_vwap_dir   = True
                        sl   = vwap - atr * 0.5
                        tp   = vwap + atr * 1.5
                        risk = vwap - sl
                        console.print(
                            f"\n  [bold cyan]🎯 VWAP {vwap:.1f} APPROACHING → [green]LONG ▲[/green][/bold cyan]\n"
                            f"  [bold]  Entry ~{vwap:.1f}  SL {sl:.1f}  TP {tp:.1f}[/bold]  "
                            f"[dim](risk {risk:.0f}pts)[/dim]"
                        )
                        alert_warning(
                            f"VWAP BOUNCE  E:{vwap:.0f}  SL:{sl:.0f}  TP:{tp:.0f}",
                            f"Price dropping to VWAP {vwap:.1f} — LONG bounce setup forming"
                        )

                elif -_APPROACH <= dist < 0 and cooldown_ok and not _direction_is_locked("short"):
                    app_key = f"APPROACH_VWAP_SHORT_{vwap_key}"
                    if app_key not in level_alerts:
                        level_alerts.add(app_key)
                        run_monitor._last_vwap_alert = now
                        run_monitor._last_vwap_dir   = False
                        sl   = vwap + atr * 0.5
                        tp   = vwap - atr * 1.5
                        risk = sl - vwap
                        console.print(
                            f"\n  [bold cyan]🎯 VWAP {vwap:.1f} APPROACHING → [red]SHORT ▼[/red][/bold cyan]\n"
                            f"  [bold]  Entry ~{vwap:.1f}  SL {sl:.1f}  TP {tp:.1f}[/bold]  "
                            f"[dim](risk {risk:.0f}pts)[/dim]"
                        )
                        alert_warning(
                            f"VWAP BOUNCE  E:{vwap:.0f}  SL:{sl:.0f}  TP:{tp:.0f}",
                            f"Price rising to VWAP {vwap:.1f} — SHORT bounce setup forming"
                        )

        # ── Live price ticker ─────────────────────────────────────────────
        if 9 <= h < 12 and price:
            confirmed = get_confirmed_trades_today()
            age    = feed.age_seconds
            source = getattr(feed, "source", "")
            src_tag = "[green]WS[/green]" if "NDX" in source else "[yellow]delayed[/yellow]"
            stale   = "[red]STALE[/red]" if age > 10 else ""
            paused_tag = "  [bold red]PAUSED[/bold red]" if is_paused()[0] else ""
            console.print(
                f"[dim]{now.strftime('%H:%M:%S')}[/dim]  "
                f"[bold]${price:,.1f}[/bold]  {src_tag}  {stale}"
                f"  [dim]Confirmed {confirmed}/3[/dim]{paused_tag}",
                end="\r"
            )

        # ── Bar close check ───────────────────────────────────────────────
        cur_bar = _bar_minute(now)
        if cur_bar != last_bar_min and h >= 9 and h < 12:
            last_bar_min = cur_bar
            t0 = time.monotonic()
            console.print()

            # Check if paused before even trying signals
            paused, pause_reason = is_paused()
            confirmed_today = get_confirmed_trades_today()

            if paused:
                console.print(
                    f"[dim]{now.strftime('%H:%M')}[/dim]  "
                    f"[bold red]PAUSED — {pause_reason}[/bold red]"
                )
                bar_cache = _append_latest(bar_cache)
                key_levels = _compute_levels(bar_cache)
                time.sleep(0.5)
                continue

            if confirmed_today >= 3:
                console.print(
                    f"[dim]{now.strftime('%H:%M')}[/dim]  "
                    f"[bold yellow]3 confirmed trades today — limit reached[/bold yellow]"
                )
                bar_cache = _append_latest(bar_cache)
                key_levels = _compute_levels(bar_cache)
                time.sleep(0.5)
                continue

            bar_cache = _append_latest(bar_cache)
            fetch_ms  = int((time.monotonic() - t0) * 1000)

            console.print(
                f"[dim]{now.strftime('%H:%M')}[/dim]  "
                f"Bar closed · fetched in {fetch_ms}ms · checking signals...",
                end=" "
            )

            t1 = time.monotonic()
            try:
                today_trades = run_quant_today(bar_cache, vix_cache)
                new_trades   = [t for t in today_trades
                                if _signal_key(t) not in seen_signals]
                check_ms     = int((time.monotonic() - t1) * 1000)

                # Filter contradictory signals: enforce direction lock
                filtered_trades = []
                for t in new_trades:
                    if _direction_is_locked(t.direction):
                        # Show a note but don't alert
                        console.print(
                            f"\n  [dim]  {t.strategy.upper()} {t.direction.upper()} suppressed "
                            f"(contradicts direction lock — wait {DIRECTION_LOCK_MINUTES}min)[/dim]"
                        )
                        seen_signals.add(_signal_key(t))  # don't repeat it
                        continue
                    filtered_trades.append(t)

                if filtered_trades:
                    console.print(f"[bold green]{len(filtered_trades)} SIGNAL(S)! ({check_ms}ms)[/bold green]")
                    for t in filtered_trades:
                        seen_signals.add(_signal_key(t))

                        # Set direction lock for this session window
                        _set_direction_lock(t.direction)

                        alert_signal(t.strategy, t.direction, t.entry, t.stop, t.target)
                        side = "[green]LONG ▲[/green]" if t.direction == "long" else "[red]SHORT ▼[/red]"
                        console.print(
                            f"  [bold white]{t.strategy.upper().replace('_',' '):<22}[/bold white] "
                            f"{side}  E:[bold]{t.entry:.1f}[/bold]  "
                            f"S:{t.stop:.1f}  T:{t.target:.1f}"
                        )
                        console.print(
                            f"  [dim]Enter next bar open · ~{5 - now.second//60} min window[/dim]"
                        )

                        # Breakeven watcher
                        risk_pts = abs(t.entry - t.stop)
                        be_mult  = 2.0 if t.strategy == "orb" else 1.0
                        be_trigger = (t.entry + risk_pts * be_mult) if t.direction == "long" \
                                     else (t.entry - risk_pts * be_mult)
                        be_watches.append({
                            "strategy":   t.strategy,
                            "direction":  t.direction,
                            "entry":      t.entry,
                            "be_trigger": be_trigger,
                            "notified":   False,
                        })
                        console.print(
                            f"  [dim]BE alert: move SL → {t.entry:.1f} when price hits {be_trigger:.1f}[/dim]"
                        )

                        # Log signal to memory for tracking
                        try:
                            vix_val = vix_cache.get(date.today(), 18.0)
                            atr_val = key_levels.get("atr", 0.0)
                            sig_id = log_signal(
                                strategy=t.strategy,
                                direction=t.direction,
                                entry=t.entry,
                                stop=t.stop,
                                target=t.target,
                                vix=vix_val,
                                atr=atr_val,
                                trend=getattr(t, "trend_dir", ""),
                                vix_regime="normal" if vix_val < 22 else "elevated",
                                day_name=date.today().strftime("%a"),
                            )
                        except Exception:
                            sig_id = None

                        # ASK USER IF THEY TOOK IT
                        console.print(
                            f"\n  [bold yellow]▶ Did you take this trade?  "
                            f"[bold]y[/bold] = yes  [bold]n[/bold] = no[/bold yellow]"
                        )
                        _pending_confirm = {
                            "signal_id": sig_id,
                            "strategy":  t.strategy,
                            "direction": t.direction,
                            "entry":     t.entry,
                            "stop":      t.stop,
                            "target":    t.target,
                        }
                        # Only ask about first signal if multiple fire at once
                        break
                else:
                    if not new_trades:
                        console.print(f"[dim]none ({check_ms}ms · {len(seen_signals)} fired today)[/dim]")
                    else:
                        console.print(f"[dim]filtered ({check_ms}ms)[/dim]")

                # Drawdown warning
                _, buf = _load_balance()
                if buf < 300:
                    alert_risk_warning(f"Buffer critical: ${buf:.0f} left!")
                    console.print(f"[bold red]  ⚠ Buffer ${buf:.0f} — consider stopping[/bold red]")

            except Exception as e:
                console.print(f"[red]error: {e}[/red]")

            key_levels = _compute_levels(bar_cache)

        time.sleep(0.5)


if __name__ == "__main__":
    try:
        run_monitor()
    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped.[/dim]")
        print_status()
