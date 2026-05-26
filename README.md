# NQ Quant System — MNQ Day Trading

A quantitative, data-driven day trading system for NQ/MNQ futures. Eight statistically-backed strategies with ATR-normalized parameters that self-adapt to any volatility regime. Built for prop firm evaluations ($25k Tradeify) and live funded accounts.

## Strategies

| Strategy | Documented WR | When It Fires | Notes |
|---|---|---|---|
| Gap Fill | 93.1% | 9:35 AM | Tiny gap + first-bar confirmation + 50% extension target; no Mon |
| ORB | 72–83% | 9:35–12:00 | Pullback entry; ≥75% retrace depth required; no Mon/Tue longs |
| IB Breakout | 84% | 10:00–12:00 | Initial balance + C-period; 1.5× IB range target; proximity ≤30pts |
| VWAP Rev AM | 66–67% | 9:45–12:00 | 1.5σ deviation mean-reversion; min 15pts, max 30pts; VIX < 25 |
| VWAP Bounce AM | 78–90% | 10:00–12:00 | Trend continuation at VWAP (±0.5σ); trending regimes only |
| VWAP Bounce PM | 78–90% | 1:30–3:30 PM | Same bounce logic, afternoon session |
| FVG | 60–75% | 9:45–11:30 | Fair Value Gap fill; min 12pts; neutral regime, no Mon |

All parameters are ATR-normalized — the same code works in 150-pt ATR (calm) and 350-pt ATR (crash) without tuning. PM VWAP reversion removed (backtested at -$1 PnL over 60 days — no edge).

## Backtest Results (60-day, 5-min bars, post-improvements)

```
Total P&L:     $+947     Target: $1,500    Win rate: 76.8%  (43W / 13L of 56 trades)

By strategy:
  ORB                9 trades  WR 78%  P&L: $+690   ← star performer
  VWAP Bounce AM    20 trades  WR 80%  P&L: $+300
  Gap Fill           9 trades  WR 78%  P&L: $+42
  VWAP Bounce PM    14 trades  WR 71%  P&L: $-38
  IB Breakout        4 trades  WR 75%  P&L: $-48
```

Filters tightened this cycle: VWAP deviation bounds raised (5→15pt min), ORB pullback depth filter added, IB target extended to 1.5×, PM VWAP reversion disabled. Win rate held at 76.8%.

**Hybrid System (hybrid_run.py) — adds confidence scoring + position sizing**

```
Total P&L:     $+2,309    Target: $1,500    PASS ✓    Win rate: 81.0%  (47W / 11L of 58 trades)
Max drawdown:  $145
```

The hybrid system uses a 0–4 point confidence score (TSMOM + GEX + ES lead-lag + HMM). Score ≥ 3 trades 2 contracts.

## Quick Start

```bash
git clone https://github.com/Justme-Cliff/MNQ-strategy.git
cd MNQ-strategy
pip3 install -r requirements.txt
```

Run the backtest:

```bash
python3 quant_run.py          # base system
python3 hybrid_run.py         # hybrid with confidence scoring
python3 inst_run.py           # institutional signals overlay
```

## TradingView Pine Script (v3)

Load `pine_script/quant_system.pine` on a **5-minute MNQ chart** in TradingView.

The script shows:
- **ORB box** — first 5-min bar range
- **IB box** — 9:30–10:00 initial balance range
- **VWAP + bands** — session anchored; 1.5σ signal, 2.5σ stop reference, 0.5σ bounce zone (teal fill)
- **FVG zones** — bullish (green) and bearish (red) imbalances
- **Signal labels** — entry / stop / target printed on the chart for all 8 strategies
- **PM signals** — afternoon VWAP reversion and bounce alerts (toggle with `Show PM signals` input)
- **Regime dashboard** — top-right table: trend direction, VIX regime, ATR, active strategies, max trades/day

Set TradingView alerts on any of the **16 alert conditions** to get notified when a setup fires:

```
Gap Fill Long / Short
ORB Breakout Long / Short
IB Breakout Long / Short
VWAP Rev AM Long / Short
VWAP Rev PM Long / Short
VWAP Bounce AM Long / Short
VWAP Bounce PM Long / Short
FVG Long / Short
```

## Live Monitor

```bash
python3 monitor.py        # start from 9:20 AM ET
python3 -m journal.dashboard  # account dashboard (auto-refreshes every 5s)
```

The live monitor streams NQ price in real time via Yahoo Finance WebSocket (`^NDX` index, no CME delay) and derives NQ futures price using cost-of-carry:

```
NQ price ≈ NDX × e^((r - q) × T)
  r = live Fed funds rate from ^IRX (13-week T-bill)
  q = Nasdaq dividend yield (~0.5%)
  T = days to quarterly expiry (Mar/Jun/Sep/Dec 3rd Friday)
```

Accuracy: within $2–5 of live NQ futures. Basis recalibrates every 5 minutes.

Alert types:
- **Approaching** (10pts before level) — estimated SL/TP shown; place limit order now
- **Crossed** — level hit, limit should be filling
- **Signal** (bar close) — confirmed entry with exact E/S/T
- **Breakeven** — move SL to entry when price reaches 1× (2× for ORB) risk

