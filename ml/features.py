"""
Shared feature schema for the meta-labeling models.

This module is the SINGLE SOURCE OF TRUTH for "what does the model see".
Both the historical dataset generator (`ml.generate_dataset`) and the live
inference gate (wired into `hybrid_engine` in shadow mode) call
`build_feature_dict()` with the exact same context dicts that
`_score_trade` / `_is_hard_blocked` already compute on every signal —
so there is zero risk of train/serve skew (the #1 way meta-labeling
projects silently fail).

Feature families:
  - time-of-day / direction
  - regime context (VIX family, ATR, trend, HAR vol forecast)
  - HMM 5-state probabilities (continuous — richer than the binary score factor)
  - GEX / TSMOM / OCC / sector / SMH / macro / NQ-ES spread / COT / breadth
  - RVOL, Kyle's lambda, AVWAP confluence (microstructure)
  - setup geometry (risk, planned R:R, ATR-relative size)
  - the live system's own 21-factor confidence-score breakdown (bd_*) + score

`NUMERIC_FEATURES` and `CATEGORICAL_FEATURES` list exactly the columns that
go into the model (everything else in the dataset — date, strategy, pnl,
outcome, etc. — is metadata/label, not a model input).
"""
from __future__ import annotations

from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# Defined locally (not imported from backtest.hybrid_engine) so that modules
# importing this one (e.g. ml.inference, used FROM hybrid_engine for the live
# gate) don't create a hybrid_engine <-> ml.* import cycle.
EST = ZoneInfo("America/New_York")

from strategy.inst_rvol   import compute_rvol
from strategy.inst_lambda import get_lambda_signal
from strategy.inst_avwap  import get_avwap_levels

# Ordinal encodings so a plain numeric model can also use these without
# native categorical support (LightGBM gets the `_cat` string columns too).
TREND_ORD = {"strong_bear": -2, "bear": -1, "neutral": 0, "bull": 1, "strong_bull": 2}
HMM_ORD   = {"bear": -2, "stress": -1, "neutral": 0, "bull": 1, "strong_bull": 2, "unavailable": 0}
BIAS_ORD  = {"bearish": -1, "mean_rev": -1, "neutral": 0, "bullish": 1, "breakout": 1,
             "tailwind": 1, "headwind": -1, "strong_headwind": -2, "strong_tailwind": 2}


def _safe(d: Optional[dict], key: str, default=np.nan):
    if d is None:
        return default
    v = d.get(key, default)
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float, np.floating, np.integer)):
        return float(v)
    return default


def _ord(mapping: dict, key, default=0):
    return mapping.get(key, default)


