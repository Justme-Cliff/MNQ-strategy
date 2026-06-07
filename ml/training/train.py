"""
Train per-strategy meta-labeling LightGBM classifiers.

Meta-labeling (López de Prado): the rule-based detectors (`detect_orb`,
`detect_ib`, ...) remain the PRIMARY model / alpha source — they decide
direction, entry, stop, target. This SECONDARY model only answers one
binary question per candidate signal: "will the primary model's call be
a winner — take it, or skip it?"

Why per-strategy models (not one global model): each strategy has a
different edge mechanism (breakout vs mean-reversion vs value-area), so
the same feature can mean opposite things (e.g. high RVOL confirms a
breakout but signals exhaustion for a fade). One LightGBM per strategy
with `strategy` excluded from its own feature set keeps the signal clean
and each model small enough for its sample size.

Hyperparameters are deliberately conservative for small financial datasets
(typically a few hundred to ~2-3k rows per strategy over 10 years):
  max_depth=4, num_leaves=12, min_child_samples=40, learning_rate=0.02,
  n_estimators=300 (with early stopping), subsample=0.7, colsample_bytree=0.6,
  reg_alpha=0.3, reg_lambda=1.0
This is a high-bias / low-variance config — we'd rather under-fit than
memorize 10 years of noise into a 600-row dataset.

Run with:
    python3 -m ml.training.train --strategy orb
    python3 -m ml.training.train --all
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

from ml.features import NUMERIC_FEATURES, CATEGORICAL_FEATURES, ALL_FEATURES
from ml.training.cv import purged_kfold_splits

DATA_PATH  = Path("ml/data/candidates_10yr.parquet")
MODEL_DIR  = Path("ml/saved_models")
MIN_ROWS_TO_TRAIN = 150   # below this, "train a model" is closer to memorizing noise

LGB_PARAMS = dict(
    objective="binary",
    metric="binary_logloss",
    max_depth=4,
    num_leaves=12,
    min_child_samples=40,
    learning_rate=0.02,
    n_estimators=300,
    subsample=0.7,
    subsample_freq=1,
    colsample_bytree=0.6,
    reg_alpha=0.3,
    reg_lambda=1.0,
    random_state=42,
    verbose=-1,
)


def _prep_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    X = df[ALL_FEATURES].copy()
    for c in CATEGORICAL_FEATURES:
        X[c] = X[c].astype("category")
    y = df["label"].astype(int)
    return X, y


def _fit_fold(X_tr, y_tr, X_va=None, y_va=None) -> lgb.LGBMClassifier:
    """
    Fit one fold. If a clean validation slice is available (carved from the
    training block — never the test fold), use it for early stopping. If not,
    fall back to a fixed, smaller `n_estimators` rather than letting early
    stopping peek at the test fold (that would leak test info into model
    selection and inflate the OOS metrics we're trying to measure honestly).
    """
    if X_va is not None and y_va is not None and y_va.nunique() >= 2:
        model = lgb.LGBMClassifier(**LGB_PARAMS)
        model.fit(
            X_tr, y_tr,
            eval_set=[(X_va, y_va)],
            eval_metric="binary_logloss",
            categorical_feature=[c for c in CATEGORICAL_FEATURES if c in X_tr.columns],
            callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
        )
    else:
        model = lgb.LGBMClassifier(**{**LGB_PARAMS, "n_estimators": 120})
        model.fit(X_tr, y_tr,
                  categorical_feature=[c for c in CATEGORICAL_FEATURES if c in X_tr.columns])
    return model


def train_strategy(strategy: str, df: pd.DataFrame, n_splits: int = 5,
                    embargo_days: int = 3, save: bool = True) -> dict:
    sub = df[df["strategy"] == strategy].sort_values("date").reset_index(drop=True)
    n = len(sub)
    print(f"\n{'='*72}\n  {strategy.upper()}  —  {n} candidate signals "
          f"(WR={sub['label'].mean()*100:.1f}%, would_trade={sub['would_trade'].sum()})")
    print("=" * 72)

    if n < MIN_ROWS_TO_TRAIN:
        print(f"  SKIP — fewer than {MIN_ROWS_TO_TRAIN} rows. Not enough data to "
              f"train without massively overfitting. Needs more history or a "
              f"relaxed capture threshold.")
        return {"strategy": strategy, "trained": False, "n": n, "reason": "insufficient_data"}

    splits = purged_kfold_splits(sub, n_splits=n_splits, embargo_days=embargo_days)
    if len(splits) < 2:
        print("  SKIP — not enough distinct trading days for purged CV splits.")
        return {"strategy": strategy, "trained": False, "n": n, "reason": "insufficient_days"}

    fold_metrics = []
    oos_proba = np.full(n, np.nan)

    for i, (tr_idx, te_idx) in enumerate(splits, 1):
        X_tr, y_tr = _prep_xy(sub.iloc[tr_idx])
        X_te, y_te = _prep_xy(sub.iloc[te_idx])

        if y_tr.nunique() < 2 or y_te.nunique() < 2:
            print(f"  Fold {i}: SKIP (single-class fold — too little data for this slice)")
            continue

        # carve a small validation slice off the END of the training block for
        # early stopping (still purged/embargoed — never touches the test fold)
        val_cut = max(int(len(tr_idx) * 0.85), len(tr_idx) - 60)
        tr_sub_idx, va_idx = tr_idx[:val_cut], tr_idx[val_cut:]

        X_tr_fit, y_tr_fit = _prep_xy(sub.iloc[tr_sub_idx])
        if len(va_idx) >= 20 and pd.Series(sub.iloc[va_idx]["label"]).nunique() >= 2:
            X_va, y_va = _prep_xy(sub.iloc[va_idx])
        else:
            X_va = y_va = None  # not enough for a clean ES slice -> fixed n_estimators (see _fit_fold)

        model = _fit_fold(X_tr_fit, y_tr_fit, X_va, y_va)
        proba = model.predict_proba(X_te)[:, 1]
        oos_proba[te_idx] = proba

        try:
            auc = roc_auc_score(y_te, proba)
        except ValueError:
            auc = float("nan")
        brier = brier_score_loss(y_te, proba)
        base_rate = y_te.mean()

        fold_metrics.append({"fold": i, "n_train": len(tr_idx), "n_test": len(te_idx),
                             "test_wr": float(base_rate), "auc": float(auc), "brier": float(brier)})
        print(f"  Fold {i}: train={len(tr_idx):>4}  test={len(te_idx):>3}  "
              f"test_WR={base_rate*100:5.1f}%  AUC={auc:.3f}  Brier={brier:.3f}")

    valid = [m for m in fold_metrics if m["auc"] == m["auc"]]
    if not valid:
        print("  No valid folds (all single-class). Cannot evaluate.")
        return {"strategy": strategy, "trained": False, "n": n, "reason": "no_valid_folds"}

    avg_auc   = float(np.mean([m["auc"] for m in valid]))
    avg_brier = float(np.mean([m["brier"] for m in valid]))
    base_rate = float(sub["label"].mean())
    # naive baseline = always predict the base rate -> Brier of a constant predictor
    naive_brier = float(np.mean((sub["label"] - base_rate) ** 2))

    print(f"\n  OOS summary: AUC={avg_auc:.3f} (0.5=random)  "
          f"Brier={avg_brier:.3f} (naive-constant={naive_brier:.3f}, lower=better)")
    if avg_auc > 0.55:
        verdict = "model adds signal — proceed to SHAP + threshold tuning"
    elif avg_auc > 0.52:
        verdict = "weak edge — usable as a soft filter only, validate carefully"
    else:
        verdict = "no detectable edge — meta-model is not worth deploying for this strategy"
    print(f"  Verdict: {verdict}")

    # ── Final model: train on ALL data (for deployment), embargo the most
    #    recent `embargo_days` only as a formality (no test fold to protect here —
    #    OOS performance was already measured honestly above) ──
    X_all, y_all = _prep_xy(sub)
    final_model = lgb.LGBMClassifier(**{**LGB_PARAMS, "n_estimators": 250})
    final_model.fit(X_all, y_all,
                    categorical_feature=[c for c in CATEGORICAL_FEATURES if c in X_all.columns])

    result = {
        "strategy": strategy,
        "trained": True,
        "n": n,
        "base_rate": base_rate,
        "fold_metrics": fold_metrics,
        "avg_auc": avg_auc,
        "avg_brier": avg_brier,
        "naive_brier": naive_brier,
        "verdict": verdict,
    }

    if save:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        model_path = MODEL_DIR / f"meta_{strategy}.txt"
        final_model.booster_.save_model(str(model_path))
        meta_path = MODEL_DIR / f"meta_{strategy}.json"
        with open(meta_path, "w") as f:
            json.dump({
                "strategy": strategy,
                "n_train_rows": n,
                "base_rate": base_rate,
                "avg_oos_auc": avg_auc,
                "avg_oos_brier": avg_brier,
                "naive_brier": naive_brier,
                "verdict": verdict,
                "features": ALL_FEATURES,
                "categorical_features": CATEGORICAL_FEATURES,
                "lgb_params": {k: v for k, v in LGB_PARAMS.items()},
            }, f, indent=2)
        print(f"  Saved -> {model_path}  +  {meta_path}")

    # stash OOS predictions for downstream backtest comparison / threshold tuning
    sub_out = sub[["date", "strategy", "direction", "would_trade", "score", "label", "pnl", "rr_realized"]].copy()
    sub_out["oos_proba"] = oos_proba
    result["oos_predictions"] = sub_out
    return result


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", type=str, default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--data", type=str, default=str(DATA_PATH))
    args = p.parse_args()

    df = pd.read_parquet(args.data)
    print(f"[TRAIN] Loaded {len(df):,} candidates from {args.data}")
    print(f"[TRAIN] Strategies: {df['strategy'].value_counts().to_dict()}")

    strategies = [args.strategy] if args.strategy else sorted(df["strategy"].unique())
    if not args.strategy and not args.all:
        print("[TRAIN] Pass --strategy <name> or --all")
        return

    results = []
    oos_frames = []
    for strat in strategies:
        r = train_strategy(strat, df)
        results.append({k: v for k, v in r.items() if k != "oos_predictions"})
        if r.get("trained"):
            oos_frames.append(r["oos_predictions"])

    summary_path = MODEL_DIR / "training_summary.json"
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[TRAIN] Summary -> {summary_path}")

    if oos_frames:
        oos_all = pd.concat(oos_frames, ignore_index=True)
        oos_path = Path("ml/data/oos_predictions.parquet")
        oos_all.to_parquet(oos_path, index=False)
        print(f"[TRAIN] OOS predictions (for backtest comparison) -> {oos_path}")


if __name__ == "__main__":
    main()
