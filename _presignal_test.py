"""
P0 — Pre-signal validation harness.

Question it answers: if you place a RESTING order at the trigger level (so you
get filled early/at-broker-speed) instead of waiting to enter at the next-bar
open the way the backtest assumes, does your win rate stay the same?

Method: re-run the hybrid backtest, then for every real trade re-simulate the
SAME stop/target but with entry = the resting trigger price, filled from the
signal bar. Compare WR / PnL head-to-head. No live code touched.

Run: python3 _presignal_test.py
"""
from collections import defaultdict
from backtest.hybrid_engine import run_hybrid_backtest, _simulate_trade
from backtest.data_loader import load_nq, label_sessions

PM = {"vwap_bounce_pm", "vwap_pm"}


def summarize(label, rows):
    # rows = list of (pnl, outcome)
    if not rows:
        print(f"{label}: 0"); return
    w = sum(1 for _, o in rows if o == "WIN")
    pnl = sum(p for p, _ in rows)
    print(f"{label:<26} {len(rows):3d} trades | WR {w/len(rows)*100:5.1f}% | PnL ${pnl:+.0f}")


if __name__ == "__main__":
    df = label_sessions(load_nq(interval="5m", period="60d"), interval="5m")
    trades = run_hybrid_backtest(interval="5m", period="60d")
    am = [t for t in trades if t.strategy not in PM]

    cur_all, early_all = [], []
    by_strat = defaultdict(lambda: {"cur": [], "early": []})

    for t in am:
        if t.signal_bar_idx < 0 or t.trigger_price <= 0:
            continue
        # current (as backtested): entry at t.entry
        cur = (t.pnl, t.outcome)
        # early/resting: same stop+target levels, entry at the trigger price,
        # simulated from the signal bar. Same n_contracts so PnL is comparable.
        _, e_pnl, e_out = _simulate_trade(
            df, t.signal_bar_idx, t.direction,
            t.trigger_price, t.stop, t.target,
            n_contracts=t.n_contracts,
        )
        cur_all.append(cur); early_all.append((e_pnl, e_out))
        by_strat[t.strategy]["cur"].append(cur)
        by_strat[t.strategy]["early"].append((e_pnl, e_out))

    print("=" * 64)
    print("PRE-SIGNAL (resting-order fill) vs CURRENT (next-bar-open)")
    print("=" * 64)
    summarize("CURRENT  (backtest)", cur_all)
    summarize("EARLY    (resting fill)", early_all)
    print("-" * 64)
    for s in sorted(by_strat):
        print(f"[{s}]")
        summarize("  current", by_strat[s]["cur"])
        summarize("  early  ", by_strat[s]["early"])
    print("=" * 64)
