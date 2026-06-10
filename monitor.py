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
import os
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
from rich.table import Table
from rich.rule import Rule
from rich.text import Text
from rich.columns import Columns
from rich.align import Align

from fast_feed import get_feed
from backtest.quant_engine import run_quant_today, QuantTrade
from backtest.data_loader import load_nq, load_es, label_sessions
from backtest.quant_engine import _load_vix

# ── Engine selection ──────────────────────────────────────────────────────────
# "hybrid" (default) -> full institutional stack + meta-labeling ML gate
#                       (gate behavior controlled by ISOGENY_ML_GATE:
#                       "shadow" = ML scores shown, never vetoes signals [default]
#                       "live"   = ML actively filters low-confidence setups
#                       "off"    = rules-only, no ML opinion)
# "quant"            -> conservative rule-only scanner (~1 signal/2 weeks)
ISOGENY_ENGINE = os.environ.get("ISOGENY_ENGINE", "hybrid").lower()

if ISOGENY_ENGINE == "hybrid":
    from backtest.hybrid_engine import (
        run_hybrid_today, HybridContext, load_hybrid_context,
    )
from notifications import (
    alert_signal, alert_session_start, alert_session_end, alert_risk_warning,
    alert_breakeven, alert_warning,
)
from strategy.quant_regime import (
    get_atr_adaptive, classify_market_full, get_overnight_range_type,
    get_expiry_context,
)
from strategy.inst_levels import get_key_levels, KeyLevels
from strategy.inst_news   import fetch_session_news
from strategy.bot_memory import (
    log_signal, confirm_signal_taken, report_outcome,
    get_confirmed_trades_today, get_pending_signal_id,
    is_paused, print_status, get_status,
)

EST       = ZoneInfo("America/New_York")
console   = Console(highlight=False)
ACCT_PATH = Path(__file__).parent / "journal" / "account.json"
TICKER    = yf.Ticker("NQ=F")
ES_TICKER = yf.Ticker("MES=F")   # only polled when ISOGENY_ENGINE=hybrid (lead-lag features)

# ── Color palette ─────────────────────────────────────────────────────────────
C_LONG    = "bright_green"
C_SHORT   = "bright_red"
C_PRICE   = "bold white"
C_ENTRY   = "bold cyan"
C_STOP    = "red"
C_TARGET  = "green"
C_DIM     = "dim white"
C_SCORE   = "bright_cyan"
C_WARN    = "bold yellow"
C_LEVEL   = "yellow"
C_HEADER  = "bold bright_white"
C_INFO    = "bright_blue"
C_GOOD    = "bright_green"
C_BAD     = "bright_red"
C_NEUTRAL = "white"


# ── TUI Helpers ───────────────────────────────────────────────────────────────

MNQ_TICK = 0.25   # MNQ minimum tick increment ($0.50 per tick)

def _tick(price: float) -> float:
    """Round to nearest valid MNQ tick (0.25 pts). Prevents 'Number format is invalid' on Tradovate."""
    return round(round(price / MNQ_TICK) * MNQ_TICK, 2)


def _banner():
    """Startup banner."""
    console.print()
    console.rule("[bold bright_white]IDK QUANT[/bold bright_white]  ·  [bright_cyan]INSTITUTIONAL ALPHA SYSTEM v7.0[/bright_cyan]", style="bright_white")
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="center")
    t.add_row("[dim]NQ Futures · 9:30 AM – 12:00 PM ET · Tradeify $25k · 20-pt scoring · Two-target exit[/dim]")
    console.print(Align.center(t))
    console.print()