def build_feature_dict(
    *, strategy: str, sig, signal_bar_idx: int, local_pos: int,
    df: pd.DataFrame, today_df: pd.DataFrame, today: date,
    vix: Optional[float], vix3m: Optional[float], vvix: Optional[float],
    market: dict, hmm: dict, gex: dict, tsmom: dict, sector: dict, macro: dict,
    nq_es_spread: dict, occ: dict, cot: dict, breadth: dict, smh_sig: dict,
    har: dict, stop_mult: float,
    score: int, breakdown: dict,
    risk_pts: float, reward_pts: float, rr_planned: float,
) -> dict:
    """
    Build the flat dict of MODEL INPUT features for one candidate signal.

    Must be called with the exact same context dicts `_score_trade` /
    `_is_hard_blocked` receive (computed once per day in the scan/live loop —
    zero extra network calls here beyond the 3 microstructure lookups below,
    which the live loop already performs inside `_score_trade`/`_is_hard_blocked`
    too, so they're cheap/cached).
    """
    ts_est = df.index[signal_bar_idx].astimezone(EST)

    setup_ratio = np.nan
    for attr in ("atr_ratio", "gap_ratio"):
        if hasattr(sig, attr):
            setup_ratio = float(getattr(sig, attr))
            break

    entry_type    = getattr(sig, "entry_type", "")
    vwap_at_entry = getattr(sig, "vwap_at_entry", np.nan)
    deviation_std = getattr(sig, "deviation_std", np.nan)

    try:
        rvol_data = compute_rvol(df, today, local_pos)
    except Exception:
        rvol_data = {}
    try:
        lam = get_lambda_signal(today_df, local_pos, sig.direction)
    except Exception:
        lam = {}
    try:
        avwap = get_avwap_levels(df, today, float(sig.entry), market.get("atr", 0.0))
    except Exception:
        avwap = {}

    return {
        # ── time-of-day / direction ──
        "hour": ts_est.hour,
        "minute": ts_est.minute,
        "minute_of_day": ts_est.hour * 60 + ts_est.minute,
        "dir_long": 1 if sig.direction == "long" else 0,

        # ── regime / market context ──
        "vix": float(vix) if vix is not None else np.nan,
        "vix3m": float(vix3m) if vix3m is not None else np.nan,
        "vvix": float(vvix) if vvix is not None else np.nan,
        "atr": float(market.get("atr", np.nan)),
        "atr_5": float(market.get("atr_5", np.nan)),
        "atr_20": float(market.get("atr_20", np.nan)),
        "vol_regime_cat": market.get("vol_regime", "unknown"),
        "vix_regime_cat": market.get("vix_regime", "unknown"),
        "trend_dir_cat": market.get("ema_trend", {}).get("direction", "neutral"),
        "trend_dir_ord": _ord(TREND_ORD, market.get("ema_trend", {}).get("direction", "neutral")),
        "vix_term_cat": market.get("vix_term", {}).get("structure", "contango"),
        "open_type_cat": market.get("open_type", {}).get("day_type_hint", "mixed"),
        "overnight_type_cat": market.get("overnight", {}).get("day_type_bias", "neutral"),

        # ── HAR vol forecast ──
        "har_rv_forecast": _safe(har, "rv_forecast"),
        "har_vol_regime_cat": har.get("vol_regime", "normal"),
        "stop_mult": float(stop_mult),

        # ── HMM 5-state regime probabilities ──
        "hmm_state_cat": hmm.get("state", "unavailable"),
        "hmm_state_ord": _ord(HMM_ORD, hmm.get("state", "unavailable")),
        "hmm_bull_prob": _safe(hmm, "bull_prob"),
        "hmm_strong_prob": _safe(hmm, "strong_prob"),
        "hmm_neutral_prob": _safe(hmm, "neutral_prob"),
        "hmm_stress_prob": _safe(hmm, "stress_prob"),
        "hmm_bear_prob": _safe(hmm, "bear_prob"),

        # ── GEX proxy ──
        "gex_bias_cat": gex.get("bias", "neutral"),
        "gex_bias_ord": _ord(BIAS_ORD, gex.get("bias", "neutral")),
        "gex_ratio": _safe(gex, "ratio"),

        # ── Session TSMOM ──
        "tsmom_bias_cat": tsmom.get("bias", "neutral"),
        "tsmom_bias_ord": _ord(BIAS_ORD, tsmom.get("bias", "neutral")),
        "tsmom_return_30m": _safe(tsmom, "return_30m"),
        "tsmom_conviction": _safe(tsmom, "conviction"),
        "tsmom_available": _safe(tsmom, "available", 0.0),

        # ── Opening candle continuation ──
        "occ_dir_cat": occ.get("direction", "neutral"),
        "occ_conviction_cat": occ.get("conviction", "low"),
        "occ_first_bar_ret": _safe(occ, "first_bar_ret"),

        # ── Sector (XLK/SPY) + SMH lead ──
        "sector_bias_cat": sector.get("bias", "neutral"),
        "sector_rs_ratio": _safe(sector, "rs_ratio"),
        "sector_rs_vs_sma": _safe(sector, "rs_vs_sma"),
        "smh_signal_cat": smh_sig.get("signal", "neutral"),
        "smh_rs_slope": _safe(smh_sig, "smh_rs_slope"),

        # ── Macro (DXY/TNX) ──
        "macro_combined_cat": macro.get("combined", "neutral"),
        "macro_dxy_ret": _safe(macro, "dxy_ret"),
        "macro_tnx_chg_bps": _safe(macro, "tnx_chg_bps"),

        # ── NQ/ES spread ──
        "nq_es_signal_cat": nq_es_spread.get("signal", "neutral"),
        "nq_es_zscore": _safe(nq_es_spread, "z_score"),

        # ── COT positioning ──
        "cot_bias_cat": cot.get("bias", "neutral"),
        "cot_index": _safe(cot, "cot_index"),

        # ── Breadth ──
        "breadth_bias_cat": breadth.get("breadth_bias", "neutral"),
        "breadth_addn": _safe(breadth, "addn_value"),

        # ── RVOL ──
        "rvol": _safe(rvol_data, "rvol"),
        "rvol_regime_cat": rvol_data.get("regime", "normal"),

        # ── Kyle's lambda ──
        "lambda_val": _safe(lam, "lambda_val"),
        "lambda_zscore": _safe(lam, "z_score"),
        "lambda_aligned": _safe(lam, "aligned", 1.0),

        # ── AVWAP confluence ──
        "avwap_near": _safe(avwap, "near_avwap", 0.0),
        "avwap_confluence": _safe(avwap, "confluence", 0.0),

        # ── Setup geometry ──
        "risk_pts": float(risk_pts),
        "reward_pts_planned": float(reward_pts),
        "rr_planned": float(rr_planned),
        "setup_atr_ratio": setup_ratio,
        "vwap_at_entry": float(vwap_at_entry) if vwap_at_entry == vwap_at_entry else np.nan,
        "deviation_std": float(deviation_std) if deviation_std == deviation_std else np.nan,
        "entry_type_cat": entry_type,

        # ── 21-factor confidence-score breakdown (live system's own features) ──
        **{f"bd_{k}": int(v) for k, v in breakdown.items()},
        "score": int(score),
    }


