"""
Historical label generator for meta-labeling ML models.

Re-runs the exact same per-day context computation and signal-detection logic
as `backtest.hybrid_engine.run_hybrid_backtest`, but instead of only keeping
trades that pass the rule-based score/hard-block gates, it captures EVERY
candidate signal the primary models produce — together with:

  - the full 21-factor confidence-score breakdown (the live system's features)
  - raw continuous context values behind each factor (richer than the 0/1 score)
  - whether the rule-based system would have hard-blocked / time-blocked / taken it
  - the triple-barrier-accurate outcome from `_simulate_trade` (same two-target
    exit logic the live bot uses — upper barrier=T1/target, lower barrier=stop,
    vertical barrier=session end / 300-bar cap)

This is what meta-labeling needs: "given everything the primary model saw,
would this specific signal have won or lost?" Capturing near-misses (low score,
hard-blocked) too — not just the trades that were actually taken — avoids the
selection bias that would come from training only on cherry-picked setups.

Run with:
    python3 -m ml.generate_dataset                  # full 10yr cached data
    python3 -m ml.generate_dataset --years 3        # shorter window for a quick test
"""
from __future__ import annotations

from datetime import date
import numpy as np
import pandas as pd

from backtest.databento_loader import load_nq_databento
from backtest.data_loader import load_es, label_sessions
from backtest.hybrid_engine import (
    EST,
    _load_vix, _get_vix, _load_extended_vix, _get_ext_vix,
    _simulate_trade, _score_trade, _time_window_ok, _is_hard_blocked,
)
from strategy.quant_regime import classify_market_full, direction_allowed
from strategy.quant_gap  import detect as detect_gap
from strategy.quant_orb  import detect as detect_orb
from strategy.quant_ib   import detect as detect_ib
from strategy.quant_vwap import detect_all as detect_vwap, detect_bounce as detect_vwap_bounce

from strategy.inst_harv    import har_forecast
from strategy.inst_hmm     import get_hmm_gate
from strategy.inst_gex     import compute_gex_proxy, load_vxn
from strategy.inst_tsmom   import get_session_tsmom, get_occ_signal
from strategy.inst_leadlag import get_nq_es_spread_signal
from strategy.inst_sectors import get_tech_sector_bias, load_sector_data, get_smh_lead_signal, load_smh_data
from strategy.inst_macro   import get_macro_bias, load_macro_data
from strategy.inst_cot     import get_cot_bias, load_cot_data
from strategy.inst_breadth import get_breadth_bias, load_breadth_data
from strategy.inst_va_rule import detect_va_rule_signal

from ml.features import build_feature_dict

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _build_row(
    *, today: date, dow: int, strategy: str, sig, detail: str,
    signal_bar_idx: int, local_pos: int,
    df: pd.DataFrame, today_df: pd.DataFrame, es_df: pd.DataFrame,
    vix: float, vix3m, vvix,
    market: dict, hmm: dict, gex: dict, tsmom: dict, sector: dict, macro: dict,
    nq_es_spread: dict, occ: dict, cot: dict, breadth: dict, smh_sig: dict,
    har: dict, stop_mult: float,
    score: int, breakdown: dict,
    hard_blocked: bool, block_reason: str,
    time_ok: bool, time_reason: str,
    would_trade: bool,
    risk_pts: float, reward_pts: float, rr_planned: float,
    outcome: str, pnl: float, exit_price: float, rr_realized: float,
) -> dict:
    feats = build_feature_dict(
        strategy=strategy, sig=sig, signal_bar_idx=signal_bar_idx, local_pos=local_pos,
        df=df, today_df=today_df, today=today,
        vix=vix, vix3m=vix3m, vvix=vvix,
        market=market, hmm=hmm, gex=gex, tsmom=tsmom, sector=sector, macro=macro,
        nq_es_spread=nq_es_spread, occ=occ, cot=cot, breadth=breadth, smh_sig=smh_sig,
        har=har, stop_mult=stop_mult,
        score=score, breakdown=breakdown,
        risk_pts=risk_pts, reward_pts=reward_pts, rr_planned=rr_planned,
    )
    return {
        # ── identity / metadata (not model features — joins, audits, splits) ──
        "date": today,
        "dow": dow,
        "day_name": DAY_NAMES[dow],
        "strategy": strategy,
        "direction": sig.direction,
        "detail": detail,
        "signal_bar_idx": int(signal_bar_idx),
        "entry": float(sig.entry),
        "stop": float(sig.stop),
        "target": float(sig.target),

        # ── full feature vector (see ml.features for schema) ──
        **feats,

        # ── gating outcome (what the rule-based system would have done) ──
        "hard_blocked": int(hard_blocked),
        "hard_block_reason": block_reason or "",
        "time_blocked": int(not time_ok),
        "time_block_reason": time_reason or "",
        "would_trade": int(would_trade),

        # ── ground-truth label (triple-barrier outcome via _simulate_trade) ──
        "outcome": outcome,
        "label": 1 if outcome == "WIN" else 0,
        "pnl": float(pnl),
        "exit_price": float(exit_price),
        "rr_realized": float(rr_realized),
    }