def _status_bar(price: float, confirmed: int, buf: float, vix: float, atr: float,
                src_tag: str, age: float, now: datetime) -> None:
    """Single overwrite-in-place status line."""
    buf_col = C_GOOD if buf >= 500 else (C_WARN if buf >= 250 else C_BAD)
    src_col = C_GOOD if "WS" in src_tag or "LIVE" in src_tag else C_WARN
    stale   = "  [red]STALE[/red]" if age > 10 else ""

    dots = ["●", "●", "●"]
    trade_cols = []
    for i in range(3):
        if i < confirmed:
            trade_cols.append(f"[{C_GOOD}]●[/{C_GOOD}]")
        else:
            trade_cols.append("[dim]○[/dim]")
    trades_vis = " ".join(trade_cols)

    line = (
        f"[{C_DIM}]{now.strftime('%H:%M:%S')}[/{C_DIM}]  "
        f"[{C_PRICE}]NQ {price:,.2f}[/{C_PRICE}]  "
        f"[{src_col}]{src_tag}[/{src_col}]{stale}"
        f"  [dim]VIX[/dim] [white]{vix:.1f}[/white]"
        f"  [dim]ATR[/dim] [white]{atr:.0f}[/white]"
        f"  [dim]Buf[/dim] [{buf_col}]${buf:.0f}[/{buf_col}]"
        f"  [dim]Trades[/dim] {trades_vis}"
    )
    console.print(line, end="\r")


