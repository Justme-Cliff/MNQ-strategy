# IDK Quant — Institutional Alpha System v7.0
### Systematic intraday trading for MNQ (Micro E-mini Nasdaq-100 Futures)
**Platform:** Tradeify $25k Evaluation · **Session:** 9:30 AM – 12:00 PM ET · **Venue:** CME Group

---

## Backtest Results (v7.0 — 60 days, 5-min bars)

| System | Trades | Win Rate | Net P&L | Avg R:R | Max DD | Pass? |
|---|---|---|---|---|---|---|
| Base (no filters) | 59 | 81.4% | $+1,687 | 3.14x | $87 | YES |
| Institutional (hard blocks only) | 18 | 66.7% | $+804 | 3.23x | $56 | NO |
| **Hybrid v7.0 (full system)** | **43** | **76.7%** | **$+2,499** | **4.23x** | **$221** | **YES** |

**Walk-Forward Efficiency (WFE): 201%** — out-of-sample outperformed in-sample.
Out-of-sample result: 14 trades, 71.4% WR, $808 P&L on data the system had never seen.

---

## What This System Does

Six intraday strategies filtered through a 20-point institutional confidence scoring layer.
Each signal passes through 11 hard blocks and 20 scoring factors before reaching the trader.
The two-target exit system locks partial profit at T1 (1R) and trails remaining 50% with a
3x intraday ATR Chandelier stop — eliminating the "44% breakeven trades" problem from v5.

**Strategies (priority order):**

| # | Strategy | Documented WR | Window | Core Edge |
|---|---|---|---|---|
| 1 | Gap Fill | 77.8% (tiny gaps) | 9:35 AM | Institutional rebalancing to prior close |
| 2 | FVG | 60–75% | 9:45–11:30 | Unfinished auction zones attract fills |
| 3 | ORB Pullback | 72–83% | 9:35–12:00 | Opening range breakout with pullback entry |
| 4 | IB Breakout | 84% (NQ, single-dir) | 10:00–12:00 | Post-initial-balance directional conviction |
| 5 | VWAP Bounce | 75–80% | 10:00–12:00 | Trend continuation at VWAP as support/resistance |
| 6 | 80% VA Rule | ~80% | 9:45–11:30 | Dalton 30yr documented value-area traverse edge |

---

## The 20-Point Confidence Scoring System

Every signal is scored across 20 orthogonal institutional dimensions.
Score <= 5 = skip. Score 6–15 = 1 MNQ. Score >= 16 = 2 MNQ contracts.

| # | Signal | Source |
|---|---|---|
| 1 | TSMOM — first 30-min momentum | Moskowitz et al. (2012) |
| 2 | GEX — gamma exposure regime | VXN/VIX ratio proxy |
| 3 | ES lead-lag confirmation | Lo & MacKinlay (1990) |
| 4 | HMM — 5-state latent regime | Ang & Bekaert (2002) |
| 5 | CVD divergence | Cumulative Volume Delta |
| 6 | Overnight range type | CME auction theory |
| 7 | VIX term structure | VIX/VIX3M contango/backwardation |
| 8 | XLK/SPY sector RS | Tech sector institutional flow |
| 9 | DXY + TNX macro | Dollar + yield headwind/tailwind |
| 10 | NQ/ES spread z-score | Stat-arb ratio divergence |
| 11 | Session conviction | Gao/Han/Li/Zhou (2018) |
| 12 | Open type (CME auction) | Steidlmayer Market Profile |
| 13 | RVOL (time-of-day adjusted) | Institutional participation |
| 14 | OCC — opening candle continuation | 84% day-continuation (10yr NQ) |
| 15 | Absorption detection | Wyckoff effort vs result |
| 16 | Kyle's lambda proxy | Kyle (1985) informed flow |
| 17 | SMH semiconductor lead signal | Sector rotation breadth |
| 18 | COT positioning (CFTC TFF) | Leveraged Funds net position |
| 19 | Anchored VWAP proximity | Brian Shannon methodology |
| 20 | Market breadth (QQQ/IWM RS) | Advance/decline proxy |
| +1 | Memory bonus | Real-trade regime WR learning |

---

## Hard Blocks (Any One Prevents the Trade Regardless of Score)

- **BNS Jump** — bipower variation detects fat-tail risk
- **OFI Opposing** — |z_OFI| > 2.0 institutional flow opposing signal
- **CVD Climax** — buying/selling exhaustion at session extreme
- **RVOL Thin** — < 0.8x (17 trades blocked in backtest — all would have lost)
- **Absorption Wall** — Wyckoff absorption opposing signal direction
- **VPIN High** — > 0.65 on mean-reversion strategies
- **VVIX Extreme** — > 130, vol-of-vol crisis
- **VIX Deep Backwardation** — VIX/VIX3M > 1.15
- **HAR Extreme Vol** — skip day if realized vol > 92nd percentile
- **Macro Headwind** — DXY+TNX combined strong headwind + mean-rev long
- **Gap Too Large** — > 1.2x ATR (only 8.2% fill rate historically)

