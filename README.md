<div align="center">

# Isogeny Alpha System
### by Kairos Capital Research

**Institutional-grade systematic intraday trading framework for MNQ futures**

`MNQ · 9:30 AM – 12:00 PM ET · CME Group · Tradeify $25k`

</div>

---

## Performance Summary

| System | Trades | Win Rate | Net P&L | Avg R:R | Max DD | Target |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| Base (no filters) | 59 | 81.4% | $+1,687 | 3.14x | $87 | ✓ |
| Institutional (hard blocks only) | 18 | 66.7% | $+804 | 3.23x | $56 | ✗ |
| **Isogeny Alpha v7.0** | **43** | **76.7%** | **$+2,499** | **4.23x** | **$221** | **✓** |

> **Walk-Forward Efficiency: 201%** — the system performed better on data it had never seen (OOS: 14 trades, 71.4% WR, $808 P&L) than on the in-sample period. Edge is structural, not overfit.

---

## Charts

### Master Dashboard — Equity Curve + Drawdown + System Metrics

![Master Dashboard](backtest_charts/01_equity_curve.png)

---

### Alpha Generation Surface — Win Rate Across VIX × Confidence Score

![Alpha Generation Surface](backtest_charts/02_drawdown.png)

---

### Strategy Performance Matrix

![Strategy Breakdown](backtest_charts/03_strategy_breakdown.png)

---

### Returns Statistical Analysis

![Returns Distribution](backtest_charts/04_pnl_distribution.png)

---

### Rolling Performance Metrics — Win Rate / Avg P&L / Sharpe

![Rolling Metrics](backtest_charts/05_rolling_winrate.png)

---

### Win Rate Heatmap — Day × Strategy

![Heatmap](backtest_charts/06_winrate_heatmap.png)

---

### Monte Carlo Simulation (500 paths) + VIX Sensitivity

![Monte Carlo](backtest_charts/07_vix_scatter.png)

---

### Factor Analysis — 20-Point Scoring Hit Rates

![Factor Analysis](backtest_charts/08_rr_distribution.png)

---

### Daily P&L Calendar

![Calendar](backtest_charts/09_monthly_calendar.png)

---

### Strategy Equity Curves + Win/Loss Sequence

![Strategy Curves](backtest_charts/10_strategy_equity_curves.png)

---

## How It Works

Six intraday strategies filtered through a **20-point institutional confidence scoring layer**. Every signal passes through **11 hard blocks** before reaching the trader. The **two-target exit system** locks 50% profit at T1 (1R) and trails the rest with a 3× intraday ATR Chandelier stop — converting the 44% breakeven-trade problem into real captured P&L.

### Signal Pipeline

```
Raw Data  →  Regime Layer  →  Strategy Detectors  →  Hard Blocks  →  20-Point Scorer  →  Notification
(5m OHLCV)   (trend/vol/HMM)  (6 strategies)         (11 filters)    (skip/1-lot/2-lot)  (y/n confirm)
```

### Strategies (Priority Order)

| # | Strategy | Documented WR | Session Window | Edge Source |
|:--|:--|:--:|:--|:--|
| 1 | **Gap Fill** | 77.8% (tiny gaps) | 9:35 AM | Institutional rebalancing to prior close. Tiny gaps (<0.3x ATR) fill 77.8% of sessions |
| 2 | **FVG** (Fair Value Gap) | 60–75% | 9:45–11:30 AM | Unfinished auction zones. Institutions buy/sell missed prices on return |
| 3 | **ORB Pullback** | 72–83% | 9:35 AM–noon | Opening range breakout with pullback entry — 3:1 R:R vs 1.5:1 direct entry |
| 4 | **IB Breakout** | 84% single-direction | 10:00–noon | Post-initial-balance directional conviction. 97% of NQ sessions break IB |
| 5 | **VWAP Bounce** | 75–80% | 10:00 AM–noon | Trend continuation as price tests VWAP as dynamic support/resistance |
| 6 | **80% Value Area Rule** | ~80% | 9:45–11:30 AM | Dalton Capital Management 30-year documented edge. $470 P&L from 4 trades |