def _signal_panel(strategy: str, direction: str, entry: float, stop: float,
                  target: float, score: int = 0, n_contracts: int = 1,
                  ml_proba: float | None = None, hmm_state: str | None = None,
                  gex_bias: str | None = None) -> None:
    """Big bordered signal panel — impossible to miss."""
    # Round ALL prices to nearest 0.25 tick — Tradovate rejects non-tick prices
    entry  = _tick(entry)
    stop   = _tick(stop)
    target = _tick(target)

    side_txt  = "LONG  ▲" if direction == "long" else "SHORT  ▼"
    side_col  = C_LONG if direction == "long" else C_SHORT
    risk_pts  = abs(entry - stop)
    risk_usd  = risk_pts * 2.0 * n_contracts
    t1_level  = _tick((entry + risk_pts) if direction == "long" else (entry - risk_pts))
    t1_usd    = risk_pts * 2.0 * max(1, n_contracts // 2)
    lots_txt  = f"{n_contracts} contract{'s' if n_contracts > 1 else ''}  ({'★ FULL SIZE' if n_contracts == 2 else 'standard'})"
    score_bar = "█" * score + "░" * (21 - score)

    t = Table.grid(padding=(0, 1))
    t.add_column(min_width=14, style="dim")
    t.add_column(style="bold")
    t.add_column(style="dim")

    t.add_row("Strategy",  f"[{C_HEADER}]{strategy.upper().replace('_', ' ')}[/{C_HEADER}]", "")
    t.add_row("Direction", f"[{side_col}]{side_txt}[/{side_col}]",  "")
    t.add_row("",          "",                                         "")
    t.add_row("Entry",     f"[{C_ENTRY}]{entry:,.2f}[/{C_ENTRY}]",   "← enter at next bar open")
    t.add_row("Stop (SL)", f"[{C_STOP}]{stop:,.2f}[/{C_STOP}]",      f"← {risk_pts:.1f} pts  max −${risk_usd:.0f}")
    t.add_row("T1 (50%)",  f"[{C_TARGET}]{t1_level:,.2f}[/{C_TARGET}]",  f"← 1R  lock +${t1_usd:.0f}")
    t.add_row("T2 (50%)",  f"[{C_TARGET}]{target:,.2f}[/{C_TARGET}]",    "← Chandelier trail")
    t.add_row("",          "",                                         "")
    t.add_row("Score",     f"[{C_SCORE}]{score}/21[/{C_SCORE}]  [{C_DIM}]{score_bar}[/{C_DIM}]", "")
    t.add_row("Size",      f"[{C_WARN}]{lots_txt}[/{C_WARN}]",        "")

    if ml_proba is not None:
        ml_col = C_GOOD if ml_proba >= 0.55 else (C_WARN if ml_proba >= 0.45 else C_BAD)
        t.add_row("ML conf.", f"[{ml_col}]{ml_proba:.0%}[/{ml_col}]", "← P(win), meta-labeling gate")
    if hmm_state or gex_bias:
        ctx_bits = [b for b in (
            f"HMM {hmm_state}" if hmm_state else "",
            f"GEX {gex_bias}" if gex_bias else "",
        ) if b]
        t.add_row("Regime",   f"[{C_DIM}]{'   ·   '.join(ctx_bits)}[/{C_DIM}]", "")

    border = side_col
    console.print()
    console.print(Panel(
        t,
        title=f"[{side_col}] ★  SIGNAL CONFIRMED  [/{side_col}]",
        border_style=border,
        padding=(0, 2),
    ))


def _confirm_prompt() -> None:
    console.print(
        "  [bold yellow]▶  Did you take this trade?   "
        "[bold white]y[/bold white] = yes    "
        "[bold white]n[/bold white] = no[/bold yellow]"
    )


def _level_alert(name: str, lvl: float, direction: str, entry: float,
                 sl: float, tp: float, crossing: bool = False) -> None:
    """Formatted level approaching / crossing alert."""
    entry    = _tick(entry)
    sl       = _tick(sl)
    tp       = _tick(tp)
    side_col  = C_LONG if direction == "long" else C_SHORT
    side_txt  = "LONG ▲" if direction == "long" else "SHORT ▼"
    risk_pts  = abs(entry - sl)
    icon      = "⚡" if crossing else "⟶"
    action    = "CROSSED — ENTER NOW" if crossing else "APPROACHING"
    style     = "bold yellow" if crossing else C_LEVEL

    t = Table.grid(padding=(0, 3))
    t.add_column(style="dim", min_width=8)
    t.add_column()
    t.add_row("Entry",  f"[{C_ENTRY}]{entry:,.1f}[/{C_ENTRY}]")
    t.add_row("SL",     f"[{C_STOP}]{sl:,.1f}[/{C_STOP}]   ({risk_pts:.0f} pts)")
    t.add_row("Target", f"[{C_TARGET}]{tp:,.1f}[/{C_TARGET}]")

    console.print()
    console.print(Panel(
        t,
        title=f"[{style}]{icon}  {name} {lvl:.1f}  {action}  →  [{side_col}]{side_txt}[/{side_col}][/{style}]",
        border_style="yellow" if crossing else "dim yellow",
        padding=(0, 2),
    ))


def _be_alert(strategy: str, direction: str, entry: float) -> None:
    entry = _tick(entry)
    side = "LONG" if direction == "long" else "SHORT"
    console.print(Panel(
        f"  [{C_WARN}]Move your stop loss to  [{C_ENTRY}]{entry:,.2f}[/{C_ENTRY}]  (your entry price)[/{C_WARN}]\n"
        f"  [dim]You are now risk-free on this {strategy.upper()} {side} trade.[/dim]",
        title="[bold cyan]🔒  T1 HIT — MOVE SL TO ENTRY[/bold cyan]",
        border_style="cyan",
        padding=(0, 2),
    ))


def _bar_close_line(now: datetime, fetch_ms: int) -> None:
    console.print(
        f"\n[{C_DIM}]{now.strftime('%H:%M')}[/{C_DIM}]  "
        f"[dim]▸ bar closed  ({fetch_ms}ms)[/dim]",
        end="  "
    )

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
    df = load_nq(interval="5m")   # 60d default — needed for EMA21 trend classification
    df = label_sessions(df, interval="5m")
    console.print(f"[{C_GOOD}]✓  {len(df)} bars loaded[/{C_GOOD}]")
    return df


def _load_vix_cache() -> dict:
    vix = _load_vix(period="90d")
    console.print(f"[{C_GOOD}]✓  {len(vix)} VIX days loaded[/{C_GOOD}]")
    return vix


def _append_latest(cache: pd.DataFrame) -> pd.DataFrame:
    latest = _fetch_latest_bars()
    if latest.index.tz is not None and str(latest.index.tz) != "UTC":
        latest = latest.copy()
        latest.index = latest.index.tz_convert("UTC")
    combined = pd.concat([cache, latest])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


# ── ES feed (hybrid engine only — lead-lag features need live ES bars) ───────

def _fetch_latest_es_bars() -> pd.DataFrame:
    df = ES_TICKER.history(period="2d", interval="5m", auto_adjust=True)
    return df.tail(10)


def _load_es_cache() -> pd.DataFrame:
    df = load_es(interval="5m")   # 60d default — matches NQ cache window
    console.print(f"[{C_GOOD}]✓  {len(df)} ES bars loaded[/{C_GOOD}]")
    return df


def _append_latest_es(cache: pd.DataFrame) -> pd.DataFrame:
    latest = _fetch_latest_es_bars()
    if latest.index.tz is not None and str(latest.index.tz) != "UTC":
        latest = latest.copy()
        latest.index = latest.index.tz_convert("UTC")
    combined = pd.concat([cache, latest])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


# ── Session open summary ──────────────────────────────────────────────────────

def _print_session_open_summary(
    bar_cache: pd.DataFrame,
    vix_cache: dict,
    price: float,
    session_news: dict | None = None,
) -> None:
    """Styled session open brief using Rich tables and panels."""
    today = date.today()
    vix   = vix_cache.get(today, 18.0)

    rows: list[tuple] = []   # (label, value, style)

    # ── News ──────────────────────────────────────────────────────────────────
    if session_news:
        risk      = session_news.get("risk_level", "low")
        brief     = session_news.get("brief", "")
        events    = session_news.get("key_events", [])
        skips     = session_news.get("skip_strategies", [])
        size_w    = session_news.get("size_warning", False)
        headlines = session_news.get("headlines_shown", [])

        risk_col = {"extreme": C_BAD, "high": "red", "elevated": C_WARN}.get(risk, C_GOOD)
        rows.append(("News",    f"[{risk_col}]{brief}[/{risk_col}]", ""))

        for ev in events[:4]:
            tag_col = ("bold yellow" if "[FOMC]" in ev or "[DATA]" in ev
                       else "magenta" if "[EARNINGS]" in ev else "dim")
            rows.append(("", f"[{tag_col}]  ▸ {ev}[/{tag_col}]", ""))

        if skips:
            skip_str = "  ".join(s.upper().replace("_", " ") for s in skips)
            rows.append(("", f"[{C_BAD}]  ⚠ SKIP TODAY: {skip_str}[/{C_BAD}]", ""))
        if size_w:
            rows.append(("", f"[{C_WARN}]  ↓ REDUCE SIZE — prefer 1 contract[/{C_WARN}]", ""))

        if headlines:
            for hl in headlines[:3]:
                short = hl[:88] + "…" if len(hl) > 88 else hl
                rows.append(("", f"[dim]  · {short}[/dim]", ""))

    # ── Expiry ────────────────────────────────────────────────────────────────
    try:
        exp = get_expiry_context(today)
        if exp["is_expiry_day"]:
            products = "+".join(exp["expiry_products"])
            gpr  = exp["gamma_pin_risk"]
            bias = exp["recommended_bias"].replace("_", "-")
            ec   = C_BAD if gpr == "high" else C_WARN
            rows.append(("Expiry",
                         f"[{ec}]{products} EXPIRY[/{ec}]  "
                         f"[dim]pin-risk[/dim] [{ec}]{gpr.upper()}[/{ec}]  "
                         f"[dim]bias[/dim] {bias}", ""))
    except Exception:
        pass

    # ── Day type ──────────────────────────────────────────────────────────────
    try:
        atr = get_atr_adaptive(bar_cache, today)
        if atr > 0:
            ov    = get_overnight_range_type(bar_cache, today, atr)
            bias  = ov["day_type_bias"].upper()
            pct   = ov["overnight_pct_atr"] * 100
            if ov["breakout_favored"]:
                dcol, strats = C_GOOD, "ORB / IB / Gap Fill favored"
            elif ov["meanrev_favored"]:
                dcol, strats = C_WARN, "VWAP / FVG favored"
            else:
                dcol, strats = C_NEUTRAL, "all strategies valid"
            rows.append(("Day Type",
                         f"[{dcol}]{bias}[/{dcol}]  "
                         f"[dim]overnight[/dim] {ov['overnight_range']:.0f}pts  "
                         f"[dim]({pct:.0f}% ATR)[/dim]  →  {strats}", ""))
    except Exception:
        pass

    # ── Key levels ────────────────────────────────────────────────────────────
    try:
        kl = get_key_levels(bar_cache, today)
        if kl:
            level_parts = [
                f"[orange1]PDH {kl.pdh:.1f}[/orange1]",
                f"[orange1]PDL {kl.pdl:.1f}[/orange1]",
            ]
            if kl.pmh > 0:
                level_parts.append(f"[yellow]PMH {kl.pmh:.1f}[/yellow]")
            if kl.pml > 0:
                level_parts.append(f"[yellow]PML {kl.pml:.1f}[/yellow]")
            rows.append(("Levels", "  ".join(level_parts), ""))
    except Exception:
        pass

    # ── Bot memory ────────────────────────────────────────────────────────────
    try:
        mem    = get_status()
        n_real = mem["total_real_trades"]
        if n_real > 0:
            wr_str = f"{mem['recent_wr']*100:.0f}%" if mem["recent_wr"] is not None else "—"
            rows.append(("Bot Memory",
                         f"{n_real} real trades  [dim]WR[/dim] [{C_SCORE}]{wr_str}[/{C_SCORE}]  "
                         f"[dim]next trade:[/dim] [{C_WARN}]{mem['contracts_next']} lot(s)[/{C_WARN}]  "
                         f"[dim]{mem['notes']}[/dim]", ""))
            for insight in mem["insights"][:3]:
                icol = C_GOOD if "HOT" in insight else C_BAD
                rows.append(("", f"  [{icol}]▸ {insight}[/{icol}]", ""))
        else:
            rows.append(("Bot Memory", "[dim]No real trades yet — learning starts today[/dim]", ""))
    except Exception:
        pass

    # ── Build table ───────────────────────────────────────────────────────────
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", min_width=12, justify="right")
    t.add_column()
    for label, val, _ in rows:
        t.add_row(label, val)

    console.print()
    console.print(Panel(
        t,
        title=f"[bold bright_white]SESSION OPEN BRIEF[/bold bright_white]  "
              f"[dim]{today.strftime('%A %B %d, %Y')}[/dim]  "
              f"[dim]NQ[/dim] [{C_PRICE}]{price:,.2f}[/{C_PRICE}]  "
              f"[dim]VIX[/dim] {vix:.1f}",
        border_style="bright_cyan",
        padding=(0, 2),
    ))
    console.print()


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
            n_conf = get_confirmed_trades_today()
            dots   = "".join(["[green]●[/green]" if i < n_conf else "[dim]○[/dim]" for i in range(3)])
            console.print(
                f"  [{C_GOOD}]✓  {strategy.upper()} confirmed[/{C_GOOD}]  "
                f"{dots}  [dim]({n_conf}/3 today)[/dim]"
            )
            _pending_outcome   = _pending_confirm.copy()
            _pending_outcome["confirmed"] = True
            console.print(
                "  [dim]When trade closes, type:  "
                "[bold white]w[/bold white] = win   "
                "[bold white]l[/bold white] = loss   "
                "[bold white]s[/bold white] = skip[/dim]"
            )
        else:
            console.print(
                f"  [dim]Skipped — slot open  ({get_confirmed_trades_today()}/3 confirmed today)[/dim]"
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

        col = C_GOOD if outcome == "WIN" else C_BAD
        icon = "✓" if outcome == "WIN" else "✗"
        console.print(
            f"  [{col}]{icon}  {strategy.upper()} {direction.upper()} → "
            f"{outcome}  ${pnl:+.2f}[/{col}]  "
            f"[dim]logged to bot memory[/dim]"
        )
        _pending_outcome = None

        paused, reason = is_paused()
        if paused:
            console.print()
            console.rule(f"[{C_BAD}]⏸  BOT PAUSED — {reason}[/{C_BAD}]", style=C_BAD)
        return


# ── Main monitor loop ─────────────────────────────────────────────────────────

def run_monitor():
    global _pending_confirm, _pending_outcome

    feed = get_feed()

    _banner()

    # ── Loading sequence ──────────────────────────────────────────────────────
    load_t = Table.grid(padding=(0, 1))
    load_t.add_column(min_width=36, style="dim")
    load_t.add_column()

    console.print("[dim]Loading NQ price (1-min bars)...[/dim]", end=" ")
    for _ in range(20):
        if feed.price:
            break
        time.sleep(0.5)
    console.print(f"[{C_GOOD}]✓  NQ {feed.price:,.2f}[/{C_GOOD}]")

    console.print("[dim]Loading bar history (10d / 5m)...[/dim]", end=" ")
    bar_cache = _load_bar_cache()

    console.print("[dim]Loading VIX history...[/dim]", end=" ")
    vix_cache = _load_vix_cache()

    hybrid_ctx: HybridContext | None = None
    es_cache:   pd.DataFrame | None  = None
    if ISOGENY_ENGINE == "hybrid":
        console.print("[dim]Loading ES bar history (10d / 5m)...[/dim]", end=" ")
        es_cache = _load_es_cache()

        console.print("[dim]Loading institutional context "
                      "(HMM/GEX/sector/macro/COT/breadth/SMH)...[/dim]", end=" ")
        hybrid_ctx = load_hybrid_context()
        gate_mode  = os.environ.get("ISOGENY_ML_GATE", "shadow").lower()
        console.print(f"[{C_GOOD}]✓  hybrid engine — ML_GATE={gate_mode}[/{C_GOOD}]")

    console.print("[dim]Reading news + economic calendar...[/dim]", end=" ")
    session_news = fetch_session_news()
    console.print(f"[{C_GOOD}]✓[/{C_GOOD}]")

    # ── Account summary panel ─────────────────────────────────────────────────
    bal, buf = _load_balance()
    buf_col  = C_GOOD if buf >= 500 else (C_WARN if buf >= 250 else C_BAD)
    floor    = bal - buf

    acct = Table.grid(padding=(0, 3))
    acct.add_column(style="dim", justify="right")
    acct.add_column(style="bold")
    acct.add_row("Balance",  f"[white]${bal:,.2f}[/white]")
    acct.add_row("Buffer",   f"[{buf_col}]${buf:,.2f}[/{buf_col}]")
    acct.add_row("Floor",    f"[dim]${floor:,.2f}[/dim]")
    acct.add_row("Max loss", f"[dim]${buf * 0.15:,.0f}/trade  (15% buffer rule)[/dim]")

    console.print(Panel(
        acct,
        title="[bold white]ACCOUNT[/bold white]",
        border_style="bright_white",
        padding=(0, 2),
    ))
    console.print()

    # Print bot memory status
    print_status()

    # Guard: ensure session_news exists even if fetch above failed
    if "session_news" not in dir():
        session_news = None  # type: ignore

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
            console.print()
            console.rule(
                f"[bold yellow]09:25  MARKET OPENS IN 5 MIN[/bold yellow]  "
                f"[dim]NQ {price:,.1f}  Buffer ${buf:.0f}[/dim]",
                style="yellow"
            )

        # ── 9:30 AM session open brief ────────────────────────────────────
        if h == 9 and m >= 30 and not session_open_done:
            session_open_done = True
            _print_session_open_summary(bar_cache, vix_cache, price, session_news)

        # ── 12:00 PM session end ─────────────────────────────────────────
        if h >= 12 and not warned_end:
            warned_end = True
            alert_session_end()
            console.print()
            console.rule("[bold red]12:00 PM — SESSION OVER  ·  STOP TRADING  ·  CLOSE ALL POSITIONS[/bold red]",
                         style="red")
            console.print()
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
                    console.print()
                    _be_alert(watch["strategy"], watch["direction"], watch["entry"])

        # ── Real-time level proximity — INFO ONLY, no trade instructions ────
        # Only confirmed strategy signals (bar-close engine) generate trades.
        # These just tell you which key level price is near so you stay aware.
        _APPROACH = 8.0
        if price and key_levels and 9 <= h < 12:
            checks = [
                ("ORB HIGH", key_levels.get("orb_high"), "long",  "cyan"),
                ("ORB LOW",  key_levels.get("orb_low"),  "short", "cyan"),
                ("IB HIGH",  key_levels.get("ib_high"),  "long",  "blue"),
                ("IB LOW",   key_levels.get("ib_low"),   "short", "blue"),
                ("VWAP",     key_levels.get("vwap"),     None,    "orange1"),
                ("PDH",      key_levels.get("pdh"),      "short", "orange1"),
                ("PDL",      key_levels.get("pdl"),      "long",  "orange1"),
                ("PMH",      key_levels.get("pmh"),      "short", "yellow"),
                ("PML",      key_levels.get("pml"),      "long",  "yellow"),
            ]
            for name, lvl, direction, col in checks:
                if not lvl:
                    continue
                near = abs(price - lvl) <= _APPROACH
                alert_key = f"NEAR_{name}_{lvl:.0f}"
                if near and alert_key not in level_alerts:
                    level_alerts.add(alert_key)
                    console.print(
                        f"\n  [dim]{now.strftime('%H:%M')}[/dim]  "
                        f"[{col}]{name} {lvl:,.2f}[/{col}]  "
                        f"[dim]price within {abs(price-lvl):.1f}pts — watch for engine signal[/dim]"
                    )

        # ── Live price ticker — suppressed while waiting for user input ──────
        if _pending_confirm or _pending_outcome:
            # Ticker paused — wait for user response, then resume
            time.sleep(0.5)
            continue

        if 9 <= h < 12 and price:
            confirmed = get_confirmed_trades_today()
            age       = feed.age_seconds
            src_tag   = "NQ"
            vix_now   = vix_cache.get(date.today(), 0.0)
            atr_now   = key_levels.get("atr", 0.0)
            _status_bar(price, confirmed, buf, vix_now, atr_now, src_tag, age, now)
            if is_paused()[0]:
                console.print(f"  [bold red]PAUSED[/bold red]", end="\r")

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
                    f"\n[dim]{now.strftime('%H:%M')}[/dim]  "
                    f"[bold red]⏸  PAUSED — {pause_reason}[/bold red]"
                )
                bar_cache = _append_latest(bar_cache)
                key_levels = _compute_levels(bar_cache)
                time.sleep(0.5)
                continue

            if confirmed_today >= 3:
                console.print(
                    f"\n[dim]{now.strftime('%H:%M')}[/dim]  "
                    f"[bold yellow]3 trades confirmed today — daily limit reached[/bold yellow]"
                )
                bar_cache = _append_latest(bar_cache)
                key_levels = _compute_levels(bar_cache)
                time.sleep(0.5)
                continue

            bar_cache = _append_latest(bar_cache)
            if ISOGENY_ENGINE == "hybrid":
                es_cache = _append_latest_es(es_cache)
            fetch_ms  = int((time.monotonic() - t0) * 1000)
            _bar_close_line(now, fetch_ms)

            t1 = time.monotonic()
            try:
                if ISOGENY_ENGINE == "hybrid":
                    today_trades = run_hybrid_today(bar_cache, es_cache, hybrid_ctx)
                else:
                    today_trades = run_quant_today(bar_cache, vix_cache)
                new_trades   = [t for t in today_trades
                                if _signal_key(t) not in seen_signals]
                check_ms     = int((time.monotonic() - t1) * 1000)

                # Filter contradictory signals: enforce direction lock
                filtered_trades = []
                for t in new_trades:
                    if _direction_is_locked(t.direction):
                        console.print(
                            f"\n  [dim]⊘  {t.strategy.upper()} {t.direction.upper()} "
                            f"suppressed — direction lock active ({DIRECTION_LOCK_MINUTES}min)[/dim]"
                        )
                        seen_signals.add(_signal_key(t))  # don't repeat it
                        continue
                    filtered_trades.append(t)

                if filtered_trades:
                    console.print(f"[{C_GOOD}]{len(filtered_trades)} signal(s)  ({check_ms}ms)[/{C_GOOD}]")
                    for t in filtered_trades:
                        seen_signals.add(_signal_key(t))
                        _set_direction_lock(t.direction)

                        # Score / sizing / ML-gate context from trade attributes if available
                        score_val = getattr(t, "score", 0)
                        n_lots    = getattr(t, "n_contracts", 1)
                        ml_proba  = getattr(t, "ml_proba", None)
                        hmm_state = getattr(t, "hmm_state", None)
                        gex_bias  = getattr(t, "gex_bias", None)

                        alert_signal(t.strategy, t.direction, t.entry, t.stop, t.target)
                        _signal_panel(t.strategy, t.direction, t.entry, t.stop, t.target,
                                      score=score_val, n_contracts=n_lots,
                                      ml_proba=ml_proba, hmm_state=hmm_state, gex_bias=gex_bias)

                        # Breakeven watcher
                        risk_pts   = abs(_tick(t.entry) - _tick(t.stop))
                        be_mult    = 2.0 if t.strategy == "orb" else 1.0
                        be_trigger = _tick(
                            (_tick(t.entry) + risk_pts * be_mult) if t.direction == "long"
                            else (_tick(t.entry) - risk_pts * be_mult)
                        )
                        be_watches.append({
                            "strategy":   t.strategy,
                            "direction":  t.direction,
                            "entry":      t.entry,
                            "be_trigger": be_trigger,
                            "notified":   False,
                        })
                        console.print(
                            f"  [dim]T1 alert: move SL to entry when price hits "
                            f"[white]{be_trigger:.1f}[/white][/dim]"
                        )

                        # Log signal to memory
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

                        _confirm_prompt()
                        _pending_confirm = {
                            "signal_id": sig_id,
                            "strategy":  t.strategy,
                            "direction": t.direction,
                            "entry":     t.entry,
                            "stop":      t.stop,
                            "target":    t.target,
                        }
                        break   # only prompt for first signal at once
                else:
                    if not new_trades:
                        console.print(
                            f"[dim]none  ({check_ms}ms · {len(seen_signals)} fired today)[/dim]"
                        )
                    else:
                        console.print(f"[dim]filtered  ({check_ms}ms)[/dim]")

                # Drawdown warning
                _, buf = _load_balance()
                if buf < 300:
                    alert_risk_warning(f"Buffer critical: ${buf:.0f} left!")
                    console.print()
                    console.rule(
                        f"[{C_BAD}]⚠  BUFFER ${buf:.0f} — CONSIDER STOPPING FOR THE DAY[/{C_BAD}]",
                        style=C_BAD
                    )

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
