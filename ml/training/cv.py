"""
Purged time-series cross-validation for financial ML (López de Prado style).

Standard K-Fold / train_test_split LEAK information in time series: a trade
opened on day T can still be open (its outcome unresolved) on day T+1, T+2...
If T+1 lands in the "test" fold while T is in "train", the model implicitly
sees overlapping-outcome information — inflating CV scores in a way that does
NOT generalize live. This is THE most common way retail quant ML projects
silently produce great backtests and then bleed money live.

Two safeguards, both required:
  1. PURGING — drop training rows whose outcome window [signal_time, exit_time]
     overlaps the test fold's date range at all.
  2. EMBARGO — additionally drop a few trading days of training data
     immediately after the test fold (information about what just happened
     in the test period leaks backward through serial correlation/features
     like rolling ATR, HMM state, memory bonus, etc.)

Because `_simulate_trade` caps trade duration at 300 bars (5-min bars => at
most ~25 hours of session time, i.e. effectively never more than 1-2 calendar
days), a 1-day purge window plus a multi-day embargo is conservative and safe.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


def purged_kfold_splits(
    df: pd.DataFrame,
    n_splits: int = 5,
    embargo_days: int = 3,
    date_col: str = "date",
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    Returns a list of (train_idx, test_idx) positional-index arrays.

    Folds are contiguous blocks of TRADING DAYS (not rows) — every candidate
    signal from the same day stays in the same fold, which prevents
    same-day leakage (e.g. two ORB and IB signals on the same morning sharing
    regime context).

    Purge: any train day within `embargo_days` of the test block's start OR
    end is dropped (covers the "trade open across the boundary" case AND the
    serial-correlation leak in regime/memory features).
    """
    dates = pd.to_datetime(df[date_col]).dt.date
    unique_days = np.array(sorted(dates.unique()))
    n_days = len(unique_days)
    fold_edges = np.array_split(np.arange(n_days), n_splits)

    splits = []
    for fold_idx in fold_edges:
        if len(fold_idx) == 0:
            continue
        test_days = set(unique_days[fold_idx])
        test_start = unique_days[fold_idx[0]]
        test_end   = unique_days[fold_idx[-1]]

        embargo = timedelta(days=embargo_days)
        purge_lo = test_start - embargo
        purge_hi = test_end + embargo

        train_mask = np.array([
            (d not in test_days) and not (purge_lo <= d <= purge_hi)
            for d in unique_days
        ])
        train_days = set(unique_days[train_mask])

        train_idx = np.where(dates.isin(train_days).values)[0]
        test_idx  = np.where(dates.isin(test_days).values)[0]

        if len(train_idx) == 0 or len(test_idx) == 0:
            continue
        splits.append((train_idx, test_idx))

    return splits


def expanding_walk_forward_splits(
    df: pd.DataFrame,
    n_windows: int = 6,
    min_train_days: int = 250,
    test_days: int = 60,
    embargo_days: int = 3,
    date_col: str = "date",
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    Expanding-window walk-forward splits — mirrors how the model will actually
    be retrained live (train on everything up to T, validate on the next
    `test_days` trading days, embargo between).

    This is the split scheme used for the FINAL walk-forward validation
    (Section 18 WFE check), while `purged_kfold_splits` is used for
    hyperparameter selection / early-stopping during development.
    """
    dates = pd.to_datetime(df[date_col]).dt.date
    unique_days = np.array(sorted(dates.unique()))
    n_days = len(unique_days)

    splits = []
    start = min_train_days
    while start + embargo_days + test_days <= n_days and len(splits) < n_windows:
        train_days = set(unique_days[:start])
        test_lo = start + embargo_days
        test_hi = min(test_lo + test_days, n_days)
        test_days_set = set(unique_days[test_lo:test_hi])

        train_idx = np.where(dates.isin(train_days).values)[0]
        test_idx  = np.where(dates.isin(test_days_set).values)[0]
        if len(train_idx) and len(test_idx):
            splits.append((train_idx, test_idx))

        start = test_hi
    return splits