---

## The 20-Point Confidence Scoring System

Every signal is scored 0–21 (20 signals + 1 memory bonus).

```
Score <= 5    →  SKIP          (insufficient institutional backing)
Score  6–15  →  1 MNQ contract (standard size)
Score >= 16   →  2 MNQ contracts (full institutional consensus)
```

| # | Signal | What It Measures | Source |
|:--|:--|:--|:--|
| 1 | **TSMOM** | First 30-min return direction | Moskowitz et al. (2012) |
| 2 | **GEX** | Dealer gamma exposure regime (mean-rev vs breakout) | VXN/VIX ratio |
| 3 | **ES Lead-Lag** | ES futures confirming NQ direction | Lo & MacKinlay (1990) |
| 4 | **HMM** | 5-state latent market regime (strong_bull→bear) | Ang & Bekaert (2002) |
| 5 | **CVD Divergence** | Cumulative delta distribution/accumulation | Cont et al. (2014) |
| 6 | **Overnight Range** | Expansion vs rotation day type | CME auction theory |
| 7 | **VIX Term Structure** | Contango/backwardation regime | VIX/VIX3M |
| 8 | **XLK/SPY Sector RS** | Tech sector institutional flow direction | Daily closes |
| 9 | **DXY + TNX Macro** | Dollar + yield headwind/tailwind for NQ | Daily closes |
| 10 | **NQ/ES Spread** | NQ overextended vs ES (20d z-score) | Stat-arb |
| 11 | **Session Conviction** | First 30-min magnitude predicts day type | Gao et al. (2018) |
| 12 | **Open Type** | Drive/auction/reversal classifier | Steidlmayer (CME) |
| 13 | **RVOL** | Time-of-day adjusted volume (same 5-min slot, 20 sessions) | Internal |
| 14 | **OCC** | Opening candle direction (84% day-continuation on NQ) | 10yr NQ database |
| 15 | **Absorption** | Wyckoff effort vs result — institutional limit order walls | Wyckoff (1910) |
| 16 | **Kyle's Lambda** | Price impact per unit volume — informed flow intensity | Kyle (1985) |
| 17 | **SMH Lead Signal** | Semiconductor RS slope vs QQQ (6-bar) | Sector rotation |
| 18 | **COT Positioning** | CFTC TFF Leveraged Funds 52-week percentile | CFTC.gov weekly |
| 19 | **Anchored VWAP** | Price proximity to yearly/swing-low/weekly AVWAP | Brian Shannon |
| 20 | **Market Breadth** | QQQ/IWM 5-day RS proxy for $ADDN | yfinance |
| +1 | **Memory Bonus** | Real-trade regime-contextual WR adjustment | bot_memory.json |

---

## Hard Blocks

Any one of these blocks the trade regardless of score:

```
BNS Jump           Bipower variation detects fat-tail / news spike
OFI Opposing       |z_OFI| > 2.0 — strong institutional flow against signal
CVD Climax         Buying/selling exhaustion at session extreme
RVOL Thin          < 0.8x normal participation — nobody home (blocked 17 trades)
Absorption Wall    Wyckoff wall absorbing your direction at entry level
VPIN High          > 0.65 on mean-reversion — informed flow running against you
VVIX Extreme       > 130 — vol-of-vol crisis, options market broken
VIX Backwardation  VIX/VIX3M > 1.15 — structural fear, skip all strategies
HAR Extreme Vol    Realized vol > 92nd pct — stops too tight for any entry
Macro Headwind     DXY + TNX both opposing + mean-rev long
Gap Too Large      > 1.2x ATR — only 8.2% fill rate, not a tradeable edge
```

---

## Two-Target Exit System

The biggest improvement in the system's history. Discovered that **44% of all v5 trades** (26 of 59) ended at exactly $0 P&L despite averaging **15.7× favorable excursion**.