# Columns that are genuinely numeric model inputs
NUMERIC_FEATURES: list[str] = [
    "hour", "minute", "minute_of_day", "dir_long",
    "vix", "vix3m", "vvix", "atr", "atr_5", "atr_20",
    "trend_dir_ord",
    "har_rv_forecast", "stop_mult",
    "hmm_state_ord", "hmm_bull_prob", "hmm_strong_prob", "hmm_neutral_prob",
    "hmm_stress_prob", "hmm_bear_prob",
    "gex_bias_ord", "gex_ratio",
    "tsmom_bias_ord", "tsmom_return_30m", "tsmom_conviction", "tsmom_available",
    "occ_first_bar_ret",
    "sector_rs_ratio", "sector_rs_vs_sma", "smh_rs_slope",
    "macro_dxy_ret", "macro_tnx_chg_bps",
    "nq_es_zscore",
    "cot_index",
    "breadth_addn",
    "rvol", "lambda_val", "lambda_zscore", "lambda_aligned",
    "avwap_near", "avwap_confluence",
    "risk_pts", "reward_pts_planned", "rr_planned", "setup_atr_ratio",
    "vwap_at_entry", "deviation_std",
    "score",
] + [f"bd_{k}" for k in (
    "tsmom", "gex", "es", "hmm", "cvd", "overnight", "vix_term", "sector",
    "macro", "nq_es_spread", "conviction", "open_type", "rvol", "occ",
    "absorption", "lambda", "smh", "cot", "avwap", "breadth", "memory",
)]

# Columns that are categorical (LightGBM handles these natively as `category` dtype)
CATEGORICAL_FEATURES: list[str] = [
    "vol_regime_cat", "vix_regime_cat", "trend_dir_cat", "vix_term_cat",
    "open_type_cat", "overnight_type_cat", "har_vol_regime_cat",
    "hmm_state_cat", "gex_bias_cat", "tsmom_bias_cat", "occ_dir_cat",
    "occ_conviction_cat", "sector_bias_cat", "smh_signal_cat",
    "macro_combined_cat", "nq_es_signal_cat", "cot_bias_cat",
    "breadth_bias_cat", "rvol_regime_cat", "entry_type_cat",
]

ALL_FEATURES: list[str] = NUMERIC_FEATURES + CATEGORICAL_FEATURES