def generate(years: int = 10, force_refresh: bool = False) -> pd.DataFrame:
    print("=" * 72)
    print("  ML LABEL GENERATOR — instrumented historical signal scanner")
    print("=" * 72)

    df = load_nq_databento(years=years, force_refresh=force_refresh)
    df = label_sessions(df, interval="5m")
    print(f"[ML] NQ data: {len(df):,} bars | {df.index[0].date()} -> {df.index[-1].date()}")

    es_df = load_es(interval="5m", period="60d")

    print("[ML] Loading VIX / VIX3M / VVIX / VXN ...")
    vix_cache   = _load_vix(period="90d")
    vix3m_cache = _load_extended_vix("^VIX3M", "90d")
    vvix_cache  = _load_extended_vix("^VVIX",  "90d")
    vxn_cache   = load_vxn(period="90d")

    print("[ML] Loading sector / macro / COT / breadth ...")
    xlk_closes, spy_closes = load_sector_data(period="90d")
    dxy_closes, tnx_closes = load_macro_data(period="90d")
    smh_closes             = load_smh_data(period="90d")
    cot_df                 = load_cot_data()
    qqq_closes, iwm_closes, addn_series = load_breadth_data(period="60d")

    est_idx   = df.index.tz_convert(EST)
    all_dates = sorted(set(est_idx.date))

    records: list[dict] = []
    skipped_days = {"weekend": 0, "vvix": 0, "vix_backwardation": 0, "har": 0}

    from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, SpinnerColumn
    progress = Progress(
        SpinnerColumn(), TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"), TextColumn("[green]{task.fields[n]} candidates"),
        TextColumn("•"), TimeRemainingColumn(),
    )
    task = progress.add_task("Scanning...", total=len(all_dates), n=0)
    progress.start()

    for today in all_dates:
        progress.update(task, advance=1, n=len(records), description=f"{today}")
        dow = today.weekday()
        if dow >= 5:
            skipped_days["weekend"] += 1
            continue

        vix   = _get_vix(vix_cache, today)
        vix3m = _get_ext_vix(vix3m_cache, today)
        vvix  = _get_ext_vix(vvix_cache, today)

        today_mask = est_idx.date == today
        today_df   = df[today_mask].copy()
        if len(today_df) < 3:
            continue

        market = classify_market_full(df, today, vix, vix3m=vix3m, vvix=vvix, today_df=today_df)
        atr   = market["atr"]
        trend = market["ema_trend"]

        if market["vvix_regime"]["skip_day"]:
            skipped_days["vvix"] += 1
            continue
        if market["vix_term"]["structure"] == "deep_backwardation":
            skipped_days["vix_backwardation"] += 1
            continue

        hmm    = get_hmm_gate(df, today)
        gex    = compute_gex_proxy(vix_cache, vxn_cache, today)
        tsmom  = get_session_tsmom(today_df)
        sector = get_tech_sector_bias(today, xlk_closes, spy_closes)
        macro  = get_macro_bias(today, dxy_closes, tnx_closes)
        nq_es_spread = get_nq_es_spread_signal(df, es_df, today)
        occ    = get_occ_signal(today_df)
        cot    = get_cot_bias(today, _df=cot_df)
        breadth = get_breadth_bias(today, qqq_closes, iwm_closes, addn_series)
        smh_sig = get_smh_lead_signal(today, smh_closes, spy_closes, vxn=(vix or 20.0))

        har = har_forecast(df, today)
        if har["skip_day"]:
            skipped_days["har"] += 1
            continue
        stop_mult = har["stop_mult"]

        def _local_pos(sig) -> int:
            try:
                signal_ts = df.index[sig.signal_bar_idx]
                diffs = [abs((ts - signal_ts).total_seconds()) for ts in today_df.index]
                return int(np.argmin(diffs))
            except Exception:
                return min(sig.signal_bar_idx, len(today_df) - 1)

        def _capture(strategy: str, sig, detail: str = "", max_hour: int = 12) -> None:
            if sig is None:
                return
            risk_pts = abs(sig.entry - sig.stop)
            if risk_pts < 1.0:
                return

            local_pos = _local_pos(sig)

            effective_mult = 1.0 if strategy == "va_rule" else stop_mult
            if sig.direction == "long":
                adjusted_stop = sig.entry - (sig.entry - sig.stop) * effective_mult
            else:
                adjusted_stop = sig.entry + (sig.stop - sig.entry) * effective_mult

            blocked, block_reason = _is_hard_blocked(
                strategy, sig, today_df, local_pos, df, today, market, macro
            )
            time_ok, time_reason = _time_window_ok(sig.signal_bar_idx, df, strategy)

            score, breakdown = _score_trade(
                strategy, sig, today_df, local_pos,
                df, es_df, hmm, gex, tsmom, market, sector, macro, nq_es_spread, occ,
                cot=cot, breadth=breadth, smh_signal=smh_sig, smh_vxn=(vix or 20.0),
            )

            # Replicate the live system's take/skip decision (for analysis & to
            # mark which rows were "actually traded" in the rule-based baseline)
            score_ok = score > 5
            if strategy == "fvg":
                score_ok = score >= 17
            if strategy == "va_rule":
                score_ok = score >= 18
            would_trade = (not blocked) and time_ok and score_ok

            # Strategy-specific T2 target extensions (mirrors _try_hybrid exactly,
            # so the simulated outcome matches what the live system would realize)
            effective_target = sig.target
            if strategy == "orb" and hasattr(sig, "orb_range") and sig.orb_range > 0:
                ext = sig.entry + sig.orb_range * 3.0 if sig.direction == "long" \
                      else sig.entry - sig.orb_range * 3.0
                effective_target = max(sig.target, ext) if sig.direction == "long" \
                                   else min(sig.target, ext)
            elif strategy == "ib_breakout" and hasattr(sig, "ib_range") and sig.ib_range > 0:
                ext = sig.entry + sig.ib_range * 2.5 if sig.direction == "long" \
                      else sig.entry - sig.ib_range * 2.5
                effective_target = max(sig.target, ext) if sig.direction == "long" \
                                   else min(sig.target, ext)

            exit_p, pnl, outcome = _simulate_trade(
                df, sig.signal_bar_idx, sig.direction, sig.entry,
                adjusted_stop, effective_target, n_contracts=1, max_hour=max_hour,
            )
            reward_pts = abs(effective_target - sig.entry)
            rr_planned = reward_pts / risk_pts if risk_pts > 0 else 0.0
            rr_realized = pnl / (risk_pts * 2.0) if risk_pts > 0 else 0.0  # 2.0 = MNQ_PER_POINT * 1 contract

            records.append(_build_row(
                today=today, dow=dow, strategy=strategy, sig=sig, detail=detail,
                signal_bar_idx=sig.signal_bar_idx, local_pos=local_pos,
                df=df, today_df=today_df, es_df=es_df,
                vix=vix, vix3m=vix3m, vvix=vvix,
                market=market, hmm=hmm, gex=gex, tsmom=tsmom, sector=sector, macro=macro,
                nq_es_spread=nq_es_spread, occ=occ, cot=cot, breadth=breadth, smh_sig=smh_sig,
                har=har, stop_mult=stop_mult,
                score=score, breakdown=breakdown,
                hard_blocked=blocked, block_reason=block_reason,
                time_ok=time_ok, time_reason=time_reason,
                would_trade=would_trade,
                risk_pts=risk_pts, reward_pts=reward_pts, rr_planned=rr_planned,
                outcome=outcome, pnl=pnl, exit_price=exit_p, rr_realized=rr_realized,
            ))

        vix_ok = vix < 25

        # Gap Fill
        gap = detect_gap(df, today, atr, dow=dow)
        if gap and direction_allowed(gap.direction, trend, strict=True):
            _capture("gap_fill", gap, f"gap={gap.gap_size:.1f}pts ({gap.gap_ratio:.2f}xATR)")

        # ORB
        if vix_ok:
            orb = detect_orb(df, today, atr, dow)
            if orb:
                if orb.direction == "short":
                    ok = trend["direction"] == "strong_bear"
                else:
                    ok = trend["direction"] in ("strong_bull", "neutral")
                if ok:
                    _capture("orb", orb,
                             f"ORB={orb.orb_range:.0f}pts ({orb.atr_ratio:.2f}xATR) [{orb.entry_type}]")

        # IB Breakout
        if vix_ok and dow != 0:
            ib = detect_ib(df, today, atr)
            if ib and direction_allowed(ib.direction, trend, strict=True):
                _capture("ib_breakout", ib, f"IB={ib.ib_range:.0f}pts ({ib.atr_ratio:.2f}xATR)")

        # AM VWAP Reversion
        _rev_hmm = hmm.get("state", "unavailable")
        if market["vwap_ok"]:
            for vs in detect_vwap(df, today, vix, atr, max_signals=3):
                if direction_allowed(vs.direction, trend, strict=True):
                    _rev_ok = (
                        (vs.direction == "long"  and _rev_hmm in ("bull", "strong_bull")) or
                        (vs.direction == "short" and _rev_hmm in ("bear", "stress"))
                    )
                    if _rev_ok:
                        _capture("vwap_rev", vs, f"dev={vs.deviation_pts:.1f}pts ({vs.deviation_std:.1f}s)")

        # AM VWAP Bounce
        if market["vwap_ok"]:
            for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"], max_signals=3):
                if direction_allowed(vs.direction, trend, strict=True):
                    _capture("vwap_bounce", vs, f"VWAP bounce {trend['direction']} dev={vs.deviation_pts:.1f}pts")

        # PM VWAP Bounce
        if market["vwap_ok"]:
            for vs in detect_vwap_bounce(df, today, vix, atr, trend["direction"], max_signals=3,
                                         start_min=13*60+30, end_min=15*60+30):
                if direction_allowed(vs.direction, trend, strict=True):
                    _capture("vwap_bounce_pm", vs, f"PM VWAP bounce {trend['direction']}", max_hour=16)

        # 80% Value Area Rule
        if vix_ok:
            va_sig = detect_va_rule_signal(df, today, atr)
            if va_sig and direction_allowed(va_sig.direction, trend, strict=False):
                _capture("va_rule", va_sig,
                         f"VA rule type={va_sig.setup_type} "
                         f"vah-val={abs(va_sig.va_target_edge - va_sig.va_entry_edge):.0f}pts")

    progress.stop()

    out = pd.DataFrame.from_records(records)
    print(f"\n[ML] Captured {len(out):,} candidate signals across {len(all_dates):,} calendar days")
    print(f"[ML] Day skips: {skipped_days}")
    if not out.empty:
        print("\n[ML] Candidates by strategy:")
        print(out.groupby("strategy").agg(
            n=("label", "size"), wr=("label", "mean"),
            would_trade=("would_trade", "sum"),
        ).sort_values("n", ascending=False).to_string(float_format=lambda x: f"{x:.3f}"))
    return out


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--out", type=str, default="ml/data/candidates.parquet")
    args = p.parse_args()

    out = generate(years=args.years, force_refresh=args.refresh)
    out.to_parquet(args.out, index=False)
    print(f"\n[ML] Saved {len(out):,} rows -> {args.out}")


if __name__ == "__main__":
    main()
