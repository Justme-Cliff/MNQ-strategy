# NQ Quant System — MNQ Day Trading

A quantitative, data-driven day trading system for NQ/MNQ futures. Eight statistically-backed strategies with ATR-normalized parameters that self-adapt to any volatility regime. Built for prop firm evaluations ($25k Tradeify) and live funded accounts.

## Strategies

| Strategy | Documented WR | When It Fires | Notes |
|---|---|---|---|
| Gap Fill | 93.1% | 9:35 AM | Tiny overnight gap + first-bar confirmation; no Mon |
| ORB | 72–83% | 9:35–11:30 | Opening range breakout pullback; VIX < 25, strong trend; no Mon/Tue longs |
| IB Breakout | 84% | 10:00–11:30 | Initial balance + C-period; any trend, direction-aligned |
| VWAP Rev AM | 66–67% | 9:45–11:30 | 1.5σ deviation mean-reversion; any trend, VIX < 25 |
| VWAP Rev PM | 66–67% | 1:30–3:30 PM | Same logic as AM, afternoon session |
| VWAP Bounce AM | 78–90% | 10:00–11:30 | Trend continuation at VWAP (±0.5σ); trending regimes only |
| VWAP Bounce PM | 78–90% | 1:30–3:30 PM | Same bounce logic, afternoon session |
| FVG | 60–75% | 9:45–11:30 | Fair Value Gap fill; neutral regime, no Mon |

All parameters are ATR-normalized — the same code works in 150-pt ATR (calm) and 350-pt ATR (crash) without tuning.

## Backtest Results (60-day, 5-min bars)

**Base System (quant_run.py)**

```
Total P&L:     $+1,143    Target: $1,500    Win rate: 78.6%  (44W / 12L of 56 trades)
Max drawdown:  $118        Avg win: $+46     Avg loss: $-40
Avg R:R:       1.85

By strategy:
  Gap Fill         15W / 3L   83.3%   P&L: $+247
  ORB               9W / 1L   90.0%   P&L: $+442   ← star performer
  IB Breakout       4W / 1L   80.0%   P&L: $+157
  VWAP Rev AM       3W / 2L   60.0%   P&L: $+51
  VWAP Rev PM       2W / 1L   66.7%   P&L: $+38
  VWAP Bounce AM    7W / 2L   77.8%   P&L: $+161
  VWAP Bounce PM    4W / 2L   66.7%   P&L: $+47
  FVG               0W / 0L     —     P&L: $0      (neutral regime window only)
```

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

## Risk Parameters (Prop Firm Safe)

```
Max risk per trade:   ATR-normalized; typically 15–30 pts × $2/pt = $30–$60 per MNQ
Max trades per day:   3
Max daily loss:       $150
VIX threshold:        25 (all strategies paused above)
Session:              9:30 AM – 4:00 PM ET (AM + PM windows)
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
quant_run.py                  — base backtest runner + full P&L analysis
hybrid_run.py                 — hybrid backtest (confidence scoring + 2-contract sizing)
inst_run.py                   — institutional signals backtest overlay
pine_script/quant_system.pine — TradingView indicator v3 + 16 alerts

backtest/
  quant_engine.py             — 8-strategy adaptive engine
  hybrid_engine.py            — hybrid engine (confidence scoring)
  inst_engine.py              — institutional signals engine
  data_loader.py              — yfinance NQ data loader

strategy/
  quant_regime.py             — EMA trend + adaptive ATR + regime classification
  quant_orb.py                — Opening Range Breakout (pullback entry)
  quant_ib.py                 — Initial Balance Breakout
  quant_gap.py                — Gap Fill
  quant_vwap.py               — VWAP Reversion + VWAP Bounce
  quant_fvg.py                — Fair Value Gap
  inst_gex.py                 — GEX (gamma exposure) signal
  inst_tsmom.py               — Time-series momentum signal
  inst_leadlag.py             — ES/NQ lead-lag signal
  inst_hmm.py                 — Hidden Markov Model regime
  inst_kelly.py               — Kelly position sizing
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
