"""
Expanding-window walk-forward validation for meta-labeling models — the
final curve-fitting check before any model is trusted.

Mirrors `backtest.walk_forward`'s WFE methodology (the project's existing
yardstick) but applied to the META-MODEL specifically:

  For each window: retrain on everything up to T, evaluate the trades it
  would gate-approve in [T, T+test_days] (OOS) vs the trades it
  gate-approved during its own training window (IS).

  WFE = OOS edge / IS edge   (edge = avg P&L per gated trade)
    > 80%  exceptional — minimal curve-fitting
    50-80% robust — tradeable
    35-50% borderline — reduce features / loosen the gate
    < 35%  curve-fitted — do NOT deploy

This is slower than the purged-CV used during development (it retrains a
fresh booster per window) — that's the point: it simulates exactly the
retrain-and-deploy cycle the live system would run.

Run with:
    python3 -m ml.evaluation.walk_forward --strategy orb
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

from ml.features import ALL_FEATURES, CATEGORICAL_FEATURES
from ml.training.cv import expanding_walk_forward_splits
from ml.training.train import LGB_PARAMS, _prep_xy, MIN_ROWS_TO_TRAIN, MODEL_DIR

DATA_PATH = Path("ml/data/candidates_10yr.parquet")
PROB_THRESHOLD = 0.55   # the gate threshold being validated


def _persist_wfe(strategy: str, avg_wfe: float | None, verdict: str, n_windows: int) -> None:
    """
    Merge the WFE result into the model's saved metadata JSON so
    `ml.inference.ml_gate_enabled` can require BOTH a real purged-CV AUC edge
    AND a robust walk-forward result before allowing live gating — a model
    can clear the AUC bar on folds that still curve-fit the retrain cycle
    (this is exactly what happened to `va_rule`: AUC=0.63 but WFE=48%,
    including OOS windows where the gate would have lost money it looked
    profitable on in-sample).
    """
    meta_path = MODEL_DIR / f"meta_{strategy}.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text())
    meta["wfe_avg"] = avg_wfe
    meta["wfe_verdict"] = verdict
    meta["wfe_n_windows"] = n_windows
    meta_path.write_text(json.dumps(meta, indent=2))


def _edge(sub: pd.DataFrame, proba: np.ndarray, thr: float) -> dict:
    gated = sub[(sub["would_trade"] == 1) & (proba >= thr)]
    if gated.empty:
        return {"n": 0, "wr": np.nan, "avg_pnl": np.nan}
    return {"n": len(gated), "wr": float(gated["label"].mean() * 100),
            "avg_pnl": float(gated["pnl"].mean())}


def run(strategy: str, n_windows: int = 6, min_train_days: int = 250,
        test_days: int = 60, embargo_days: int = 3, thr: float = PROB_THRESHOLD) -> None:
    df = pd.read_parquet(DATA_PATH)
    sub = df[df["strategy"] == strategy].sort_values("date").reset_index(drop=True)
    if len(sub) < MIN_ROWS_TO_TRAIN:
        print(f"  {strategy}: only {len(sub)} rows — skipping walk-forward (needs {MIN_ROWS_TO_TRAIN}+).")
        return

    splits = expanding_walk_forward_splits(sub, n_windows=n_windows, min_train_days=min_train_days,
                                            test_days=test_days, embargo_days=embargo_days)
    if not splits:
        print(f"  {strategy}: not enough distinct days for expanding walk-forward "
              f"(have {sub['date'].nunique()}, need >= {min_train_days + embargo_days + test_days}).")
        return

    print(f"\n{'='*86}\n  WALK-FORWARD — {strategy}  (gate threshold P(win) >= {thr:.2f})")
    print(f"  {len(splits)} windows | min_train={min_train_days}d  test={test_days}d  embargo={embargo_days}d")
    print(f"{'='*86}")
    print(f"  {'Window':<24} {'IS n/WR/$avg':<22} {'OOS n/WR/$avg':<22} {'WFE':>8}")
    print(f"  {'-'*78}")

    wfes = []
    for i, (tr_idx, te_idx) in enumerate(splits, 1):
        train_sub = sub.iloc[tr_idx]
        test_sub  = sub.iloc[te_idx]
        if train_sub["label"].nunique() < 2:
            continue

        X_tr, y_tr = _prep_xy(train_sub)
        model = lgb.LGBMClassifier(**{**LGB_PARAMS, "n_estimators": 200})
        model.fit(X_tr, y_tr, categorical_feature=[c for c in CATEGORICAL_FEATURES if c in X_tr.columns])

        X_is, _ = _prep_xy(train_sub)
        X_oos, _ = _prep_xy(test_sub)
        is_proba  = model.predict_proba(X_is)[:, 1]
        oos_proba = model.predict_proba(X_oos)[:, 1]

        is_edge  = _edge(train_sub, is_proba, thr)
        oos_edge = _edge(test_sub, oos_proba, thr)

        wfe = (oos_edge["avg_pnl"] / is_edge["avg_pnl"] * 100
               if is_edge["avg_pnl"] not in (None, 0) and is_edge["avg_pnl"] == is_edge["avg_pnl"]
               and is_edge["avg_pnl"] > 0 else float("nan"))
        if wfe == wfe:
            wfes.append(wfe)

        win_label = f"{train_sub['date'].iloc[-1]} -> {test_sub['date'].iloc[-1]}"
        is_str  = f"{is_edge['n']}/{is_edge['wr']:.0f}%/${is_edge['avg_pnl']:+.1f}" if is_edge["n"] else "—"
        oos_str = f"{oos_edge['n']}/{oos_edge['wr']:.0f}%/${oos_edge['avg_pnl']:+.1f}" if oos_edge["n"] else "—"
        wfe_str = f"{wfe:.0f}%" if wfe == wfe else "—"
        print(f"  {win_label:<24} {is_str:<22} {oos_str:<22} {wfe_str:>8}")

    if wfes:
        avg_wfe = float(np.mean(wfes))
        if avg_wfe >= 80:
            verdict = "EXCEPTIONAL — minimal curve-fitting."
        elif avg_wfe >= 50:
            verdict = "ROBUST — tradeable."
        elif avg_wfe >= 35:
            verdict = "BORDERLINE — reduce feature count / loosen gate."
        else:
            verdict = "CURVE-FITTED — do NOT deploy live."
        print(f"\n  Average WFE: {avg_wfe:.0f}%   Verdict: {verdict}")
        _persist_wfe(strategy, avg_wfe, verdict, len(wfes))
    else:
        print(f"\n  Not enough windows with positive IS edge to compute WFE — "
              f"likely means the model (or even the rule-based gate) has no "
              f"detectable in-sample edge here either.")
        _persist_wfe(strategy, None, "no valid windows — insufficient evidence to deploy live", 0)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", type=str, required=True)
    p.add_argument("--threshold", type=float, default=PROB_THRESHOLD)
    args = p.parse_args()
    run(args.strategy, thr=args.threshold)


if __name__ == "__main__":
    main()
