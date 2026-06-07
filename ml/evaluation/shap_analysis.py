"""
SHAP interpretability check — the mandatory pre-deployment sanity gate.

A model can show a great OOS AUC purely by exploiting a spurious correlation
(e.g. "Tuesdays in March" or a feature that's a leaked proxy for the label).
Before trusting any meta-labeling model with real money, its TOP features
must make CAUSAL sense to a human who understands the market — not just
statistical sense to a gradient booster.

This script:
  1. Loads a trained per-strategy model + its held-out data
  2. Computes SHAP values (TreeExplainer — exact & fast for LightGBM)
  3. Ranks features by mean |SHAP| (global importance)
  4. Reports the DIRECTION of each top feature's effect (does a high value
     push the prediction toward WIN or LOSS?) so you can eyeball whether
     that direction matches market intuition

Run with:
    python3 -m ml.evaluation.shap_analysis --strategy orb
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
import shap

from ml.features import ALL_FEATURES, CATEGORICAL_FEATURES

MODEL_DIR = Path("ml/saved_models")
DATA_PATH = Path("ml/data/candidates_10yr.parquet")


def _load(strategy: str):
    model_path = MODEL_DIR / f"meta_{strategy}.txt"
    meta_path  = MODEL_DIR / f"meta_{strategy}.json"
    if not model_path.exists():
        raise FileNotFoundError(f"No saved model for '{strategy}' — run training first ({model_path})")
    booster = lgb.Booster(model_file=str(model_path))
    meta = json.loads(meta_path.read_text())
    return booster, meta


def _prep_X(df: pd.DataFrame) -> pd.DataFrame:
    X = df[ALL_FEATURES].copy()
    for c in CATEGORICAL_FEATURES:
        X[c] = X[c].astype("category")
    return X


def analyze(strategy: str, top_n: int = 20) -> pd.DataFrame:
    booster, meta = _load(strategy)
    df = pd.read_parquet(DATA_PATH)
    sub = df[df["strategy"] == strategy].reset_index(drop=True)
    X = _prep_X(sub)

    print(f"\n{'='*72}\n  SHAP analysis — {strategy}  (n={len(sub)}, "
          f"OOS AUC={meta.get('avg_oos_auc', float('nan')):.3f})\n{'='*72}")

    explainer = shap.TreeExplainer(booster)
    sv = explainer.shap_values(X)
    # LightGBM binary booster -> single array of shape (n, n_features) for class "1" (WIN)
    shap_vals = sv[1] if isinstance(sv, list) else sv

    mean_abs = np.abs(shap_vals).mean(axis=0)
    # direction: correlation between the raw feature value and its SHAP contribution
    # (only meaningful for numeric features; categorical -> show per-level mean SHAP)
    rows = []
    for j, feat in enumerate(ALL_FEATURES):
        contrib = shap_vals[:, j]
        if feat in CATEGORICAL_FEATURES:
            # show the level with the most positive and most negative mean SHAP
            tmp = pd.DataFrame({"level": X[feat].astype(str), "shap": contrib})
            grp = tmp.groupby("level")["shap"].mean().sort_values()
            if len(grp) >= 2:
                direction = f"'{grp.index[-1]}'(+{grp.iloc[-1]:.3f}) vs '{grp.index[0]}'({grp.iloc[0]:.3f})"
            else:
                direction = "single level"
            corr = np.nan
        else:
            vals = pd.to_numeric(X[feat], errors="coerce")
            mask = vals.notna() & np.isfinite(contrib)
            corr = float(np.corrcoef(vals[mask], contrib[mask])[0, 1]) if mask.sum() > 5 else np.nan
            direction = ("higher value -> WIN" if corr > 0.05 else
                         "higher value -> LOSS" if corr < -0.05 else "no clear monotonic direction")
        rows.append({"feature": feat, "mean_abs_shap": float(mean_abs[j]),
                     "corr_with_shap": corr, "direction": direction})

    out = pd.DataFrame(rows).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
    print(f"\n  Top {top_n} features by mean |SHAP| (global importance):\n")
    for _, r in out.head(top_n).iterrows():
        corr_str = f"r={r['corr_with_shap']:+.2f}" if r["corr_with_shap"] == r["corr_with_shap"] else "      "
        print(f"    {r['feature']:<24} |SHAP|={r['mean_abs_shap']:.4f}  {corr_str}   {r['direction']}")

    print(f"\n  >>> Eyeball check: do these top features have an obvious causal story?")
    print(f"      (e.g. 'rvol high -> WIN' for a breakout = institutions confirming the move;")
    print(f"       'score high -> WIN' = the rule-based scorer already captures real edge;")
    print(f"       a date/index-like feature dominating = LEAKAGE — investigate immediately.)")

    out_path = MODEL_DIR / f"shap_{strategy}.csv"
    out.to_csv(out_path, index=False)
    print(f"\n  Full ranking -> {out_path}")
    return out


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", type=str, required=True)
    p.add_argument("--top", type=int, default=20)
    args = p.parse_args()
    analyze(args.strategy, top_n=args.top)


if __name__ == "__main__":
    main()
