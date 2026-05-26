"""
Daily trade check — run this after each session.

  python3 daily_check.py

What it does:
  1. Shows every setup that fired today
  2. Asks "did you take this trade?"
  3. Checks actual price data to determine if target or stop was hit
  4. Logs the trade and updates your account balance
  5. Prints the full dashboard
"""
from __future__ import annotations
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backtest.data_loader import load_nq as load_data
from backtest.quant_engine import run_quant_backtest, QuantTrade
from journal.trade_journal import TradeJournal
from journal.dashboard import print_dashboard
from risk.prop_firm_rules import TradeifyState

EST = ZoneInfo("America/New_York")
MNQ_PER_POINT = 2.0


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nExiting.")
        sys.exit(0)


def _check_outcome(df, signal_bar_idx: int, direction: str,
                   entry: float, stop: float, target: float,
                   max_hour: int = 12) -> tuple[str, float, float]:
    """
    Replay bars after entry to see if target or stop was hit first.
    Returns (outcome, exit_price, pnl_dollars).
    """
    from zoneinfo import ZoneInfo
    EST = ZoneInfo("America/New_York")

    bars_after = df.iloc[signal_bar_idx + 1:]
    for _, row in bars_after.iterrows():
        ts  = row.name.astimezone(EST)
        if ts.hour >= max_hour:
            # Session close
            exit_p = float(row["Open"])
            pnl    = (exit_p - entry if direction == "long" else entry - exit_p) * MNQ_PER_POINT
            return "CLOSED_SESSION", exit_p, round(pnl, 2)

        hi = float(row["High"])
        lo = float(row["Low"])

        if direction == "long":
            if hi >= target:
                pnl = (target - entry) * MNQ_PER_POINT
                return "WIN", target, round(pnl, 2)
            if lo <= stop:
                pnl = (stop - entry) * MNQ_PER_POINT
                return "LOSS", stop, round(pnl, 2)
        else:
            if lo <= target:
                pnl = (entry - target) * MNQ_PER_POINT
                return "WIN", target, round(pnl, 2)
            if hi >= stop:
                pnl = (entry - stop) * MNQ_PER_POINT
                return "LOSS", stop, round(pnl, 2)

    # Never resolved — flat
    last = float(df.iloc[-1]["Close"])
    pnl  = (last - entry if direction == "long" else entry - last) * MNQ_PER_POINT
    return "FLAT", last, round(pnl, 2)