**Root cause:** the old breakeven stop moved to entry at 1R profit. Price went far in the right direction, then reversed to entry. The system was right — the exit was wrong.

**Fix:**

```
T1  →  1× risk from entry  →  exit 50% of position, lock that P&L
T2  →  trail remaining 50% with Chandelier stop (3× 14-bar intraday ATR)

Chandelier long  = highest_high_since_T1 − 3 × ATR_14
Chandelier short = lowest_low_since_T1  + 3 × ATR_14
```

**Result:** Avg R:R jumped from 3.14× (v5) to 4.23× (v7). Exit fix alone added **+$693 P&L per 60 days**.

---

## Quick Start

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run backtest (three-way: base / institutional / hybrid)
python3 hybrid_run.py

# Walk-forward validation (WFE = 201%)
python3 -m backtest.walk_forward

# Start live monitor (run at 9:20 AM ET)
python3 monitor.py

# Generate 105-page research paper
python3 generate_report.py
# outputs: Isogeny_Alpha_System_Kairos_Research_v7.pdf
```

---

## Live Monitor — Terminal UI

The monitor runs in your terminal from 9:20 AM ET. It shows:

- **Startup**: account balance, buffer, bot memory insights
- **Session open brief**: news, economic calendar, day type (expansion/rotation), PDH/PDL/PMH/PML key levels
- **Live price ticker**: updates every 0.5s, shows RVOL, VIX, buffer, trade count
- **Level alerts**: bordered panels when approaching ORB/IB/PDH/PDL/VWAP
- **Signal panels**: large bordered display with entry/stop/T1/T2/score/contracts
- **Trade confirmation**: `y` = took it, `n` = skipped — only confirmed trades count toward 3/day limit
- **Outcome tracking**: `w/l/s` after each trade — feeds regime-contextual WR learning

Works on **macOS**, **Windows**, and **Linux**.

---

## Risk Management

```
Max risk per trade   25 pts × $2/pt × 1–2 MNQ = $50–$100
Max trades per day   3 (confirmed trades only — y/n flow)
Max daily loss       $100 self-imposed hard stop
Session close        12:00 PM ET — hard stop, no exceptions
Kelly guard          activates after 40+ real trades, prevents sizing up during drawdown
```

**Tradeify $25k compliance:**

| Rule | Required | Achieved |
|:--|:--:|:--:|
| Profit Target | $1,500 | $2,499 ✓ |
| Trailing Max Drawdown | $1,000 | $221 max ✓ |
| Consistency (no day > 40% profit) | 40% cap | $300 max day vs $600 cap ✓ |
| Max Contracts | 10 micros | 2 MNQ max ✓ |

---

## Project Structure

```
monitor.py                     Live session monitor — terminal UI, signals, memory
hybrid_run.py                  Three-way backtest comparison (base/inst/hybrid)
generate_report.py             105-page research paper (PDF) generator

backtest/
  hybrid_engine.py             20-point scoring + two-target exit + all signals
  quant_engine.py              Base strategies with two-target exit
  inst_engine.py               Hard-block overlay only
  walk_forward.py              IS/OOS walk-forward validation (WFE metric)
  data_loader.py               yfinance NQ/ES loader + validation + holiday calendar