## Risk Parameters (Prop Firm Safe)

```
Max risk per trade:   ATR-normalized; typically 15–30 pts × $2/pt = $30–$60 per MNQ
Max trades per day:   3
Max daily loss:       $150
Consistency cap:      activates after $100 total profit (≤38% of total in one day)
VIX threshold:        25 (all strategies paused above)
Session:              9:30 AM – 12:00 PM ET (AM window, prop firm rules)
```

## Regime Logic

The system gates each strategy by market regime so you only trade high-probability setups:

```
VIX < 25    → All 8 strategies available
VIX ≥ 25   → All strategies paused

EMA8 > EMA21 by 3%+  (strong bull) → ORB longs, Gap Fill longs, VWAP Bounce longs
EMA8 > EMA21 by 1–3% (bull)        → Gap Fill longs, VWAP Bounce longs
Neutral (±1%)                       → ORB, FVG, IB, VWAP Reversion
EMA8 < EMA21 by 1–3% (bear)        → Gap Fill shorts, VWAP Bounce shorts
EMA8 < EMA21 by 3%+  (strong bear) → ORB shorts, Gap Fill shorts, VWAP Bounce shorts

IB Breakout: any trend — direction filter ensures entries align with bias
VWAP Reversion: any trend — requires 1.5σ deviation from VWAP
VWAP Bounce: trending only (bull/strong_bull/bear/strong_bear)
```

Adaptive ATR uses `max(ATR_5, ATR_20)` — never stale during a spike, never inflated in a calm recovery.

## Key Design Decisions

**ORB target capping** — ORB entries use pullback-based stops (tight, ~2 pts below ORB high). Without a cap, target R:R becomes 10–14:1, which almost never fills. Target is now `min(orb_range × 1.0, risk × 3.0)` so max R:R is 3:1.

**Strategy-specific trailing stop** — ORB trailing stop moves to breakeven after 2× risk profit (`be_mult=2.0`). All other strategies use 1× (`be_mult=1.0`). This prevents premature breakeven lock on wide-target ORB trades while protecting mean-reversion wins.

**VWAP Bounce vs Reversion** — In trending markets, price rarely reaches 1.5σ below VWAP. The bounce strategy catches trend-continuation entries when price merely *tests* VWAP (within ±0.5σ), firing on almost every trending day.

**Day-of-week filters** — Gap Fill and FVG blocked on Mondays (gap bias data weak). ORB longs blocked Mon/Tue (statistically weakest days for NQ breakouts).

## Project Structure

```
monitor.py                    — live session monitor (real-time price + signals)
quant_run.py                  — base backtest runner + full P&L analysis
hybrid_run.py                 — hybrid backtest (confidence scoring + 2-contract sizing)
inst_run.py                   — institutional signals backtest overlay
pine_script/quant_system.pine — TradingView indicator v3 + 16 alerts

backtest/
  quant_engine.py             — adaptive engine (6 strategies, prop firm risk gates)
  hybrid_engine.py            — hybrid engine (confidence scoring)
  inst_engine.py              — institutional signals engine
  data_loader.py              — yfinance NQ loader + OHLC validation + holiday calendar

strategy/
  quant_regime.py             — EMA trend + adaptive ATR + rolling VWAP bands
  quant_orb.py                — Opening Range Breakout (pullback entry + depth filter)
  quant_ib.py                 — Initial Balance Breakout (1.5× target)
  quant_gap.py                — Gap Fill (+ 50% extension target)
  quant_vwap.py               — VWAP Reversion + VWAP Bounce (tightened deviation bounds)
  quant_fvg.py                — Fair Value Gap (min 12pts)
  inst_gex.py                 — GEX (gamma exposure) signal
  inst_tsmom.py               — Time-series momentum signal
  inst_leadlag.py             — ES/NQ lead-lag signal
  inst_hmm.py                 — Hidden Markov Model regime
  inst_kelly.py               — Kelly position sizing

risk/
  prop_firm_rules.py          — Tradeify rule tracker (drawdown, daily loss, consistency cap)

journal/
  trade_journal.py            — SQLite trade log (required field validation)
  dashboard.py                — live account dashboard (auto-refreshes every 5s)

yahoo_ws_feed.py              — real-time ^NDX WebSocket + cost-of-carry NQ basis
notifications.py              — macOS sound + popup alerts (0.5s timeout)
fast_feed.py                  — price feed selector (WS or yfinance fallback)
```

## Research Basis

| Strategy | Source |
|---|---|
| Gap Fill 93.1% | 2,791 NQ sessions 2015–2025 |
| ORB 72–83% | Toby Crabel (1990), Edgeful ES, Unger Academy NQ |
| IB 84% | 2,686 ES / 2,833 NQ sessions 2015–2025 |
| VWAP Rev 66–67% | Statistical mean-reversion, σ-band sizing (Bollinger, 25-yr ES backtest) |
| VWAP Bounce 78–90% | Trend continuation at dynamic support/resistance (VWAP) |
| FVG 60–75% | Edgeful YM study + advanced imbalance filtering |