def main() -> None:
    print("\n" + "=" * 60)
    print("  NQ QUANT SYSTEM — Daily Trade Check")
    print(f"  {date.today().strftime('%A, %B %d %Y')}")
    print("=" * 60)

    # Load today's signals (last 2 days to catch today's trades)
    print("\nLoading today's signals...", end=" ", flush=True)
    trades: list[QuantTrade] = run_quant_backtest(interval="5m", period="2d")
    today_str = str(date.today())
    today_trades = [t for t in trades if str(t.date) == today_str]
    print(f"{len(today_trades)} setup(s) found today.")

    if not today_trades:
        print("\n  No setups fired today — nothing to log.")
        _show_dashboard()
        return

    # Load raw price data for outcome checking
    print("Loading price data...", end=" ", flush=True)
    df = load_data(interval="5m", period="2d")
    print("done.\n")

    journal = TradeJournal()
    state   = _rebuild_state(journal)

    for i, t in enumerate(today_trades, 1):
        print(f"─" * 60)
        print(f"  Setup {i}/{len(today_trades)}: {t.strategy.upper().replace('_', ' ')}")
        print(f"  Direction : {t.direction.upper()}")
        print(f"  Entry     : {t.entry:.1f}")
        print(f"  Stop      : {t.stop:.1f}  (risk {abs(t.entry - t.stop):.1f} pts)")
        print(f"  Target    : {t.target:.1f}  (reward {abs(t.target - t.entry):.1f} pts)")
        print(f"  Time      : {t.date}  {getattr(t, 'day_name', '')}")
        print()

        ans = _ask("  Did you take this trade? (y/n/skip): ")
        if ans == "skip" or ans == "s":
            print("  Skipped.\n")
            continue
        if ans not in ("y", "yes"):
            print("  Not taken — not logged.\n")
            continue

        # Check if they can trade (Tradeify rules)
        ok, reason = state.can_open_trade()
        if not ok:
            print(f"\n  ⚠  {reason}")
            print("  Trade not logged (rule violation).\n")
            continue

        # Determine outcome from price data
        max_hour = 16 if "pm" in t.strategy else 12
        outcome, exit_p, pnl = _check_outcome(
            df, t.signal_bar_idx, t.direction,
            t.entry, t.stop, t.target, max_hour=max_hour,
        )

        win = outcome == "WIN"
        result_str = (
            f"[WIN +${pnl:.2f}]" if win else
            f"[LOSS ${pnl:.2f}]" if outcome == "LOSS" else
            f"[{outcome} ${pnl:+.2f}]"
        )
        print(f"\n  Result → {result_str}  exit @ {exit_p:.1f}")

        # Contracts (from bot memory if available)
        contracts = 1
        try:
            from strategy.bot_memory import get_sizing
            contracts = get_sizing()
        except Exception:
            pass

        pnl_scaled = pnl * contracts

        trade_id = journal.log_trade({
            "timestamp":    datetime.now(tz=EST).isoformat(timespec="seconds"),
            "direction":    t.direction,
            "strategy":     t.strategy,
            "entry_price":  t.entry,
            "stop_price":   t.stop,
            "tp1_price":    t.target,
            "exit_price":   exit_p,
            "contracts":    contracts,
            "risk_dollars": abs(t.entry - t.stop) * MNQ_PER_POINT * contracts,
            "pnl_dollars":  pnl_scaled,
            "outcome":      outcome,
            "status":       "CLOSED",
            "vix":          getattr(t, "vix", 0.0),
        })

        state.record_trade(pnl_scaled)

        # Also update bot memory
        try:
            from strategy.bot_memory import log_trade as mem_log
            mem_log(
                strategy=t.strategy, direction=t.direction,
                entry=t.entry, stop=t.stop, target=t.target,
                outcome="WIN" if win else "LOSS",
                pnl=pnl_scaled, contracts=contracts,
                vix=getattr(t, "vix", 0.0),
                day_name=getattr(t, "day_name", ""),
            )
        except Exception:
            pass

        print(f"  Logged (trade #{trade_id}).  Balance: ${state.current_balance:,.2f}\n")

        # Check if limits hit after this trade
        if state.daily_pnl <= -150:
            print("  ⚠  Daily loss limit hit. Stop trading for today.")
            break
        if state.drawdown_buffer < 200:
            print(f"  ⚠  Drawdown buffer low: ${state.drawdown_buffer:.0f} left. Be careful.")

    print("─" * 60)
    print_dashboard(state, journal)


def _rebuild_state(journal: TradeJournal) -> TradeifyState:
    """
    Build state from account.json (real balance) + any trades logged today.
    account.json is the source of truth for your actual Tradeify balance.
    """
    import json
    from pathlib import Path

    acct_path = Path(__file__).parent / "journal" / "account.json"
    if acct_path.exists():
        acct = json.loads(acct_path.read_text())
    else:
        acct = {"starting_balance": 25000.0, "current_balance": 25000.0, "peak_eod_balance": 25000.0}

    state = TradeifyState()
    state.starting_balance    = acct["starting_balance"]
    state.current_balance     = acct["current_balance"]
    state.peak_eod_balance    = acct.get("peak_eod_balance", acct["starting_balance"])
    state.total_realized_pnl  = acct["current_balance"] - acct["starting_balance"]

    # Add any trades logged in today's session on top
    today = str(date.today())
    for t in journal.get_all_trades():
        if t.get("status") != "CLOSED" or t.get("pnl_dollars") is None:
            continue
        if str(t.get("timestamp", ""))[:10] == today:
            pnl = t["pnl_dollars"]
            state.daily_pnl        += pnl
            state.trades_today     += 1
            state.current_balance  += pnl
            state.total_realized_pnl += pnl
    return state


def _show_dashboard() -> None:
    j = TradeJournal()
    print_dashboard(_rebuild_state(j), j)


if __name__ == "__main__":
    main()
