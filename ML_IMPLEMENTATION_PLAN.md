# ML Implementation Plan — MNQ Isogeny Alpha System
**Date:** June 2026  
**System:** MNQ RTH 9:30–12:00 ET | Tradeify $25k Eval  
**Current WR:** ~76.8% | Goal: 80%+ with lower variance and smarter sizing

---

## TABLE OF CONTENTS

1. [What We're Actually Doing & Why](#1-what-were-actually-doing--why)
2. [Architecture Overview of the New System](#2-architecture-overview-of-the-new-system)
3. [Phase 1 — ML Signal Quality Classifier (Replace Hardcoded Thresholds)](#3-phase-1--ml-signal-quality-classifier)
4. [Phase 2 — Dynamic Regime Engine (Replace HMM)](#4-phase-2--dynamic-regime-engine)
5. [Phase 3 — Neural Confidence Scorer (Replace 20-Point Manual System)](#5-phase-3--neural-confidence-scorer)
6. [Phase 4 — Adaptive Exit Engine (Dynamic Stop/Target)](#6-phase-4--adaptive-exit-engine)
7. [Phase 5 — Bayesian Position Sizer (Replace Static Kelly)](#7-phase-5--bayesian-position-sizer)
8. [Phase 6 — Strategy Selector (Which Strategy Wins Today)](#8-phase-6--strategy-selector)
9. [Phase 7 — Online Learning & Walk-Forward Retraining](#9-phase-7--online-learning--walk-forward-retraining)
10. [Phase 8 — New Feature Engineering](#10-phase-8--new-feature-engineering)
11. [Phase 9 — RL Agent for Intraday Adaptation](#11-phase-9--rl-agent-for-intraday-adaptation)
12. [Complete Hardcoded Parameter Migration Table](#12-complete-hardcoded-parameter-migration-table)
13. [Implementation Order & Dependencies](#13-implementation-order--dependencies)
14. [File Structure for New ML Layer](#14-file-structure-for-new-ml-layer)
15. [Training Data Setup](#15-training-data-setup)
16. [Live Integration Points](#16-live-integration-points)
17. [Risk Guardrails You Must Never Remove](#17-risk-guardrails-you-must-never-remove)
18. [Research-Backed Implementation Guidance — Read Before Starting](#18-research-backed-implementation-guidance--read-before-starting)

---

## 1. What We're Actually Doing & Why

### The Problem with the Current System

The current system is excellent — 76.8% WR is genuinely elite for a prop firm eval. But it has one fundamental constraint: **almost every decision boundary is a fixed number someone decided was right.**

Examples of the problem:
- `gap_ratio < 0.20` — why 0.20? Maybe on high-VIX Thursdays it should be 0.15, and on low-VIX Wednesdays it should be 0.28. The system can't know.
- `VPIN_THRESHOLD = 0.65` — blocks trades when VPIN > 65%. But maybe at 0.68 in a bull regime it's still fine, and at 0.58 in a bear regime it should already block.
- `WR_SIZE_UP = 0.75` — size up to 2 lots at 75% WR. But what if that 75% was built on 8 trending days and today is range-bound?
- `CHANDELIER_MULT = 3.0` — trail everything at 3× ATR. But ORB breakouts in low-vol regimes should trail tighter (1.8×), and FVG trades in high-vol regimes need 4×.

**The 20-point confidence scoring system is the biggest opportunity.** It's a linear sum — each factor adds exactly 1 point. That's a manual approximation of what a neural network learns automatically: the non-linear interactions between factors. TSMOM + CVD + OCC together in a trending market is worth 8 points, not 3. The current system can't capture that.

### What ML Gives You

| Problem | ML Solution | Expected Gain |
|---------|-------------|---------------|
| Fixed thresholds | Gradient boosting classifier with regime-conditional boundaries | +3-5% WR |
| Linear confidence scoring | Neural network with learned factor interactions | Filter out another 15% of losing trades |
| Static Kelly sizing | Bayesian Kelly with uncertainty bounds | Reduce drawdown by 20-30% |
| Fixed Chandelier 3.0× | Predicted optimal trail per trade | Capture more T2 profit |
| Fixed 50/50 T1/T2 split | ML-predicted optimal exit split | +8-12% on avg winner |
| HMM regime (5 states) | LightGBM regime ensemble (15+ features) | Better day-gating |
| Strategy selected by order | Strategy selector that predicts today's winner | Fewer "wrong strategy" days |

---

## 2. Architecture Overview of the New System

```
┌─────────────────────────────────────────────────────────────────┐
│                    MORNING PRE-OPEN (9:00–9:29 AM)              │
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐                     │
│  │  REGIME ENGINE  │    │ STRATEGY SELECT │                     │
│  │  (LightGBM      │    │ (Which strat    │                     │
│  │   ensemble)     │    │  wins today?)   │                     │
│  └────────┬────────┘    └────────┬────────┘                     │
│           │                     │                               │
│           └──────────┬──────────┘                               │
│                      ▼                                          │
│              Daily Regime State + Strategy Priority List         │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                  INTRADAY (9:30 AM – 12:00 PM)                  │
│                                                                  │
│  5m Bar Close                                                   │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────────────────────────────┐                           │
│  │    ML SIGNAL QUALITY CLASSIFIER  │                           │
│  │    (LightGBM per strategy)       │                           │
│  │    Input: 80+ features           │                           │
│  │    Output: P(win) for each strat │                           │
│  └──────────────┬───────────────────┘                           │
│                 │  P(win) > threshold?                          │
│                 ▼                                               │
│  ┌──────────────────────────────────┐                           │
│  │   NEURAL CONFIDENCE SCORER      │                           │
│  │   (Replaces 20-point system)     │                           │
│  │   Input: all 20 factors +        │                           │
│  │          signal P(win) + regime  │                           │
│  │   Output: 0.0–1.0 confidence    │                           │
│  └──────────────┬───────────────────┘                           │
│                 │  confidence > 0.55?                           │
│                 ▼                                               │
│  ┌──────────────────────────────────┐                           │
│  │   BAYESIAN POSITION SIZER       │                           │
│  │   Input: regime, confidence,     │                           │
│  │          recent trades, DD state │                           │
│  │   Output: 0 / 1 / 2 contracts   │                           │
│  └──────────────┬───────────────────┘                           │
│                 │                                               │
│                 ▼  TRADE FIRED                                  │
│  ┌──────────────────────────────────┐                           │
│  │   ADAPTIVE EXIT ENGINE          │                           │
│  │   Input: bar-by-bar features +  │                           │
│  │          open PnL + regime       │                           │
│  │   Output: hold / T1 / T2 /      │                           │
│  │           trail_mult / stop_adj │                           │
│  └──────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                  END OF DAY                                     │
│                                                                  │
│   Trade outcome logged → Online learner updates all models      │
│   Walk-forward retrain triggered if > 5 new outcomes            │
│   Bot memory updated with regime-specific stats                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Phase 1 — ML Signal Quality Classifier

### What it replaces

Every hardcoded entry threshold in every strategy file:
- `gap_ratio < 0.20` (quant_gap.py:79)
- `min_range = max(3.0, 0.025 × ATR)` (quant_orb.py:86)
- `retrace_depth < 0.75` (quant_orb.py:147)
- `SIGNAL_STD = 1.5` (quant_vwap.py:37)
- All others listed in §12

### What it is

A **LightGBM binary classifier per strategy** trained to predict: *"Given these market conditions at bar close, will this signal result in a win or loss?"*

Output: `P(win | features, strategy)` → a number from 0.0 to 1.0

### Architecture

```
For each strategy in [gap_fill, orb, ib, vwap_rev, vwap_bounce, fvg]:
    model = LightGBMClassifier(
        n_estimators=500,
        learning_rate=0.02,
        max_depth=6,
        min_child_samples=30,    # prevents overfitting on small datasets
        subsample=0.8,
        colsample_bytree=0.7,
        class_weight='balanced', # handles WR imbalance
        reg_alpha=0.1,           # L1
        reg_lambda=0.5           # L2
    )
    
    Features (80+): see §10 for full list
    Target: 1 if trade hit T1 (1R profit), 0 if stopped out or scratched
    Training: expanding window walk-forward (never look-ahead)
    Retrain: weekly or after 10 new labeled examples
```

### Key design decision: Per-strategy models

Gap fill and ORB breakout are very different bets. A unified model will find the union of their features useless for each. Separate models let each one find its own most predictive signals.

### Training data generation

```python
# backtest/ml_label_generator.py

def generate_labels(bars_df, strategy_name):
    """
    Run backtest, capture every signal candidate (even ones the current 
    system would skip due to hardcoded thresholds), record outcome.
    This gives you a richer training set than only "approved" trades.
    """
    signals = []
    for i, bar in bars_df.iterrows():
        features = extract_features(bars_df, i)
        signal = generate_candidate_signal(bars_df, i, strategy_name)
        if signal:
            outcome = simulate_trade_outcome(bars_df, i, signal)
            signals.append({**features, 'outcome': outcome})
    return pd.DataFrame(signals)
```

**Important:** Generate candidates with **relaxed thresholds** (e.g., allow `gap_ratio < 0.35` instead of 0.20). This gives the model training examples of what happens when you're too loose, so it learns the actual boundary rather than just re-learning the hardcoded one.

### File to create

```
ml/models/signal_classifier.py
ml/models/signal_classifier_gap.pkl
ml/models/signal_classifier_orb.pkl
ml/models/signal_classifier_ib.pkl
ml/models/signal_classifier_vwap.pkl
ml/models/signal_classifier_fvg.pkl
ml/train/train_signal_classifiers.py
```

### Integration point

In `strategy/quant_gap.py`, `quant_orb.py`, etc. — after computing the signal candidate, instead of checking hardcoded thresholds:

```python
# OLD (quant_gap.py:79)
if gap_ratio > 0.20:
    return None

# NEW
from ml.models.signal_classifier import SignalClassifier
clf = SignalClassifier.load('gap_fill')
p_win = clf.predict_proba(features)
if p_win < 0.52:  # learned threshold, calibrated on validation set
    return None
signal['ml_confidence'] = p_win
```

### Expected impact

- Gap fill: threshold adapts to regime (stricter on Mondays, looser after earnings)
- ORB: learns that pullback depth matters more on high-RVOL days
- VWAP: learns that 1.5σ in a strong trend is never worth taking
- Overall: +3-5% WR improvement, fewer "technically valid but contextually wrong" entries

---

## 4. Phase 2 — Dynamic Regime Engine

### What it replaces

- `strategy/quant_regime.py` — EMA8/EMA21 based trend, fixed VIX buckets
- `strategy/inst_hmm.py` — 5-state Gaussian HMM on daily returns
- `BEAR_THRESHOLD = 0.55`, `STRESS_THRESHOLD = 0.60` (inst_hmm.py:58-59)
- VIX bucketing logic (quant_engine.py:331)

### What it is

A **LightGBM regime classifier** that outputs:
1. Market state: `[strong_bull, bull, neutral, bear, stress, crash]`
2. Intraday volatility forecast: `[compressed, normal, elevated, crisis]`  
3. Session type prediction: `[trending, range, choppy, fake-out_heavy]`
4. Per-strategy go/no-go probability: `P(strategy_profitable | today's regime)`

### Why this beats HMM

The HMM only sees daily returns. This model sees:
- VIX term structure slope (VIX9D/VIX/VIX3M) — tells you if fear is short-term or persistent
- Overnight gap magnitude + direction
- Pre-open futures vs cash spread
- VXN/VIX ratio (already in GEX filter, but not in regime detection)
- ES/NQ ratio (which is leading)
- First 5 minutes of RTH price action
- RVOL at open vs rolling 10-day average
- Day-of-week + calendar effects
- Prior 3 days' outcomes + regime sequence

### Architecture

```python
# ml/models/regime_engine.py

class RegimeEngine:
    def __init__(self):
        self.state_model = LightGBMClassifier(n_class=6, ...)
        self.vol_model = LightGBMClassifier(n_class=4, ...)
        self.session_model = LightGBMClassifier(n_class=4, ...)
        self.strategy_models = {
            'gap_fill': LightGBMClassifier(...),
            'orb': LightGBMClassifier(...),
            'ib': LightGBMClassifier(...),
            'vwap_rev': LightGBMClassifier(...),
            'fvg': LightGBMClassifier(...),
        }
    
    def predict_morning(self, features_930am):
        """Call once at 9:00 AM with overnight + pre-open data"""
        state = self.state_model.predict_proba(features_930am)
        vol = self.vol_model.predict_proba(features_930am)
        session = self.session_model.predict_proba(features_930am)
        strategy_probs = {
            s: m.predict_proba(features_930am) 
            for s, m in self.strategy_models.items()
        }
        return RegimeSnapshot(state, vol, session, strategy_probs)
    
    def update_intraday(self, new_bar):
        """Update regime probabilities on each 5m bar close"""
        # Lightweight update — just adjust vol forecast and session type
        # State doesn't change intraday, but vol certainty grows
        pass
```

### Regime features at 9:00 AM

```python
MORNING_REGIME_FEATURES = [
    # Overnight
    'overnight_gap_pts',        # NQ gap
    'overnight_gap_pct',        # As % of prior close
    'overnight_range_pts',      # High-low of overnight session
    'overnight_direction',      # Up/down/neutral
    'overnight_close_position', # Where did overnight close relative to range (0-1)
    
    # Volatility signals
    'vix_open',                 # VIX at 9:00 AM
    'vix_prev_close',
    'vix_5d_ma',
    'vix_change_pct',
    'vix_9d',                   # VIX9D (short-term VIX)
    'vix_term_slope',           # VIX9D - VIX (inverted term structure = fear)
    'vxn_vix_ratio',            # GEX proxy
    'atr_14d',                  # 14-day daily ATR
    'atr_ratio',                # Today's expected ATR / 20d ATR
    
    # Market structure
    'es_nq_divergence',         # ES/NQ relative strength overnight
    'spy_close_vs_vwap',        # Where did SPY close vs its daily VWAP
    'qqq_close_vs_vwap',
    'nq_prev_day_type',         # Was yesterday trending/range/choppy
    'nq_prev_day_outcome',      # % gain/loss yesterday
    
    # Calendar
    'day_of_week',              # 0=Mon, 4=Fri
    'days_to_expiry',           # Days to next NQ expiry
    'days_to_fomc',             # Days to next FOMC
    'week_of_month',
    'month',
    
    # Recent memory
    'prior_3d_regime_sequence', # [bull, neutral, stress] → encode as ordinal
    'prior_3d_win_rate',        # Bot's WR in last 3 days
    'prior_session_outcome',    # Win/loss/scratch in yesterday's session
    'consecutive_losses',       # From bot_memory
    
    # Pre-open futures
    'premarket_rvol',           # RVOL at 9:00 vs prior opens
    'premarket_range_vs_atr',
    'premarket_trend_strength',
]
```

### Labels for training

Use **confirmed session outcomes** from your journal:
- State labels: Can be derived from VIX + realized vol + outcome
- Session type: Analyze post-hoc if the session was trending/choppy (using realized intraday swings)
- Strategy labels: Did gap_fill work today? Did ORB work? Binary per strategy

### Integration point

In `hybrid_run.py` and `inst_run.py`, replace:

```python
# OLD
regime = detect_regime(bars, vix_data)

# NEW
from ml.models.regime_engine import RegimeEngine
regime_engine = RegimeEngine.load()
regime_snapshot = regime_engine.predict_morning(morning_features)

# Now strategy selection and gating use regime_snapshot.strategy_probs
# instead of hardcoded VIX < 22 / trend == neutral
```

---

## 5. Phase 3 — Neural Confidence Scorer

### What it replaces

The entire `hybrid_engine.py` 20-point confidence scoring system (lines 358–640).

Current system: Linear sum of 20 binary factors → 0–20 integer.  
New system: Gradient boosted model → 0.0–1.0 calibrated probability.

### Why this is the single highest-impact change

The 20-point system assumes:
1. All factors are equal weight (each worth exactly 1 point)
2. Factors are independent (TSMOM adds 1 point whether or not CVD also aligns)
3. The threshold (score ≥ 6 to trade) is universal

None of these are true. The ML version learns:
- TSMOM is worth 3× more than COT on an intraday basis
- TSMOM + CVD + OCC together in a trend = 8 effective points, not 3
- The threshold should be 0.58 for gap fill on Tuesdays, 0.65 for VWAP on high-VIX Mondays
- Some factors are noise on certain days and should be ignored entirely

### Architecture

```python
# ml/models/confidence_scorer.py

class ConfidenceScorer:
    """
    Replaces 20-point linear scoring with gradient-boosted probability.
    """
    def __init__(self):
        self.model = LightGBMClassifier(
            n_estimators=300,
            learning_rate=0.03,
            max_depth=5,
            min_child_samples=25,
            subsample=0.75,
            class_weight='balanced',
        )
        self.calibrator = IsotonicRegression(out_of_bounds='clip')
        # Calibration step ensures P(win) is reliable, not just ranked
    
    def predict(self, signal_features, regime_snapshot):
        raw_prob = self.model.predict_proba(
            self._build_input(signal_features, regime_snapshot)
        )
        return self.calibrator.predict([raw_prob])[0]  # calibrated 0-1
    
    def _build_input(self, sig, regime):
        return [
            # All 20 original factors (as floats, not binary)
            sig['tsmom_value'],          # continuous value, not just aligned/not
            sig['gex_ratio'],            # actual VXN/VIX ratio
            sig['es_direction_z'],       # ES lead-lag z-score
            sig['hmm_bear_prob'],        # actual P(bear), not binary
            sig['cvd_divergence'],       # continuous CVD value
            sig['overnight_type'],       # encoded
            sig['vix_term_slope'],       # not just binary up/down
            sig['xlk_relative_str'],     # XLK vs SPY
            sig['dxy_z_score'],          # DXY deviation from 20d mean
            sig['nq_es_spread'],         # spread z-score
            sig['session_conviction'],   # intraday momentum score
            sig['open_type_code'],       # encoded open type
            sig['rvol'],                 # actual RVOL value
            sig['occ_score'],            # opening candle continuation strength
            sig['absorption_score'],     # absorption level
            sig['kyle_lambda'],          # actual lambda value
            sig['smh_str'],              # SMH vs QQQ strength
            sig['cot_net'],              # actual COT net positioning
            sig['avwap_distance'],       # distance in ATR units
            sig['breadth_score'],        # A/D ratio value
            
            # NEW: signal quality from Phase 1
            sig['ml_signal_confidence'], # P(win) from signal classifier
            
            # Regime context
            regime.state_probs[0],      # P(strong_bull)
            regime.state_probs[1],      # P(bull)
            regime.state_probs[4],      # P(stress)
            regime.vol_regime_code,
            regime.session_type_code,
            
            # Strategy context
            sig['strategy_type_code'],  # encoded
            sig['contracts_proposed'],
            
            # Time context
            sig['minutes_since_open'],
            sig['day_of_week'],
        ]
```

### Calibration — critical step

After training, calibrate using Isotonic Regression on a held-out validation set. This ensures that when the model says `P(win) = 0.70`, it actually wins 70% of the time. Without calibration, you can't use the probability to make sizing decisions.

```python
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
# Or manual isotonic regression post-hoc on validation set
```

### Dynamic threshold per strategy

Instead of `score >= 6` for all strategies, learn:

```python
CONFIDENCE_THRESHOLDS = {
    'gap_fill':     0.56,   # Historically high WR, lower bar
    'orb':          0.58,
    'ib':           0.60,
    'vwap_rev':     0.65,   # Lower base WR, need more confidence
    'vwap_bounce':  0.62,
    'fvg':          0.57,
}
```

Derive these thresholds by maximizing risk-adjusted return on validation set — not just WR.

### Sizing from confidence

Replace `score >= 19 → 2 lots`:

```python
def get_contracts(confidence, regime, kelly_fraction, drawdown_state):
    if confidence < 0.55:
        return 0  # Don't trade
    elif confidence < 0.68:
        return 1
    elif confidence >= 0.68 and kelly_fraction >= 0.5 and drawdown_state == 'healthy':
        return 2
    else:
        return 1
```

---

## 6. Phase 4 — Adaptive Exit Engine

### What it replaces

- `CHANDELIER_MULT = 3.0` (hybrid_engine.py:107) — static trail multiplier
- Fixed 50/50 T1/T2 split (universal across all strategies and conditions)
- Fixed `T1 = 1× risk` distance (same regardless of target quality)

### The insight

The current system trails everything at `3.0 × ATR`. But:
- ORB breakout in trending day with high RVOL: trail should be tight (1.8×) to lock in gains fast
- FVG in choppy market: trail should be wide (4.5×) to avoid getting stopped out on noise
- VWAP reversion near end of session: T1 should trigger faster (0.8× risk, not 1×)
- Gap fill with huge runway: T2 target should extend past `prior_close + 0.5×`

### Architecture

```python
# ml/models/exit_engine.py

class AdaptiveExitEngine:
    """
    Predicts optimal exit parameters per trade at entry time.
    Updates trailing stop recommendation on each bar.
    """
    def __init__(self):
        # At-entry: predict T1 distance, T2 multiplier, split ratio
        self.entry_model = LightGBMRegressor(...)
        
        # Bar-by-bar: predict if we're in a "reverse now" moment
        # or a "let it run" moment
        self.bar_model = LightGBMClassifier(...)  # hold/partial_exit/full_exit
    
    def predict_at_entry(self, signal, regime_snapshot):
        """Returns ExitParams for this trade."""
        features = self._entry_features(signal, regime_snapshot)
        
        t1_mult = self.t1_model.predict(features)[0]    # 0.6–1.4× risk
        chandelier = self.t2_model.predict(features)[0] # 1.5–5.0× ATR
        split = self.split_model.predict(features)[0]   # 0.3–0.7 at T1
        
        return ExitParams(
            t1_distance=signal['risk_pts'] * t1_mult,
            trail_mult=max(1.5, min(5.0, chandelier)),  # hard clamp
            t1_exit_fraction=max(0.3, min(0.7, split))
        )
    
    def update_bar(self, trade_state, new_bar, regime_snapshot):
        """Call on each 5m bar while trade is open."""
        features = self._bar_features(trade_state, new_bar, regime_snapshot)
        action = self.bar_model.predict(features)
        
        if action == 'tighten_trail':
            return TrailAdjustment(new_mult=trade_state.trail_mult * 0.85)
        elif action == 'widen_trail':
            return TrailAdjustment(new_mult=trade_state.trail_mult * 1.15)
        else:
            return TrailAdjustment(keep=True)
```

### Exit features at entry

```python
EXIT_ENTRY_FEATURES = [
    'strategy_type',
    'ml_signal_confidence',    # from Phase 1
    'regime_state',
    'vol_regime',
    'session_type',            # trending/choppy
    'rvol_at_entry',
    'minutes_since_open',
    'distance_to_key_level',   # how close is next VWAP/AVWAP/IB level?
    'atr_normalized_range',    # today's range / ATR (how extended is today?)
    'spread_quality',          # bid/ask spread quality (from Databento)
    'cvd_at_entry',            # buying/selling pressure direction
    'tsmom_at_entry',
    'time_to_session_end',     # minutes until 12:00 PM cutoff
]
```

### Exit features bar-by-bar

```python
EXIT_BAR_FEATURES = [
    'open_pnl_r',              # current P&L in R units
    'bars_in_trade',
    'price_vs_vwap',
    'price_vs_t1_target',      # how far to T1
    'momentum_5bar',           # recent 5-bar close momentum
    'volume_delta_current',    # CVD direction in last 3 bars
    'bar_close_position',      # where did bar close in its range (0-1)
    'regime_shift_detected',   # did regime change since entry?
    'time_to_session_end',
    'rvol_current',
]
```

### Training labels for exit model

Run historical trades through multiple exit strategies and record which one maximized risk-adjusted return:
- `T1_distance = 0.5R, 1R, 1.2R, 1.5R`
- `Chandelier = 1.5×, 2.0×, 2.5×, 3.0×, 3.5×, 4.5×`
- `split = 30%, 50%, 70%`

The training target for each trade = the combination that historically produced the best Sharpe on that trade type in that regime.

---

## 7. Phase 5 — Bayesian Position Sizer

### What it replaces

- `inst_kelly.py` — static Kelly on 50-trade lookback
- `bot_memory.py:29` — `WR_SIZE_UP = 0.75` (hard threshold)
- `MAX_CONTRACTS = 2` (binary 1-lot or 2-lot)

### The current problem

The current Kelly is "hot or cold" — it sizes up if WR ≥ 75% and down otherwise. But:
- 75% on 8 trades in a new regime is unreliable (wide confidence interval)
- 65% on 40 trades in a stable regime is very reliable (tight CI)
- After a 3-loss streak the system pauses, even if losses were all on high-RVOL days that aren't repeating

### Bayesian Kelly approach

```python
# ml/models/bayesian_sizer.py

class BayesianKellySizer:
    """
    Maintains a Beta distribution over true win rate per regime.
    Uses uncertainty-weighted Kelly to determine contract size.
    """
    def __init__(self):
        # Beta(alpha, beta) distribution per regime × strategy × day-of-week
        # Prior: Beta(10, 4) = ~71% WR with moderate confidence
        self.distributions = defaultdict(lambda: BetaDistribution(alpha=10, beta=4))
    
    def update(self, strategy, regime_key, won):
        """Called after each trade completes."""
        dist = self.distributions[(strategy, regime_key)]
        if won:
            dist.alpha += 1
        else:
            dist.beta += 1
    
    def get_kelly_fraction(self, strategy, regime_key, confidence_score):
        dist = self.distributions[(strategy, regime_key)]
        
        # Sample win rate with uncertainty
        p_mean = dist.alpha / (dist.alpha + dist.beta)
        p_lower = dist.ppf(0.20)  # 20th percentile = pessimistic
        
        # Use pessimistic estimate when uncertain (low total trades)
        n_trades = dist.alpha + dist.beta - 14  # subtract prior pseudocounts
        uncertainty = 1.0 / max(1, n_trades ** 0.5)
        p_used = p_mean * (1 - uncertainty) + p_lower * uncertainty
        
        # Kelly formula: f = (p*b - q) / b, where b = avg_win / avg_loss
        avg_wr = p_used
        avg_rr = 1.8  # ~1.8R average winner (from T1 + trailing T2)
        q = 1 - avg_wr
        kelly = (avg_wr * avg_rr - q) / avg_rr
        
        # Fractional Kelly (25% of full Kelly = safe zone)
        fractional = kelly * 0.25
        
        # Scale by ML confidence
        adjusted = fractional * (0.5 + confidence_score)  # higher conf = closer to full frac Kelly
        
        return max(0.0, min(1.0, adjusted))
    
    def get_contracts(self, strategy, regime_key, confidence, drawdown_state):
        if drawdown_state == 'critical':  # < $200 buffer
            return 0
        if drawdown_state == 'warning':   # $200-$400 buffer
            return 1
        
        kelly = self.get_kelly_fraction(strategy, regime_key, confidence)
        
        if kelly < 0.05:
            return 0  # Edge is gone, don't trade
        elif kelly < 0.30 or confidence < 0.60:
            return 1
        else:
            return 2  # Full size only with high Kelly AND high confidence
```

### Regime key for per-regime tracking

```python
def make_regime_key(regime_snapshot, day_of_week):
    # Create a composite key that groups similar conditions
    return (
        regime_snapshot.state,           # bull/neutral/bear/stress
        regime_snapshot.vol_regime,      # compressed/normal/elevated/crisis  
        day_of_week,                     # 0-4
    )
```

This means you'll have ~5 × 4 × 5 = 100 separate "regime slots" that each accumulate their own win rate. After ~6 months of trading you'll have meaningful data in each slot.

---

## 8. Phase 6 — Strategy Selector

### What it replaces

The current priority order in `hybrid_engine.py`:
1. Gap Fill
2. FVG
3. ORB
4. IB
5. VWAP Rev
6. VWAP Bounce

This is a fixed order. The system always tries gap fill first, ORB second. But some days IB breakout is the winner and gap fill is a trap.

### What it is

A **multiclass LightGBM classifier** trained on morning features to predict: *"Which strategy will be most profitable today?"*

```python
# ml/models/strategy_selector.py

class StrategySelector:
    """
    Predicts which strategies have positive expected value today
    and reranks the priority list.
    """
    def __init__(self):
        # For each strategy: P(at least one profitable trade today)
        self.models = {
            strategy: LightGBMClassifier(...)
            for strategy in STRATEGIES
        }
    
    def rank_strategies(self, morning_features):
        probs = {
            s: m.predict_proba(morning_features)
            for s, m in self.models.items()
        }
        
        # Filter strategies with < 45% expected profitability
        viable = {s: p for s, p in probs.items() if p > 0.45}
        
        # Return ranked list
        return sorted(viable.keys(), key=lambda s: viable[s], reverse=True)
```

### Morning features

All of the morning regime features from §4, plus:
- Day-specific gap characteristics (size, direction, quality)
- Pre-open ATR estimate
- Overnight momentum score
- Prior week's strategy performance

### Integration

In `hybrid_run.py`:
```python
# OLD: fixed strategy order
strategies = [gap_fill, fvg, orb, ib, vwap_rev, vwap_bounce]

# NEW: ML-ranked at 9:00 AM
strategy_selector = StrategySelector.load()
strategies = strategy_selector.rank_strategies(morning_features)
# e.g. today's ranking: [orb, ib, fvg, vwap_bounce]  (gap_fill filtered out)
```

---

## 9. Phase 7 — Online Learning & Walk-Forward Retraining

### The problem with static ML models in trading

Markets change. A model trained on 2023–2024 data may be wrong on 2026 data. You need a system that:
1. Updates on new data automatically
2. Knows when it's out-of-distribution (don't trust the model on new regimes it hasn't seen)
3. Doesn't overfit to recent noise

### Walk-forward retraining protocol

```
Training window: 252 days (1 year)
Validation window: 63 days (1 quarter)  
Retrain frequency: Every 21 trading days (1 month)

Timeline:
  Day 0–252:   Initial training data
  Day 253–315: Initial validation
  Day 316:     Deploy model v1
  Day 337:     Add 21 new days, retrain on days 21–273, validate on 273–336
  Day 358:     Retrain on days 42–294, validate on 294–357
  ...
```

This is **expanding window** for the first year, then **rolling window** once you have 2+ years of data.

### Online update between retrains

```python
# ml/online_updater.py

class OnlineLearner:
    """
    Lightweight online update between full retrains.
    Uses gradient boosted model's leaf node assignments to update
    leaf weights without full retrain.
    """
    def __init__(self, model):
        self.model = model
        self.pending_updates = []
    
    def add_outcome(self, features, outcome):
        """Call after each trade completes."""
        self.pending_updates.append((features, outcome))
        
        if len(self.pending_updates) >= 5:
            self._apply_updates()
    
    def _apply_updates(self):
        X = np.array([f for f, o in self.pending_updates])
        y = np.array([o for f, o in self.pending_updates])
        
        # Partial fit: only update leaf weights, not tree structure
        # This is safe and fast — no overfitting risk
        self.model.fit(X, y, init_model=self.model)
        self.pending_updates = []
```

### Drift detection

```python
# ml/drift_detector.py

class DriftDetector:
    """
    Detects when current market is outside the training distribution.
    If drift detected, fall back to conservative hardcoded thresholds.
    """
    def __init__(self):
        self.feature_stats = {}  # mean/std per feature from training
    
    def check_drift(self, current_features):
        z_scores = {
            f: abs(current_features[f] - self.feature_stats[f]['mean']) 
               / self.feature_stats[f]['std']
            for f in current_features
        }
        
        # If >30% of features are > 2.5 sigma from training distribution
        out_of_dist = sum(z > 2.5 for z in z_scores.values()) / len(z_scores)
        
        return DriftResult(
            drift_detected=out_of_dist > 0.30,
            drift_score=out_of_dist,
            recommendation='use_hardcoded_fallback' if out_of_dist > 0.50 else 'use_ml'
        )
```

---

## 10. Phase 8 — New Feature Engineering

### Features to add that the current system doesn't have

These are not in any current file and represent genuinely new signal.

#### A. VIX Term Structure (Critical — free alpha)

```python
def compute_vix_term_structure():
    """
    VIX9D - VIX = short-term fear spike (inverted = short vol environment)
    VIX - VIX3M = medium-term slope
    VIX3M - VIX6M = long-term slope
    
    Inverted term structure (VIX9D > VIX > VIX3M) = market panic = skip mean reversion
    Normal structure (VIX9D < VIX < VIX3M) = healthy market = all strategies viable
    """
    vix_9d = yf.download('^VIX9D', period='5d')['Close'].iloc[-1]
    vix = yf.download('^VIX', period='5d')['Close'].iloc[-1]
    vix_3m = yf.download('^VIX3M', period='5d')['Close'].iloc[-1]
    
    return {
        'vix_term_slope_short': vix_9d - vix,    # negative = inverted = bad
        'vix_term_slope_long': vix - vix_3m,
        'vix_structure': 'inverted' if vix_9d > vix else 'normal',
    }
```

#### B. Opening Gap Quality Score

```python
def score_opening_gap(gap_pts, prior_close, overnight_range, vix):
    """
    Not all 2-point gaps are equal.
    A 2pt gap on a 20pt overnight range = nothing.
    A 2pt gap on a 4pt overnight range = significant.
    """
    gap_to_overnight_ratio = gap_pts / max(overnight_range, 1)
    gap_to_atr_ratio = gap_pts / compute_daily_atr()
    
    quality = (
        (0 if gap_to_overnight_ratio > 0.5 else 1) +  # gap wasn't just intranight drift
        (1 if gap_to_atr_ratio < 0.15 else 0) +        # gap is small enough to fill
        (1 if vix < 20 else 0) +                        # not panic environment
        (1 if prior_day_was_directional() else 0)       # clean continuation
    )
    return quality  # 0-4, use as feature
```

#### C. Intraday Momentum Fingerprint

```python
MOMENTUM_FEATURES = [
    # First 5 bars (25 min) after open
    'first_5bar_range',           # Total range 9:30–9:55
    'first_5bar_direction',       # Net direction (up/flat/down)
    'first_5bar_close_position',  # Where did 9:55 bar close in session range
    'first_5bar_rvol',            # RVOL vs prior 10 opens
    'first_5bar_vwap_distance',   # How far from VWAP?
    
    # First bar specifically
    'bar1_body_pct',              # Body / total range (engulfing = large body)
    'bar1_upper_wick',            # Rejection above
    'bar1_lower_wick',            # Rejection below
    'bar1_vs_overnight_high',     # Tested/broke overnight high?
    'bar1_vs_overnight_low',
    
    # Volume profile
    'open_volume_ratio',          # First 15min volume / daily average first 15min
    'poc_distance',               # Distance from 5-day POC (Point of Control)
]
```

#### D. Microstructure Features (from Databento — already have the feed)

```python
MICROSTRUCTURE_FEATURES = [
    'bid_ask_spread_avg',         # Last 5 min average spread
    'bid_ask_spread_trend',       # Widening or tightening?
    'trade_size_avg',             # Average trade size (large = institutional)
    'trade_count_per_bar',        # High count = lots of small orders = retail
    'aggressor_ratio',            # % of trades that were aggressive (market orders)
    'imbalance_score',            # Order book imbalance (bid qty / ask qty)
]
```

#### E. Cross-Asset Confirmation

```python
CROSS_ASSET_FEATURES = [
    'qqq_vs_spy_strength',        # QQQ relative strength vs SPY (NQ bias)
    'smh_strength',               # Already in scoring, make it continuous
    'xlk_strength',               # Already in scoring, make it continuous
    'iwm_nq_divergence',          # Small cap vs large cap (risk-on signal)
    'hyg_change',                 # HYG = high yield bonds (risk appetite)
    'tnx_intraday_change',        # 10yr yield change since open
    'dxy_intraday_change',        # DXY change since open
    'cl_change',                  # Crude oil (inflation/risk proxy)
]
```

---

## 11. Phase 9 — RL Agent for Intraday Adaptation

### What it is (and why it's Phase 9, not Phase 1)

A **reinforcement learning agent** that makes real-time decisions:
- When to enter (within the 5-min bar — not just "next open")
- Whether to skip a technically valid signal
- When to close early (before T1 or T2)
- When to pyramid (add to a winning position — not currently possible)

**Why Phase 9:** RL for trading is high-risk and requires extensive testing. The simpler ML models (Phases 1–7) give you 90% of the benefit with 10% of the complexity. Only add RL after the other phases are stable and you have enough data.

### Approach: Conservative RL with hard guardrails

```python
# ml/rl/trading_agent.py

class TradingAgent:
    """
    Uses Proximal Policy Optimization (PPO) — the most stable RL algorithm
    for finance, doesn't blow up like DQN.
    """
    # State space: all features from Phases 1-8
    # Action space: {skip, enter_1lot, enter_2lot, close_early, tighten_trail}
    # Reward: risk-adjusted PnL (Sharpe ratio per episode, not just raw PnL)
    
    # HARD GUARDRAILS (these override RL actions):
    # - Never enter if daily loss limit reached
    # - Never enter if drawdown < $300 buffer
    # - Never size > 2 lots regardless of RL recommendation
    # - Never extend stop loss past 25 pts
    
    def get_action(self, state):
        rl_action = self.policy.act(state)
        return self.apply_guardrails(rl_action, state)
```

### Training environment

Use your existing backtest engine as the RL environment:

```python
class TradingEnvironment(gym.Env):
    def __init__(self, bars_df, backtest_engine):
        self.bars = bars_df
        self.engine = backtest_engine
        self.current_bar = 0
        
    def step(self, action):
        state, pnl, done, info = self.engine.step(action)
        reward = self._compute_reward(pnl, info)
        return state, reward, done, info
    
    def _compute_reward(self, pnl, info):
        # Not just PnL — penalize drawdown heavily
        reward = pnl
        if info['hit_daily_loss']:
            reward -= 500  # Heavy penalty
        if info['consecutive_losses'] > 2:
            reward -= 50   # Moderate penalty
        return reward
```

---

## 12. Complete Hardcoded Parameter Migration Table

This table shows every hardcoded parameter, where it lives, and what replaces it.

| # | Parameter | File:Line | Current Value | ML Replacement | Phase |
|---|-----------|-----------|---------------|----------------|-------|
| 1 | gap_ratio threshold | quant_gap.py:79 | `< 0.20` | Signal classifier P(win) | 1 |
| 2 | gap_size min | quant_gap.py:71 | `>= 2.0 pts` | Signal classifier feature | 1 |
| 3 | gap_pct max | quant_gap.py:83 | `< 0.0055` | Signal classifier feature | 1 |
| 4 | Premarket bars | quant_gap.py:104 | `>= 3 bars` | Signal classifier feature | 1 |
| 5 | Premarket lookback | quant_gap.py:106 | `6 bars` | Learned optimal window | 1 |
| 6 | Gap stop buffer | quant_gap.py:120 | `± 2.0 pts` | Exit engine at-entry model | 4 |
| 7 | Gap target | quant_gap.py:134 | `× 0.5` | Exit engine T1 predictor | 4 |
| 8 | ORB PULLBACK_ZONE | quant_orb.py:32 | `0.25` | Signal classifier feature | 1 |
| 9 | ORB PULLBACK_BARS | quant_orb.py:33 | `4 bars` | Learned optimal wait | 1 |
| 10 | ORB min_range | quant_orb.py:86 | `max(3.0, 0.025×ATR)` | Signal classifier | 1 |
| 11 | ORB max_range | quant_orb.py:87 | `0.50×ATR` | Signal classifier | 1 |
| 12 | ORB retrace_depth | quant_orb.py:147 | `0.75` | Signal classifier feature | 1 |
| 13 | ORB stop (pullback) | quant_orb.py:159 | `orb_high − 2.0` | Exit engine | 4 |
| 14 | ORB target mult | quant_orb.py:165 | `min(1.0×, 3.0×risk)` | Exit engine | 4 |
| 15 | IB min_range | quant_ib.py:80 | `max(3.0, 0.025×ATR)` | Signal classifier | 1 |
| 16 | IB max_range | quant_ib.py | `0.45×ATR` | Signal classifier | 1 |
| 17 | IB time stop | quant_ib.py:97 | `11:30 AM` | Regime-adaptive cutoff | 2 |
| 18 | VWAP SIGNAL_STD | quant_vwap.py:37 | `1.5σ` | Signal classifier | 1 |
| 19 | VWAP STOP_STD | quant_vwap.py:38 | `2.0σ` | Exit engine | 4 |
| 20 | VWAP min_dev | quant_vwap.py:71 | `max(15.0, 0.05×ATR)` | Signal classifier | 1 |
| 21 | VWAP max_dev | quant_vwap.py:72 | `min(30.0, 0.12×ATR)` | Signal classifier | 1 |
| 22 | VWAP stop_dist | quant_vwap.py:73 | `max(8.0, 0.06×ATR)` | Exit engine | 4 |
| 23 | VIX gate (breakout) | quant_engine.py:331 | `VIX < 25` | Regime engine | 2 |
| 24 | VIX gate (mean rev) | inst_engine.py:409 | `VIX < 22` | Regime engine | 2 |
| 25 | CHANDELIER_MULT | hybrid_engine.py:107 | `3.0×` | Exit engine | 4 |
| 26 | OFI_HARD_BLOCK_Z | hybrid_engine.py:106 | `2.0` | Neural confidence scorer | 3 |
| 27 | ABSORPTION_THRESH | hybrid_engine.py:108 | `0.4` | Neural confidence scorer | 3 |
| 28 | GAP_LARGE_ATR_MULT | hybrid_engine.py:109 | `1.2×` | Signal classifier | 1 |
| 29 | GAP_MONDAY_ATR_MULT | hybrid_engine.py:110 | `0.7×` | Signal classifier feature | 1 |
| 30 | ATR lookback | all engines | `14 bars` | Optimized per regime | 2 |
| 31 | 20-point score system | hybrid_engine.py:358 | Linear sum | Neural confidence scorer | 3 |
| 32 | Score threshold | hybrid_engine.py | `>= 6` | Calibrated P(win) threshold | 3 |
| 33 | 2-lot threshold | hybrid_engine.py | `>= 19` | Bayesian sizer | 5 |
| 34 | BEAR_THRESHOLD | inst_hmm.py:58 | `0.55` | Regime engine | 2 |
| 35 | STRESS_THRESHOLD | inst_hmm.py:59 | `0.60` | Regime engine | 2 |
| 36 | BNS_THRESHOLD | inst_harv.py:30 | `0.20` | Neural confidence (feature) | 3 |
| 37 | Stop mult (low vol) | inst_harv.py:101 | `0.85` | Exit engine | 4 |
| 38 | Stop mult (high vol) | inst_harv.py:93 | `1.6` | Exit engine | 4 |
| 39 | Stop mult (crisis) | inst_harv.py:105 | `1.3` | Exit engine | 4 |
| 40 | GEX_HIGH | inst_gex.py:25 | `1.10` | Regime feature (continuous) | 2 |
| 41 | GEX_LOW | inst_gex.py:26 | `0.95` | Regime feature (continuous) | 2 |
| 42 | VPIN_THRESHOLD | inst_vpin.py:28 | `0.65` | Neural confidence (feature) | 3 |
| 43 | OFI_WINDOW | inst_ofi.py:21 | `20 bars` | Optimized per strategy | 1 |
| 44 | Z_CONFIRM | inst_ofi.py:22 | `1.5` | Neural confidence (feature) | 3 |
| 45 | Z_BLOCK | inst_ofi.py:23 | `1.5` | Neural confidence (feature) | 3 |
| 46 | TSMOM_THRESHOLD | inst_tsmom.py:25 | `0.001` | Neural confidence (feature) | 3 |
| 47 | TSMOM_HIGH | inst_tsmom.py:26 | `0.003` | Neural confidence (feature) | 3 |
| 48 | ES direction thresh | inst_leadlag.py:24 | `0.0002` | Neural confidence (feature) | 3 |
| 49 | ES lookback_bars | inst_leadlag.py:27 | `3 bars` | Optimized feature | 3 |
| 50 | AVWAP_NEAR_ATR | inst_avwap.py:29 | `0.025` | Neural confidence (feature) | 3 |
| 51 | VA CONFIRM_BARS | inst_va_rule.py:37 | `3 bars` | Signal classifier | 1 |
| 52 | VA MIN_TARGET | inst_va_rule.py:38 | `5.0 pts` | Signal classifier | 1 |
| 53 | WR_SIZE_UP | bot_memory.py:29 | `0.75` | Bayesian sizer | 5 |
| 54 | WR_SIZE_DOWN | bot_memory.py:30 | `0.50` | Bayesian sizer | 5 |
| 55 | LOOKBACK | bot_memory.py:31 | `20 trades` | Bayesian (regime-split) | 5 |
| 56 | REGIME_LOOKBACK | bot_memory.py:32 | `10 trades` | Bayesian (regime-split) | 5 |
| 57 | MAX_CONSEC_L | bot_memory.py:33 | `3 losses` | Bayesian sizer signal | 5 |
| 58 | Kelly lookback | inst_kelly.py:26 | `50 trades` | Bayesian full posterior | 5 |
| 59 | Kelly max_contracts | inst_kelly.py:27 | `2` | Keep (prop firm limit) | N/A |
| 60 | Strategy priority | hybrid_engine.py | Fixed order | Strategy selector | 6 |
| 61 | T1/T2 split | all engines | `50/50` | Exit engine | 4 |
| 62 | T1 distance | all engines | `1× risk` | Exit engine | 4 |
| 63 | DIRECTION_LOCK | monitor.py:230 | `20 min` | Regime-adaptive | 2 |

---

## 13. Implementation Order & Dependencies

### Recommended sequence

```
WEEK 1–2: Setup & Data Pipeline
  - Create ml/ directory structure
  - Build feature extraction pipeline (extract_features.py)
  - Generate labeled training data from backtest runs
  - Set up model versioning (pickle + metadata JSON)

WEEK 3–4: Phase 1 (Signal Classifiers) ← HIGHEST IMPACT FIRST
  - Train one classifier per strategy
  - Walk-forward validate on 2022–2025 data  
  - A/B test: run old system and new system in parallel on paper
  - Deploy if validation Sharpe > current Sharpe

WEEK 5–6: Phase 2 (Regime Engine)
  - Collect morning feature set
  - Label historical days with regime types
  - Train and validate
  - Integrate with existing regime gating

WEEK 7–8: Phase 3 (Neural Confidence Scorer)
  - Requires Phase 1 output (ml_signal_confidence as input)
  - Requires Phase 2 output (regime_state as input)
  - Most complex — set aside 2 full weeks

WEEK 9: Phase 5 (Bayesian Sizer)
  - Relatively self-contained
  - Can be deployed independently of Phases 1–3

WEEK 10: Phase 4 (Adaptive Exit Engine)
  - Requires Phase 1+2+3 features
  - Start with just exit_chandelier_mult prediction (easiest)
  - Add T1 distance and split prediction later

WEEK 11–12: Phase 6 (Strategy Selector)
  - Uses outputs from Phases 1–3 as features
  - Relatively simple once others are done

ONGOING: Phase 7 (Online Learning)
  - Set up automated weekly retraining job
  - Drift detection runs daily at 9:00 AM

FUTURE: Phases 8–9 (New Features + RL)
  - Add new features incrementally
  - RL only after 1+ year of live ML data
```

### Dependency graph

```
Phase 1 (Signal Classifier)
    └── Phase 3 (Confidence Scorer)
            └── Phase 4 (Exit Engine)
            └── Phase 5 (Bayesian Sizer)

Phase 2 (Regime Engine)
    └── Phase 3 (Confidence Scorer)
    └── Phase 6 (Strategy Selector)
    └── Phase 5 (Bayesian Sizer)

Phase 7 (Online Learning)
    └── depends on all deployed models
```

---

## 14. File Structure for New ML Layer

```
trading_strategy/
├── ml/
│   ├── __init__.py
│   ├── features/
│   │   ├── extract_features.py         # Master feature extractor
│   │   ├── morning_features.py         # Pre-open regime features
│   │   ├── signal_features.py          # Per-signal features
│   │   ├── exit_features.py            # Bar-by-bar trade features
│   │   └── cross_asset.py              # VIX term structure, bonds, etc.
│   │
│   ├── models/
│   │   ├── signal_classifier.py        # Phase 1: per-strategy classifiers
│   │   ├── regime_engine.py            # Phase 2: morning regime prediction
│   │   ├── confidence_scorer.py        # Phase 3: neural scorer
│   │   ├── exit_engine.py              # Phase 4: dynamic exits
│   │   ├── bayesian_sizer.py           # Phase 5: Bayesian Kelly
│   │   ├── strategy_selector.py        # Phase 6: strategy ranking
│   │   └── base_model.py               # Shared save/load/version logic
│   │
│   ├── training/
│   │   ├── label_generator.py          # Generate training labels from backtest
│   │   ├── train_signal_classifiers.py
│   │   ├── train_regime_engine.py
│   │   ├── train_confidence_scorer.py
│   │   ├── train_exit_engine.py
│   │   ├── train_bayesian_sizer.py
│   │   └── walk_forward_validator.py   # Shared walk-forward logic
│   │
│   ├── online/
│   │   ├── online_updater.py           # Phase 7: online learning
│   │   ├── drift_detector.py           # OOD detection
│   │   └── retrain_scheduler.py        # Automated weekly retrain
│   │
│   ├── rl/ (Phase 9 — build later)
│   │   ├── trading_env.py
│   │   ├── ppo_agent.py
│   │   └── train_rl.py
│   │
│   ├── saved_models/                   # Serialized model files
│   │   ├── signal_classifier_gap_v1.pkl
│   │   ├── signal_classifier_orb_v1.pkl
│   │   ├── regime_engine_v1.pkl
│   │   ├── confidence_scorer_v1.pkl
│   │   └── ...
│   │
│   └── evaluation/
│       ├── backtest_comparison.py      # Old vs new system comparison
│       ├── model_metrics.py            # WR, Sharpe, drawdown by model version
│       └── shap_analysis.py            # SHAP feature importance plots
│
└── (existing files unchanged during integration)
```

---

## 15. Training Data Setup

### How much data do you have?

From the codebase, the backtest covers ~2 years of 5-min NQ bars. Here's roughly how many labeled examples you can generate:

| Strategy | Approximate Signals/Year | Training Labels |
|----------|--------------------------|-----------------|
| Gap Fill | 50–70 signals | 100–140 examples |
| ORB | 80–120 signals | 160–240 examples |
| IB | 60–90 signals | 120–180 examples |
| VWAP Rev | 40–60 signals | 80–120 examples |
| VWAP Bounce | 30–50 signals | 60–100 examples |
| FVG | 50–80 signals | 100–160 examples |

**Problem:** 100–200 examples per strategy is thin for deep learning. This is why we use:
1. **LightGBM** (not neural nets for signal classification) — handles small data well
2. **Relaxed threshold data generation** — capture near-misses to double the training set
3. **Cross-strategy features** — share learning across strategies where signals overlap
4. **Regime-stratified cross-validation** — don't let one regime dominate training

### Data augmentation

```python
def augment_training_data(raw_signals):
    """
    Augment training data by perturbing features within realistic bounds.
    NOT on price data — on derived features.
    """
    augmented = []
    for signal in raw_signals:
        # Add ±5% noise to continuous features
        for _ in range(3):  # 3 augmented versions per original
            noisy = signal.copy()
            for feat in CONTINUOUS_FEATURES:
                noisy[feat] *= np.random.uniform(0.95, 1.05)
            augmented.append(noisy)
    return raw_signals + augmented
```

### Expanding data over time

Set up an automated pipeline:
1. Every day, after session close, log all signals (taken and skipped) to `ml/data/daily_signals.csv`
2. Weekly, regenerate training labels for any trades that closed out
3. Monthly, retrain all models with the accumulated data
4. After 6 months, you'll have 300–500 examples per strategy — enough for high-confidence models

---

## 16. Live Integration Points

### Changes to existing files (minimal invasive approach)

The goal is to add ML as an **optional layer on top** without breaking existing logic. Use feature flags:

```python
# In a new file: ml/config.py
ML_ENABLED = {
    'signal_classifier': True,     # Phase 1
    'regime_engine': True,         # Phase 2
    'confidence_scorer': False,    # Phase 3 (enable after testing)
    'exit_engine': False,          # Phase 4
    'bayesian_sizer': False,       # Phase 5
    'strategy_selector': False,    # Phase 6
}
FALLBACK_ON_ERROR = True           # If model crashes, use hardcoded logic
```

### Integration in hybrid_engine.py

```python
# At the top of HybridEngine.generate_signals():
from ml.config import ML_ENABLED
from ml.models.signal_classifier import SignalClassifier
from ml.models.regime_engine import RegimeEngine

if ML_ENABLED['regime_engine']:
    regime_snapshot = regime_engine.predict_morning(morning_features)
else:
    regime_snapshot = None  # falls back to existing logic

# ... existing signal generation ...

# After signal candidate generated:
if ML_ENABLED['signal_classifier'] and signal_candidate:
    clf = SignalClassifier.load(signal_candidate.strategy)
    signal_candidate['ml_confidence'] = clf.predict_proba(features)
    
    if signal_candidate['ml_confidence'] < THRESHOLDS[signal_candidate.strategy]:
        continue  # Skip this signal

# Confidence scoring:
if ML_ENABLED['confidence_scorer']:
    confidence = confidence_scorer.predict(signal_candidate, regime_snapshot)
else:
    confidence = compute_legacy_20pt_score(signal_candidate) / 20  # normalize to 0-1
```

### Changes to monitor.py

The live monitor needs minimal changes — it mostly calls the engines. The main addition:

```python
# In monitor.py, before printing trade signal:
if ML_ENABLED['bayesian_sizer']:
    contracts = bayesian_sizer.get_contracts(
        strategy=signal.strategy,
        regime_key=make_regime_key(regime_snapshot, day_of_week),
        confidence=signal.ml_confidence,
        drawdown_state=get_drawdown_state()
    )
else:
    contracts = legacy_kelly_sizing(signal)  # existing logic
```

---

## 17. Risk Guardrails You Must Never Remove

No matter what any ML model says, these rules are hardcoded and inviolable:

```python
PROP_FIRM_HARD_LIMITS = {
    'max_daily_loss_usd': 150,      # NEVER override
    'max_stop_pts': 25,             # NEVER override
    'max_contracts': 2,             # NEVER override
    'max_trades_day': 3,            # NEVER override
    'trailing_drawdown_floor': 1000,# NEVER override — account gets blown
    'consistency_buffer': 0.38,     # NEVER override — eval fails
}

def apply_hard_limits(trade, account_state):
    """This function runs AFTER all ML models. Cannot be disabled."""
    if account_state.daily_pnl <= -150:
        return None  # Block all trades, period
    
    if account_state.drawdown_buffer < 100:
        return None  # Too close to floor
    
    trade.contracts = min(trade.contracts, 2)
    trade.stop_pts = min(trade.stop_pts, 25)
    
    return trade
```

**The ML is the brain. The risk limits are the skull. The skull doesn't negotiate.**

---

## Summary: Expected System Improvements

| Metric | Current | After All Phases | How |
|--------|---------|-----------------|-----|
| Win Rate | 76.8% | 81–83% | Signal classifier filters bad entries |
| Avg Winner | ~1.8R | ~2.1–2.3R | Exit engine optimizes trails |
| Max Drawdown | ~$350 | ~$220 | Bayesian sizer reduces size on uncertainty |
| Daily False Signals | 3–4 | 1–2 | Regime engine filters wrong-strategy days |
| "Flat" Trades (T1 only) | ~40% | ~28% | Better trail multiplier from exit engine |
| Strategy Selection Accuracy | Fixed order | 70%+ best-strat match | Strategy selector |

**Combined expected effect:** Same or fewer total trades, higher quality per trade, better sizing precision, and exits that actually capture the full move. The goal isn't to trade more — it's to be right more often and capture more when you're right.

---

---

## 18. Research-Backed Implementation Guidance — Read Before Starting

After writing the phase plan above, I went and researched how the quant industry actually builds exactly this kind of system — "I have rule-based signals, how do I layer ML on top correctly without blowing myself up." Here's what changes based on that research, and the concrete tools to use.

### 18.1 — The single most important reframe: This is a textbook "Meta-Labeling" problem

Marcos López de Prado (former head of ML at Guggenheim, Cornell professor) wrote the book on exactly this situation in *Advances in Financial Machine Learning* (2018). His framework, called **meta-labeling**, splits the trading decision into two separate models:

1. **Primary model** — decides direction/side (long or short). **You already have this.** It's your gap fill, ORB, IB, VWAP, FVG strategies. They're rule-based and high-recall (they fire often, ~76.8% WR already).
2. **Secondary model (the "meta-model")** — a binary ML classifier that looks at a signal the primary model just generated and answers one question only: *"Should I actually take this trade, yes or no?"*

This is **precisely** what Phase 1 (Signal Classifier) and Phase 3 (Confidence Scorer) in this plan are — but meta-labeling gives you the proven, named methodology and a pre-built toolkit for it, instead of building from scratch. The research is unambiguous that this approach:
- Improves precision (win rate) **without** killing recall (you don't lose your good trades)
- Is specifically designed for cases where you already have a working strategy and want an ML "second opinion" layer
- Avoids the #1 way retail ML trading fails: trying to get ML to predict price direction from scratch (very hard, ~50% accuracy per the MNQ-specific 2026 study below)

**Practical takeaway: Don't build Phase 1 as "replace the strategy's entry logic with an ML classifier." Build it as "keep every existing strategy exactly as-is, and bolt a yes/no ML gate onto its output."** This is lower-risk, easier to validate (you can A/B test gate-on vs gate-off on the *same* signals), and is the version of this idea that has actually worked in production quant shops.

```python
# This is the correct mental model for Phase 1:

signal = gap_fill_strategy.detect(bars)   # UNCHANGED — your existing 77.8% WR logic
if signal:
    take_it = meta_model.predict(meta_features(signal, bars))  # NEW — binary yes/no
    if take_it:
        execute(signal)
    else:
        log_skipped(signal)  # still log it — this becomes future training data
```

### 18.2 — Use the "Triple-Barrier Method" to label your training data correctly

One subtle bug that kills most homemade trading-ML projects: **how do you label a trade as "win" or "loss" for training?** If you label based on "price X bars later," you bake in an arbitrary holding period that doesn't match how your strategies actually exit (two-target system with trailing stops).

López de Prado's **Triple-Barrier Method** solves this — and it maps almost perfectly onto your existing two-target exit system:
- **Upper barrier** = your T1/target level (label = win)
- **Lower barrier** = your stop level (label = loss)
- **Vertical barrier** = your time-stop (e.g., 12:00 PM session cutoff, or 300-bar max from `quant_engine.py`)

Whichever barrier gets touched first determines the label. This is a *much* better label than "+1 if price went up 10 points in 2 hours" because it labels the trade exactly the way your system would have actually exited it.

### 18.3 — Use `mlfinlab`/`mlfinpy` instead of building labeling from scratch

There's an open-source library, originally `mlfinlab` (Hudson & Thames — now a paid product) with an actively maintained open fork called **`mlfinpy`**, that implements:
- Triple-barrier labeling (`mlfinpy.labeling`)
- Meta-labeling utilities
- **Purged K-Fold Cross-Validation** (critical — see 18.4)
- CUSUM event filters (for finding "interesting" bars worth labeling)

```bash
pip install mlfinpy
```

```python
from mlfinpy.labeling import get_events, get_bins

# triple_barrier_events maps your existing T1/stop/time-stop directly:
events = get_events(
    close=bars['close'],
    t_events=signal_timestamps,           # when your strategies fired
    pt_sl=[1.0, 1.0],                      # profit-take / stop-loss multiples (your 1R system)
    target=atr_normalized_risk,            # your existing ATR-based risk sizing
    min_ret=0.0,
    num_threads=1,
    vertical_barrier_times=session_end_times,  # your 12:00 PM cutoff
)
labels = get_bins(events, bars['close'])   # 1 = win, 0 = loss — ready to train on
```

This alone will save you weeks of subtle labeling-bug debugging.

### 18.4 — Use Purged K-Fold Cross-Validation, NOT standard `train_test_split` or `KFold`

**This is the single most common mistake that makes a backtest lie to you.** Standard k-fold cross-validation shuffles data randomly — which means a training fold can contain bars from *minutes after* a test-fold bar. Your model "learns" from the future and then looks brilliant in validation, then falls apart live. This is called **leakage**, and it is the #1 reason ML trading strategies look amazing in research and fail in production.

`mlfinpy`/`mlfinlab` implements **Purged K-Fold CV** — it removes ("purges") training samples whose label-determination window overlaps with the test set, plus an "embargo" period after each test fold. Use this for every single model in this plan, no exceptions:

```python
from mlfinpy.cross_validation import PurgedKFold

cv = PurgedKFold(
    n_splits=5,
    samples_info_sets=events['t1'],   # when each label's outcome was actually known
    pct_embargo=0.02                   # 2% embargo buffer between train/test
)
```

Combine this with the **walk-forward validation already specified in Phase 7** of this plan (§9) — purged CV for hyperparameter tuning, walk-forward for the final out-of-sample check before deployment.

### 18.5 — Confirmed: LightGBM is the right call, but tune it specifically for your dataset size

Research confirms LightGBM is the standard choice for this kind of tabular, small-to-medium financial dataset — but it has a specific failure mode you need to guard against given you'll have only ~100-250 labeled examples per strategy in year one:

> LightGBM's leaf-wise tree growth is more accurate but **overfits aggressively below ~10,000 rows**. With datasets this small, cap complexity hard.

**Concrete settings to start with (tighter than typical defaults):**
```python
params = {
    'max_depth': 4,              # NOT 6-8 — your data is too small for deep trees
    'num_leaves': 12,            # roughly 2^max_depth, keep conservative
    'min_child_samples': 40,     # up from typical 20 — "quickest way to tame overfitting on noisy data"
    'learning_rate': 0.02,
    'n_estimators': 300,
    'subsample': 0.7,
    'colsample_bytree': 0.6,
    'reg_alpha': 0.3,            # L1 — push harder than the 0.1 I specified earlier
    'reg_lambda': 1.0,           # L2 — push harder than the 0.5 I specified earlier
    'early_stopping_rounds': 30, # stop the moment validation loss plateaus
}
```
If results still look unstable with under ~150 examples, fall back to **XGBoost with `max_depth=3`** or even plain **logistic regression with L2** — boring, but far less likely to memorize noise on a 150-row dataset. A simple model that's right 56% of the time beats a complex model that's "right" 70% of the time in-sample and 50% live.

### 18.6 — The honest red flag you need to know about: a 2026 study tested this exact thing on MNQ and it didn't work

I found a paper from 2026 — *"Sequential Structure in Intraday Futures Data: LSTM vs Gradient Boosting on MNQ"* — that is about as close to your exact use case as research gets: 5-minute MNQ OHLCV bars, 944 trading days (2021-2025), gradient boosting vs. LSTM, walk-forward validated. **Their finding: no configuration beat the 51.8% base rate for predicting next-bar direction. LSTM hit 50.6%, gradient boosting 50.0-50.9%.**

This is not a reason to abandon the plan — it's a reason to be precise about *what* you're asking ML to predict:

- ❌ **"Predict whether the next bar/next 2 hours will go up or down from raw OHLCV"** — this is what that paper tried, and it's near-impossible. Price direction from price alone is close to a random walk at 5-minute resolution. This confirms your instinct that the *strategies* (gap fill, ORB, etc. — which encode real structural edges like institutional opening-range behavior) are the right place for the "alpha," not a generic price predictor.
- ✅ **"Given that my rule-based strategy already fired a signal (meaning real structure was detected), will THIS SPECIFIC INSTANCE of it work, based on regime/confluence/microstructure context?"** — this is meta-labeling, and it is a fundamentally easier and better-posed question, because you're not fighting the random walk — you're refining an edge that's already been found.

**Bottom line: the research validates the meta-labeling reframe in 18.1 and is a warning against ever trying to replace your strategies' core detection logic with a generic price-direction model.** Keep the alpha-generation in the rule-based strategies (where your 76.8% WR already comes from); use ML only to filter, size, and exit.

### 18.7 — Realistic expectations and the "too good to be true" check

Industry research is blunt about why most homemade trading ML fails, and two specific warnings apply directly to you:

1. **Search bias / multiple testing**: Every time you try a new feature set, threshold, or model variant and check its backtest score, you're "spending" statistical significance. Test 50 feature combinations and 1-2 will look great by pure chance. **Mitigation: decide your feature set and model config BEFORE looking at validation results, lock it, test once. If you must iterate, keep a held-out "final exam" dataset you only touch once, at the very end, before going live.**
2. **The "too clean" tell**: "Win rates above 80%, profit factors above 4.0, or equity curves with virtually no drawdown are almost always overfit." If your meta-model's validation results show it boosting your WR from 76.8% to, say, 95%, do not deploy it — that's a leakage bug, not a breakthrough. A realistic, honest improvement from a well-built meta-labeling layer is **+2 to +6 percentage points of WR** and a **modest reduction in max drawdown** — which is exactly the range I projected in the original plan's summary table. Treat any result wildly outside that range as a bug to hunt down, not a win to celebrate.

### 18.8 — Concrete library stack (what to actually `pip install`)

```bash
pip install lightgbm          # Phase 1, 2, 3, 6 — primary model library
pip install mlfinpy           # triple-barrier labeling + purged CV (open mlfinlab fork)
pip install scikit-learn      # isotonic calibration (Phase 3), metrics, pipelines
pip install shap              # interpretability — SEE WHY the model rejects/accepts a trade
pip install optuna            # Bayesian hyperparameter tuning (TPE — won 75% of trials vs. genetic in 2025 comparison study)
pip install mlflow            # model versioning/registry — tracks every retrain (Phase 7)
```

**On SHAP specifically — make this non-negotiable for every model you ship.** Before you ever let a model gate a real trade, run SHAP on its validation predictions and look at the top features driving its decisions. If the top feature is something nonsensical (e.g., "day of month" dominating a gap-fill model), that's a leakage/spurious-correlation red flag — kill it before it trades real money. If the top features are things like `ml_signal_confidence`, `rvol`, `vix_term_slope` — things that have a plausible causal story — that's a model worth trusting incrementally.

```python
import shap
explainer = shap.TreeExplainer(meta_model)
shap_values = explainer.shap_values(X_validation)
shap.summary_plot(shap_values, X_validation)  # run this before every deployment, always
```

### 18.9 — Revised Phase 1 build order (incorporating all of the above)

This supersedes the generic "Week 3-4" description in §13 with the specific, research-backed sequence:

1. Pick **one strategy** to pilot — recommend **ORB** (most signals/year, cleanest structural edge, `quant_orb.py`)
2. Log every signal it generates for ~4-8 weeks **without changing live behavior** — both taken and would-have-skipped (relax the hardcoded thresholds in a shadow/logging-only branch to capture near-misses too)
3. Label each logged signal with the **triple-barrier method** using `mlfinpy`, mapped to your actual T1/stop/12pm-cutoff exit rules
4. Train a **deliberately small** LightGBM model (`max_depth=4`, settings from §18.5) using **Purged K-Fold CV** via `mlfinpy`
5. Run **SHAP** — confirm the top features make causal sense, not just statistical sense
6. **Walk-forward validate** (§9 of this plan) on a held-out final period you have not looked at yet
7. If — and only if — validation shows a believable +2-6pp WR improvement (not +20pp — that's a bug): deploy as a **shadow gate** that logs its yes/no recommendation alongside the live trade, but does not yet block anything
8. After 4 more weeks of shadow-mode agreement-rate analysis, flip it to live gating on ORB only
9. Once ORB's meta-model is proven live for a full month, repeat steps 1-8 for the next strategy (recommend Gap Fill next — second-most signals, similarly clean structural edge)

This is slower than building all 6 strategy classifiers at once — intentionally. One proven, trusted meta-model beats six untested ones, and the infrastructure you build for ORB (logging, labeling, training, SHAP review, shadow-mode harness) is directly reusable for the rest.

---

**Sources consulted for this section:**
- [Sequential Structure in Intraday Futures Data: LSTM vs Gradient Boosting on MNQ (2026)](https://arxiv.org/abs/2605.17724) — the MNQ-specific null result on raw price prediction
- [Meta-Labeling — Wikipedia](https://en.wikipedia.org/wiki/Meta-Labeling) and [Hudson & Thames meta-labeling research](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/)
- [MlFinLab Triple-Barrier & Meta-Labeling docs](https://random-docs.readthedocs.io/en/latest/implementations/tb_meta_labeling.html) and [mlfinpy labeling docs](https://mlfinpy.readthedocs.io/en/latest/Labelling.html)
- [Purged cross-validation — Wikipedia](https://en.wikipedia.org/wiki/Purged_cross-validation)
- [LightGBM hyperparameter tuning to reduce overfitting](https://towardsdatascience.com/hyperparameter-tuning-to-reduce-overfitting-lightgbm-5eb81a0b464e/) and [common LightGBM mistakes](https://www.datasciencebase.com/supervised-ml/algorithms/gradient-boosting/LightGBM/common-mistakes/)
- [Why most ML trading strategies fail — search bias & overfitting](https://quant.fish/wiki/why-most-machine-learning-trading-strategies-fail/) and [GT-Score paper on overfitting](https://arxiv.org/pdf/2602.00080)
- [SHAP for LightGBM interpretability](https://github.com/ccomkhj/interpretable-lightgbm)
- [Bayesian (TPE) vs evolutionary hyperparameter optimization — TPE won 75% of trials](https://www.mdpi.com/2227-7390/14/5/761)

---

*Plan generated June 2026, updated with research-backed implementation guidance same month. Implement phases in order. Each phase is independently deployable. Start with §18.9's revised Phase 1 sequence — pilot ONE strategy (ORB) end-to-end as a meta-labeling shadow gate before scaling to the rest.*
