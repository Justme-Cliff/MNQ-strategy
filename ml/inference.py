"""
Live / shadow-mode inference for the meta-labeling gate.

Loads saved per-strategy LightGBM boosters once (lazy + cached) and scores
a single candidate signal at decision time using the SAME `build_feature_dict`
the training data was generated with — guaranteeing feature parity between
train and serve.

Usage (from `hybrid_engine._try_hybrid` or a shadow-mode wrapper around it):

    from ml.inference import score_candidate, ml_gate_enabled

    p_win = score_candidate(
        strategy, sig, signal_bar_idx=sig.signal_bar_idx, local_pos=local_pos,
        df=df, today_df=today_df, today=today, vix=vix, vix3m=vix3m, vvix=vvix,
        market=market, hmm=hmm, gex=gex, tsmom=tsmom, sector=sector, macro=macro,
        nq_es_spread=nq_es_spread, occ=occ, cot=cot, breadth=breadth, smh_sig=smh_sig,
        har=har, stop_mult=stop_mult, score=score, breakdown=breakdown,
        risk_pts=risk_pts, reward_pts=reward_pts, rr_planned=rr_planned,
    )
    # p_win is None if no trained/validated model exists for this strategy
    # (meta-gate degrades to a no-op — the rule-based system is untouched)

`ml_gate_enabled(strategy)` checks both that a model file exists AND that its
saved validation verdict cleared the bar (avg_oos_auc > 0.55) — models that
showed no real edge are loaded for shadow-mode logging/comparison only and
never allowed to actually gate a trade.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import lightgbm as lgb

from ml.features import ALL_FEATURES, CATEGORICAL_FEATURES, build_feature_dict

MODEL_DIR = Path("ml/saved_models")
MIN_DEPLOYABLE_AUC = 0.55   # below this, the model showed no real edge — never gates
MIN_DEPLOYABLE_WFE = 50.0   # walk-forward efficiency floor ("ROBUST" per plan §18 verdict scale)


@lru_cache(maxsize=None)
def _load(strategy: str) -> Optional[tuple[lgb.Booster, dict]]:
    model_path = MODEL_DIR / f"meta_{strategy}.txt"
    meta_path  = MODEL_DIR / f"meta_{strategy}.json"
    if not (model_path.exists() and meta_path.exists()):
        return None
    try:
        booster = lgb.Booster(model_file=str(model_path))
        meta = json.loads(meta_path.read_text())
        return booster, meta
    except Exception:
        return None


def model_available(strategy: str) -> bool:
    return _load(strategy) is not None


def ml_gate_enabled(strategy: str) -> bool:
    """
    True only if a model exists AND clears BOTH validation bars:
      1. purged-CV OOS AUC > MIN_DEPLOYABLE_AUC (real predictive edge, not noise)
      2. expanding walk-forward WFE >= MIN_DEPLOYABLE_WFE (the edge survives the
         actual retrain-and-deploy cycle, not just one fixed CV split)

    AUC alone is not sufficient — `va_rule` cleared AUC=0.63 but its WFE was
    only 48% with two OOS windows where the gate would have LOST money on
    setups that looked profitable in-sample (textbook curve-fitting that a
    single purged-CV pass doesn't catch). Requiring both keeps strategies like
    that in shadow-mode-only (still scored/logged for ongoing comparison, but
    never allowed to filter a live trade) until they earn their way in.
    """
    loaded = _load(strategy)
    if loaded is None:
        return False
    _, meta = loaded
    if not bool(meta.get("trained", True)):
        return False
    if meta.get("avg_oos_auc", 0.0) <= MIN_DEPLOYABLE_AUC:
        return False
    wfe = meta.get("wfe_avg")
    return wfe is not None and wfe >= MIN_DEPLOYABLE_WFE


def score_candidate(strategy: str, sig, **ctx) -> Optional[float]:
    """
    Returns P(this candidate signal wins) in [0, 1], or None if no model
    is available for `strategy` (caller should treat None as "no opinion —
    defer entirely to the rule-based system").

    `**ctx` must supply every keyword `build_feature_dict` needs:
    signal_bar_idx, local_pos, df, today_df, today, vix, vix3m, vvix, market,
    hmm, gex, tsmom, sector, macro, nq_es_spread, occ, cot, breadth, smh_sig,
    har, stop_mult, score, breakdown, risk_pts, reward_pts, rr_planned.
    """
    loaded = _load(strategy)
    if loaded is None:
        return None
    booster, _meta = loaded

    feats = build_feature_dict(strategy=strategy, sig=sig, **ctx)
    row = pd.DataFrame([feats])[ALL_FEATURES]
    for c in CATEGORICAL_FEATURES:
        row[c] = row[c].astype("category")

    # The saved booster carries `pandas_categorical` from training time, so
    # predicting on a DataFrame with the same `category`-dtype columns maps
    # levels back to the training-time codes automatically.
    proba = booster.predict(row)
    return float(proba[0])


def clear_cache() -> None:
    """Call after retraining so the next score_candidate() picks up new models."""
    _load.cache_clear()
