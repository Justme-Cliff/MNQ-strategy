"""
Compare rules-only baseline vs ML-gated hybrid — using OOS predictions only.

This is the question that actually matters: "does adding the meta-model make
money the rule-based system already captured better, worse, or about the same?"

Critically, this uses ONLY out-of-sample predictions (`oos_proba` from the
purged-CV folds in `ml.training.train`) — never in-sample predictions, which
would trivially "improve" everything by having memorized the answers.

Two scenarios are compared on the SAME OOS rows:
  BASELINE   = what the rule-based system already does: take every signal
               with `would_trade == 1` (score > threshold, not hard-blocked)
  ML-GATED   = take a signal only if would_trade == 1 AND meta-model's
               P(win) clears a chosen probability threshold

Sweeping the threshold shows the precision/coverage trade-off: a stricter
gate trades fewer times but (if the model has real edge) at a higher win rate
and better $/trade — the entire point of meta-labeling is improving the bet
sizing / selectivity of an already-profitable primary model, NOT replacing it.

Run with:
    python3 -m ml.evaluation.compare_backtest --strategy orb
    python3 -m ml.evaluation.compare_backtest --all
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OOS_PATH = Path("ml/data/oos_predictions.parquet")
MNQ_PER_POINT = 2.0


def _stats(sub: pd.DataFrame) -> dict:
    if sub.empty:
        return {"n": 0, "wr": 0.0, "pnl": 0.0, "avg_pnl": 0.0, "max_dd": 0.0}
    wins = sub["label"].sum()
    pnl  = sub["pnl"].sum()
    running = peak = max_dd = 0.0
    for p in sub.sort_values("date")["pnl"]:
        running += p
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    return {
        "n": len(sub), "wr": wins / len(sub) * 100, "pnl": float(pnl),
        "avg_pnl": float(pnl / len(sub)), "max_dd": float(max_dd),
    }


def compare(strategy: str, thresholds=(0.50, 0.55, 0.60, 0.65, 0.70)) -> pd.DataFrame:
    df = pd.read_parquet(OOS_PATH)
    sub = df[(df["strategy"] == strategy) & df["oos_proba"].notna()].copy()
    if sub.empty:
        print(f"  No OOS predictions for '{strategy}' — train it first.")
        return pd.DataFrame()

    print(f"\n{'='*86}\n  {strategy.upper()}  —  OOS comparison  (n={len(sub)} candidates with OOS predictions)")
    print(f"{'='*86}")

    baseline = sub[sub["would_trade"] == 1]
    bs = _stats(baseline)
    print(f"\n  {'Scenario':<32} {'Trades':>7} {'WR':>7} {'Net P&L':>10} {'$/trade':>9} {'MaxDD':>8}")
    print(f"  {'-'*72}")
    print(f"  {'BASELINE (rules only)':<32} {bs['n']:>7} {bs['wr']:>6.1f}% "
          f"${bs['pnl']:>+8,.0f} ${bs['avg_pnl']:>+7.2f} ${bs['max_dd']:>7,.0f}")

    rows = [{"scenario": "baseline_rules_only", **bs}]
    for thr in thresholds:
        gated = baseline[baseline["oos_proba"] >= thr]
        gs = _stats(gated)
        tag = f"ML-gated  (P(win)>={thr:.2f})"
        print(f"  {tag:<32} {gs['n']:>7} {gs['wr']:>6.1f}% "
              f"${gs['pnl']:>+8,.0f} ${gs['avg_pnl']:>+7.2f} ${gs['max_dd']:>7,.0f}")
        rows.append({"scenario": f"ml_gated_{thr:.2f}", "threshold": thr, **gs})

        # Also show: ML gate APPLIED TO EVERYTHING (incl. would_trade==0 near-misses)
        # -> can the model "rescue" good setups the rule-based score wrongly skipped?
        rescued = sub[(sub["would_trade"] == 0) & (sub["oos_proba"] >= thr)]
        if len(rescued):
            rs = _stats(rescued)
            print(f"      ↳ rescued near-misses (rule said skip, ML says P>={thr:.2f}): "
                  f"{rs['n']} trades, WR={rs['wr']:.1f}%, P&L=${rs['pnl']:+,.0f}")

    out = pd.DataFrame(rows)
    if bs["n"] > 0 and bs["pnl"] != 0:
        best = out[out["scenario"].str.startswith("ml_gated")].sort_values("pnl", ascending=False)
        if not best.empty:
            top = best.iloc[0]
            verdict = ("IMPROVES on baseline" if top["pnl"] > bs["pnl"] and top["wr"] > bs["wr"]
                       else "trades fewer but doesn't clearly beat baseline P&L"
                       if top["pnl"] <= bs["pnl"] else "mixed — higher WR, check $/trade and sample size")
            print(f"\n  Best ML threshold: {top['scenario']}  ->  {verdict}")
    return out


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", type=str, default=None)
    p.add_argument("--all", action="store_true")
    args = p.parse_args()

    if not OOS_PATH.exists():
        print(f"  {OOS_PATH} not found — run `python3 -m ml.training.train --all` first.")
        return

    df = pd.read_parquet(OOS_PATH)
    strategies = [args.strategy] if args.strategy else sorted(df["strategy"].unique())
    if not args.strategy and not args.all:
        print("Pass --strategy <name> or --all")
        return
    for s in strategies:
        compare(s)


if __name__ == "__main__":
    main()