---

## Quick Start

```bash
pip3 install -r requirements.txt
```

Run backtest:
```bash
python3 hybrid_run.py                  # three-way comparison
python3 -m backtest.walk_forward       # WFE validation
```

Run live monitor:
```bash
python3 monitor.py                     # start at 9:20 AM ET
```

Generate research paper:
```bash
python3 generate_report.py             # outputs IDK_Quant_Institutional_Alpha_System_v7.pdf
```

---

## Two-Target Exit System

The single most impactful improvement in the system's history.

**Problem:** 26 of 59 v5 trades (44%) ended at $0 despite averaging 15.7x favorable excursion.
**Fix:** T1 exits 50% at 1R (locks profit). T2 trails remaining 50% with Chandelier stop.

```
Chandelier_stop (long)  = max(High since T1) - 3 x ATR_14_intraday
Chandelier_stop (short) = min(Low  since T1) + 3 x ATR_14_intraday
```

Impact: Avg R:R improved from 3.14x (v5) to 4.23x (v7). +$693 P&L per 60 days from exit fix alone.

---

## Risk Management

```
Max risk per trade:   25 pts x $2/pt x 1-2 MNQ = $50-$100
Max trades per day:   3 (confirmed trades only)
Max daily loss:       $100 self-imposed hard stop
Session close:        12:00 PM ET — hard stop, no exceptions
Kelly guard:          activates after 40+ real trades
```

Tradeify $25k compliance: Profit target $2,499 vs $1,500 required. Max DD $221 vs $1,000 limit.

---

## Project Structure

```
monitor.py                     live session monitor
hybrid_run.py                  three-way backtest runner
generate_report.py             105-page research paper generator

backtest/
  hybrid_engine.py             20-point scoring + two-target exit
  quant_engine.py              base engine with two-target exit
  inst_engine.py               hard-block overlay
  walk_forward.py              IS/OOS walk-forward validation

strategy/
  quant_regime.py              EMA + adaptive ATR + VIX/VVIX + overnight
  quant_gap/orb/ib/vwap/fvg.py  six strategy detectors
  inst_ofi.py                  OFI + CVD divergence + CVD climax
  inst_hmm.py                  5-state HMM (return, range_ratio, realized_vol)
  inst_harv.py                 HAR-RV stop multiplier + BNS jump
  inst_gex.py                  GEX proxy
  inst_tsmom.py                TSMOM + session conviction + OCC
  inst_leadlag.py              ES lead-lag + NQ/ES spread
  inst_sectors.py              XLK/SPY RS + SMH semiconductor lead
  inst_macro.py                DXY + TNX macro
  inst_vpin.py                 VPIN toxicity gate
  inst_volprofile.py           Volume Profile (POC/VAH/VAL/VPOC/composite/single prints)
  inst_levels.py               PDH/PDL/PMH/PML key levels
  inst_rvol.py                 Time-of-day adjusted RVOL
  inst_absorption.py           Wyckoff absorption detection
  inst_lambda.py               Kyle's lambda proxy
  inst_va_rule.py              80% Value Area Rule
  inst_avwap.py                Anchored VWAP
  inst_cot.py                  CFTC COT TFF positioning
  inst_breadth.py              QQQ/IWM breadth proxy
  inst_news.py                 Session news reader (Haiku AI + fallback)
  bot_memory.py                Regime-contextual WR learning
```

---

## Research Paper

**IDK_Quant_Institutional_Alpha_System_v7.pdf** — 105 pages

Complete system documentation written for both quant practitioners and complete beginners.
Every formula has a plain-English translation. Every concept has a real-number example.
Includes 4 complete trade walkthroughs, daily operating guide, FAQ, formula reference,
and 7 embedded backtest charts.

---

## Academic References

| Signal | Citation |
|---|---|
| OFI z-score | Cont, Kukanov & Stoikov (2014) |
| VPIN | Easley, Lopez de Prado & O'Hara (2012) |
| HMM | Hamilton (1989); Ang & Bekaert (2002) |
| TSMOM | Moskowitz, Ooi & Pedersen (2012) |
| Session conviction | Gao, Han, Li & Zhou (2018, JFE) |
| HAR-RV | Andersen, Bollerslev & Diebold (2007) |
| Kyle's lambda | Kyle (1985, Econometrica) |
| Value Area Rule | Dalton Capital Management (1987–1991) |
| ORB | Crabel (1990); Edgeful (2023); Unger Academy (2022) |

---

*IDK Quant Research Institute — For internal use only. Not investment advice.*
