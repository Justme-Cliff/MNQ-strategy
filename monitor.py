"""
Live session monitor — run from 9:20 AM ET.

  python3 monitor.py

Speed breakdown:
  - fast_feed.py:  NQ price updated every 0.5s via fast_info.last_price (real-time)
  - Bar cache:     Full history loaded ONCE on startup (~2-3s), then only the
                   latest bar is fetched on each check (~0.1s)
  - Signal check:  Runs on bar close, completes in <0.5s total
  - Notification:  Fires within 2-3 seconds of the bar closing
  - Entry window:  You then have the full next 5-min bar (~4min 57sec) to get in

Timeline:
  9:20 AM  → start monitor (loads bar cache)
  9:25 AM  → popup: "Market opens in 5 min"
  9:30 AM  → session starts
  each 5m  → bar closes → append latest bar → run signals → popup if new
  12:00 PM → popup: "Session over"
"""
from __future__ import annotations
import time
import json
from datetime import datetime, date
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

EST       = ZoneInfo("America/New_York")
console   = Console()
ACCT_PATH = Path(__file__).parent / "journal" / "account.json"
TICKER    = yf.Ticker("NQ=F")


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
    return f"{t.date}-{t.strategy}-{t.direction}-{round(t.entry, 1)}"


def _bar_minute(dt: datetime) -> int:
    return (dt.minute // 5) * 5


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

    return levels


def _fetch_latest_bars() -> pd.DataFrame:
    """Fetch only the most recent bars — fast (~80ms)."""
    df = TICKER.history(period="2d", interval="5m", auto_adjust=True)
    return df.tail(10)


def _load_bar_cache() -> pd.DataFrame:
    """Full history load done once on startup — gives ATR/EMA enough context."""
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
    """Append fresh bars, deduplicate — keeps cache current without re-downloading."""
    latest = _fetch_latest_bars()
    # Align timezone: cache is UTC, raw yfinance bars are ET
    if latest.index.tz is not None and str(latest.index.tz) != "UTC":
        latest = latest.copy()
        latest.index = latest.index.tz_convert("UTC")
    combined = pd.concat([cache, latest])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


# ── Main monitor loop ─────────────────────────────────────────────────────────

def run_monitor():
    feed = get_feed()

    console.print(Panel(
        "[bold cyan]NQ Quant System — Live Monitor[/bold cyan]\n"
        "[dim]Real-time price every 0.5s · Signal check on each 5-min bar close (<0.5s)[/dim]",
        border_style="cyan"
    ))

    # Show which feed is active
    from yahoo_ws_feed import YahooWsFeed
    if isinstance(feed, YahooWsFeed):
        feed_name = "[bold green]Yahoo WS ^NDX + basis (real-time, ~$2-5 approx)[/bold green]"
    else:
        feed_name = "[yellow]yfinance (15-min delayed)[/yellow]"
    console.print(f"Price feed: {feed_name}")

    # Wait for first price
    console.print("Connecting...", end=" ")
    for _ in range(20):
        if feed.price:
            break
        time.sleep(0.5)
    console.print(f"[green]NQ ${feed.price:,.1f}[/green]")

    # Load bar history + VIX once at startup
    bar_cache = _load_bar_cache()
    vix_cache = _load_vix_cache()

    bal, buf = _load_balance()
    buf_col  = "red" if buf < 300 else ("yellow" if buf < 500 else "green")
    console.print(
        f"Balance [bold]${bal:,.2f}[/bold]  "
        f"Buffer [{buf_col}]${buf:.0f}[/{buf_col}]  "
        f"Floor ${bal - buf:,.0f}\n"
    )

    seen_signals:  set[str] = set()
    be_watches:    list     = []   # tracks open signals for breakeven alerts
    warned_start            = False
    warned_end              = False
    last_bar_min: int       = -1
    key_levels:   dict      = _compute_levels(bar_cache)
    level_alerts: set[str]  = set()   # level crossings already notified

    while True:
        now   = _now()
        h, m  = now.hour, now.minute
        price = feed.price or 0.0

        # ── 9:25 AM pre-market warning ────────────────────────────────────
        if h == 9 and m == 25 and not warned_start:
            warned_start = True
            bal, buf = _load_balance()
            alert_session_start()
            console.print(
                f"\n[yellow bold]09:25[/yellow bold]  Market opens in 5 min  "
                f"NQ ${price:,.1f}  Buffer ${buf:.0f}"
            )

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

        # ── Real-time level crossing alerts (fires mid-bar, before bar close) ──
        if price and key_levels and 9 <= h < 12:
            checks = [
                ("ORB HIGH", key_levels.get("orb_high"), "long",  lambda p, l: p >= l),
                ("ORB LOW",  key_levels.get("orb_low"),  "short", lambda p, l: p <= l),
                ("IB HIGH",  key_levels.get("ib_high"),  "long",  lambda p, l: p >= l),
                ("IB LOW",   key_levels.get("ib_low"),   "short", lambda p, l: p <= l),
            ]
            for name, lvl, direction, test in checks:
                if not lvl or not test(price, lvl):
                    continue
                key = f"{name}_{lvl:.0f}"
                if key in level_alerts:
                    continue
                level_alerts.add(key)
                side = "[green]LONG ▲[/green]" if direction == "long" else "[red]SHORT ▼[/red]"
                console.print(
                    f"\n  [bold yellow]⚡ {name} {lvl:.1f} CROSSED → {side}[/bold yellow]  "
                    f"[dim]signal likely on next bar close — get ready[/dim]"
                )
                alert_warning(name, f"Price crossed {lvl:.1f} → {direction.upper()} setup forming")

        # ── Live price ticker (overwrites same line) ───────────────────────
        if 9 <= h < 12 and price:
            age     = feed.age_seconds
            stale   = "[red]STALE[/red]" if age > 10 else ""
            console.print(
                f"[dim]{now.strftime('%H:%M:%S')}[/dim]  "
                f"[bold]${price:,.1f}[/bold]  {stale}",
                end="\r"
            )

        # ── Bar close check ───────────────────────────────────────────────
        cur_bar = _bar_minute(now)
        if cur_bar != last_bar_min and h >= 9 and h < 12:
            last_bar_min = cur_bar
            t0 = time.monotonic()
            console.print()

            # Append only the latest bars — fast
            bar_cache = _append_latest(bar_cache)
            fetch_ms  = int((time.monotonic() - t0) * 1000)

            console.print(
                f"[dim]{now.strftime('%H:%M')}[/dim]  "
                f"Bar closed · fetched in {fetch_ms}ms · checking signals...",
                end=" "            )

            t1 = time.monotonic()
            try:
                today_trades = run_quant_today(bar_cache, vix_cache)
                new_trades   = [t for t in today_trades
                                if _signal_key(t) not in seen_signals]
                check_ms     = int((time.monotonic() - t1) * 1000)

                if new_trades:
                    console.print(f"[bold green]{len(new_trades)} SIGNAL(S)! ({check_ms}ms)[/bold green]")
                    for t in new_trades:
                        seen_signals.add(_signal_key(t))
                        alert_signal(t.strategy, t.direction, t.entry, t.stop, t.target)
                        side = "[green]LONG ▲[/green]" if t.direction == "long" else "[red]SHORT ▼[/red]"
                        console.print(
                            f"  [bold white]{t.strategy.upper().replace('_',' '):<22}[/bold white] "
                            f"{side}  E:[bold]{t.entry:.1f}[/bold]  "
                            f"S:{t.stop:.1f}  T:{t.target:.1f}"
                        )
                        console.print(
                            f"  [dim]Enter next bar open · "
                            f"~{5 - now.second//60} min window[/dim]"
                        )
                        # Register breakeven watcher for this signal
                        risk_pts = abs(t.entry - t.stop)
                        be_mult  = 2.0 if t.strategy == "orb" else 1.0
                        if t.direction == "long":
                            be_trigger = t.entry + risk_pts * be_mult
                        else:
                            be_trigger = t.entry - risk_pts * be_mult
                        be_watches.append({
                            "strategy":   t.strategy,
                            "direction":  t.direction,
                            "entry":      t.entry,
                            "be_trigger": be_trigger,
                            "notified":   False,
                        })
                        console.print(
                            f"  [dim]BE alert set: move SL → {t.entry:.1f} "
                            f"when price hits {be_trigger:.1f}[/dim]"
                        )
                else:
                    console.print(f"[dim]none ({check_ms}ms · {len(seen_signals)} fired today)[/dim]")

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