strategy/
  quant_regime.py              EMA trend + adaptive ATR + VIX/VIX3M/VVIX + overnight
  quant_gap.py                 Gap Fill — prior-close target, tiny-gap filter
  quant_orb.py                 ORB — pullback entry, depth filter, extended T2 target
  quant_ib.py                  IB Breakout — IB bias detection, C-period confirmation
  quant_vwap.py                VWAP Reversion + VWAP Bounce (AM + PM)
  quant_fvg.py                 Fair Value Gap fills
  inst_ofi.py                  OFI z-score + CVD divergence + CVD climax detection
  inst_hmm.py                  5-state Gaussian HMM (return, range_ratio, realized_vol)
  inst_harv.py                 HAR-RV stop multiplier + BNS bipower jump detection
  inst_gex.py                  GEX proxy (VXN/VIX ratio — mean-rev vs breakout regime)
  inst_tsmom.py                TSMOM + session conviction + OCC opening candle
  inst_leadlag.py              ES lead-lag (3-bar) + NQ/ES spread z-score
  inst_sectors.py              XLK/SPY relative strength + SMH semiconductor lead
  inst_macro.py                DXY + TNX macro headwind/tailwind
  inst_vpin.py                 VPIN toxicity gate (Easley/Lopez de Prado/O'Hara 2012)
  inst_volprofile.py           POC / VAH / VAL / Naked VPOC / composite / single prints
  inst_levels.py               PDH / PDL / PMH / PML key institutional levels
  inst_rvol.py                 Time-of-day adjusted RVOL (same 5-min slot, 20 sessions)
  inst_absorption.py           Wyckoff effort vs result absorption detection
  inst_lambda.py               Kyle's lambda informed flow proxy (1985)
  inst_va_rule.py              80% Value Area Rule (Dalton — 30yr documented edge)
  inst_avwap.py                Anchored VWAP (yearly open, swing low, weekly open)
  inst_cot.py                  CFTC COT TFF Leveraged Funds — weekly macro compass
  inst_breadth.py              QQQ/IWM breadth proxy + $ADDN attempt
  inst_news.py                 Session news reader — Claude Haiku AI + keyword fallback
  bot_memory.py                Regime-contextual WR learning + adaptive score adjustment

notifications.py               Cross-platform alerts (macOS + Windows + Linux)
risk/prop_firm_rules.py        Tradeify trailing drawdown tracker
journal/trade_journal.py       SQLite trade log
```

---

## Research Paper

**[Isogeny_Alpha_System_Kairos_Research_v7.pdf](https://drive.google.com/file/d/1LOtb1W11er0btztrAVTCl8z7XHoDBU8O/view?usp=sharing)** — 105 pages

Written for both quantitative practitioners and complete beginners. Every formula has a plain-English translation. Every concept has a real-number NQ example.

Contents:
- Complete system documentation from first principles
- All 20 institutional signals with academic citations and plain-English explanations
- Full mathematical derivations (Kelly, Sharpe, HAR-RV, VPIN, OFI, HMM)
- 4 complete trade walkthroughs (real backtest dates, real prices, real P&L)
- Practical daily operating guide (9:00 AM pre-session checklist)
- Walk-forward validation methodology and WFE=201% analysis
- 8-question FAQ section
- Formula reference (17 formulas with translations)
- 7 embedded backtest charts

> To regenerate locally: `python3 generate_report.py`

---

## Academic References

| Signal / Concept | Citation |
|:--|:--|
| OFI z-score | Cont, Kukanov & Stoikov (2014) — *Journal of Financial Econometrics* |
| VPIN toxicity | Easley, Lopez de Prado & O'Hara (2012) — *Review of Financial Studies* |
| Hidden Markov Model | Hamilton (1989) — *Econometrica*; Ang & Bekaert (2002) — *JBES* |
| TSMOM | Moskowitz, Ooi & Pedersen (2012) — *Journal of Financial Economics* |
| Session intraday momentum | Gao, Han, Li & Zhou (2018) — *Journal of Financial Economics* |
| HAR-RV volatility | Andersen, Bollerslev & Diebold (2007) — *JBES* |
| Kyle's lambda | Kyle (1985) — *Econometrica* |
| 80% Value Area Rule | Dalton Capital Management (1987–1991) — *The Profile Reports* |
| ORB backtests | Crabel (1990); Edgeful ES (2023); Unger Academy NQ (2022) |
| Absorption / effort-result | Wyckoff (1910) — *Studies in Tape Reading* |
| Anchored VWAP | Shannon (2022) — *Maximum Trading Gains with Anchored VWAP* (CMT Association) |
| Walk-forward methodology | Lopez de Prado (2018) — *Advances in Financial Machine Learning* |

---

<div align="center">

*Kairos Capital Research — Proprietary and Confidential — Not Investment Advice*

</div>
