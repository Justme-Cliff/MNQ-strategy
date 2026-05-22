# Asia Session Sweep: Automated Futures Trading System

A real-time signal detection and risk management system for day trading futures. Built around the Asia Session Sweep model, enhanced with a 5-point confluence scoring system, adaptive smart filters, and automatic risk sizing. Works out of the box for MNQ on a $25k evaluation. Fully configurable for any account size, instrument, or prop firm rules.

![Strategy Flow](images/strategy_flow.png)

---

## Table of Contents

1. [What This Is](#what-this-is)
2. [Quick Start](#quick-start)
3. [Adapt It to Your Account](#adapt-it-to-your-account)
4. [The Strategy Explained](#the-strategy-explained)
5. [How the Bot Works](#how-the-bot-works)
6. [Signal Output](#signal-output)
7. [Smart Adaptive Features](#smart-adaptive-features)
8. [System Architecture](#system-architecture)
9. [File Structure](#file-structure)
10. [Backtest Results](#backtest-results)
11. [Trade Journal](#trade-journal)
12. [Roadmap](#roadmap)

---

## What This Is

This bot runs in your terminal every morning. It watches live futures price data, detects high-probability reversal setups, and fires an alert with exact entry, stop loss, and take profit numbers the moment a valid signal forms. You place the trade manually on your broker platform. The bot monitors your open position and alerts you at every milestone.

It does not place trades automatically in its current form. It is the detection and calculation layer. The full execution layer (bracket orders, stop management, break-even moves) is already coded and ready to activate when Tradovate API access is available on a funded account.

**What you need to run it:**

* Python 3.9+ on macOS
* Any broker platform open on the side (TradingView, Tradovate, etc.)
* A futures account (prop firm evaluation or live funded account)

---

## Quick Start

```bash
git clone https://github.com/Justme-Cliff/MNQ-strategy.git
cd MNQ-strategy
pip3 install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your broker credentials. Then every morning:

```bash
python3 live_detector.py
```

To view your trade history:

```bash
python3 live_detector.py /journal
```

To run a backtest on 60 days of historical data:

```bash
python3 backtest_run.py
```

**Keyboard commands while running:**

| Key | Action |
|---|---|
| s + Enter | Print current status |
| j + Enter | Show trade journal |
| h + Enter | Show help |
| q + Enter | Quit safely |

---

## Adapt It to Your Account

This is the most important section if you are not on a Tradeify $25k evaluation. Everything that controls risk, targets, and firm rules lives in two files: `config.py` and `risk/prop_firm_rules.py`.

![Risk Scaling Reference](images/risk_scaling.png)

### Step 1: Set your risk per trade

Open `config.py` and change these four values:

```python
# How much you are willing to lose on a single trade (in dollars)
MAX_RISK_PER_TRADE = 50

# How many points your stop can be from entry before the trade is rejected
# Formula: MAX_RISK_PER_TRADE / dollars_per_point_for_your_instrument
# MNQ = $2/pt  ->  50 / 2 = 25 points
# MES = $5/pt  ->  100 / 5 = 20 points
# ES  = $50/pt ->  250 / 50 = 5 points
MAX_STOP_POINTS = 25

# Max total loss allowed in one session before the bot shuts down signals
# Recommended: 2x your per-trade risk
MAX_DAILY_LOSS = 100

# How many trades per day you allow yourself
MAX_TRADES_PER_DAY = 2
```

**Formula for any account size:**

```
MAX_RISK_PER_TRADE  = account_size * 0.002      (0.2% of account)
MAX_STOP_POINTS     = MAX_RISK_PER_TRADE / dollars_per_point
MAX_DAILY_LOSS      = MAX_RISK_PER_TRADE * 2
```

### Step 2: Set your instrument

The bot defaults to `NQ=F` (Nasdaq-100 futures) via yfinance. To change it, open `config.py`:

```python
# yfinance ticker symbol for your instrument
# NQ=F  = E-mini Nasdaq-100 (MNQ trades at 1/10th the tick)
# ES=F  = E-mini S&P 500
# RTY=F = E-mini Russell 2000
TICKER = "NQ=F"

# Dollar value per 1 index point for your contract
# MNQ = $2.00,  MES = $5.00,  M2K = $5.00
# NQ  = $20.00, ES  = $50.00, RTY = $50.00
DOLLARS_PER_POINT = 2.0
```

### Step 3: Set your trading hours

```python
# When signals start firing (24h format, ET timezone)
TRADE_START_HOUR   = 9
TRADE_START_MINUTE = 30

# When signals stop (session auto-closes at this time)
TRADE_END_HOUR     = 11
TRADE_END_MINUTE   = 30

# High-quality window (bot requires 5/5 score outside this window)
PRIME_END_HOUR     = 11
PRIME_END_MINUTE   = 0
```

### Step 4: Set your prop firm rules (if applicable)

Open `risk/prop_firm_rules.py` and update the `TradeifyState` class with your firm's actual numbers:

```python
class TradeifyState:
    PROFIT_TARGET     = 1500    # Dollar amount you need to earn to pass
    MAX_DRAWDOWN      = 1000    # Maximum trailing drawdown allowed by firm
    CONSISTENCY_CAP   = 0.40    # Max % of total profit from a single day (firm rule)
    CONSISTENCY_BUFFER = 0.38   # Use 38% instead of 40% for a safety margin
    DRAWDOWN_ALERT    = 200     # Bot warns you when buffer drops to this level
    DRAWDOWN_BLOCK    = 100     # Bot blocks new signals when buffer is this low
```

To initialize with how much you have already lost on the evaluation:

```python
# In live_detector.py, update this line:
state.setup(already_lost=0.00)   # replace 0.00 with your current loss
```

If you are trading a live funded account (no profit target, no trailing DD), you can disable prop firm tracking entirely by setting `PROFIT_TARGET = None` and `MAX_DRAWDOWN = None` in the same file.

### Step 5: Adjust confluence requirements

The bot requires 4 out of 5 points by default. You can tighten or relax this in `config.py`:

```python
# Minimum score required to fire a signal (1-5)
# 3 = more signals, lower quality
# 4 = balanced (default)
# 5 = only perfect setups
MIN_CONFLUENCE_SCORE = 4
```

---

## The Strategy Explained

### Why This Works

Professional institutions and large traders operate differently from retail traders. Retail traders place their stop losses at obvious levels: just above a key high, just below a key low, just outside a session range. Institutions know exactly where these stops cluster. They deliberately push price through those levels to fill their own large orders at a better price, then reverse direction.

This is called a liquidity sweep or stop hunt. This strategy is built entirely around identifying those moments and trading the reversal once it is confirmed.

### The Asia Session Range

Every night from roughly 8:00 PM to 12:00 AM EST, the futures market consolidates in a quiet range while the Asian session is active. The high and low of this range are significant because retail traders leave stops on both sides. When New York opens at 9:30 AM, there is a well-documented tendency for price to sweep one side of that range first before moving in the day's real direction.

### The Four Step Setup

![Confluence Scoring](images/confluence_score.png)

**Step 1: Asia Range Formation**

From 8:00 PM to midnight, the bot records every 1-minute bar and identifies the session high and low. These become the two reference levels. No action is taken yet.

**Step 2: The Sweep**

After 9:30 AM the bot watches for price to break through one of those levels:

* Price dips below the Asia Low: bullish setup forming (institutions swept buy stops below, will reverse up)
* Price pushes above the Asia High: bearish setup forming (institutions swept sell stops above, will reverse down)

This is a warning, not a trade entry. Many sweeps are false or lead nowhere.

**Step 3: Market Structure Shift (MSS)**

After the sweep, the bot waits for confirmation. For a bullish setup, price must create a local low after the sweep, then break back above a prior swing high. That break is the MSS. It signals that the reversal is actually underway. Without the MSS, no signal fires.

**Step 4: Fair Value Gap Entry**

When price moves aggressively it often skips a range of prices entirely, leaving a gap between candles. This gap (called a Fair Value Gap or FVG) acts as a magnet. Price often returns to fill it before continuing. The entry limit order is placed inside that gap. If price never returns to fill it, the trade is skipped with zero loss.

### Scoring System

The bot scores the setup from 0 to 5 based on five conditions. A trade fires only at 4 or 5. See the image above for what each point represents and why it matters.

### Entry, Stop, and Targets

**Entry:** Limit order inside the FVG zone, at most `MAX_STOP_POINTS` away from the stop.

**Stop Loss:** 1 point beyond the sweep wick. If swept again, trade is invalid.

**Take Profit 1:** 1.5 times the stop distance. When hit, move stop to break-even. Trade is now risk-free.

**Take Profit 2:** 3.0 times the stop distance. Full target. Minimum 3:1 reward to risk.

**Why 3:1 minimum?** At a 40% win rate the strategy is still profitable. At 43% the expected value per trade is over $44.

---

## How the Bot Works

### Startup

When you run `python3 live_detector.py`:

1. Fast price feed starts (background thread, updates every 0.5 seconds using yfinance persistent connection)
2. Three days of 1-minute bar data downloads to build Asia range and VWAP
3. Morning briefing prints: Asia levels, distances to key levels, account buffer, consistency cap, game plan for the day
4. Economic calendar checked for high-impact news events (FOMC, CPI, NFP)
5. Keyboard listener starts
6. Main detection loop begins

### Main Loop

Every 0.5 seconds the bot reads the cached live price (no network call, instant). It checks sweep conditions, MSS conditions, scores the setup, and fires a signal if all thresholds are met. Bar data refreshes every 5 minutes to keep VWAP accurate.

### After a Signal Fires

![Terminal Signal](images/terminal_signal.png)

1. Large colored panel prints with exact numbers to enter on your broker platform
2. Hero sound plays twice on Mac speakers
3. macOS notification banner appears even if terminal is minimized
4. Bot asks whether you took the trade
5. If yes: live price monitoring starts in a background thread, watching for TP1, TP2, and stop level
6. When TP1 hits: alert fires, terminal tells you to move stop to break-even
7. When TP2 or stop hits: alert fires, bot asks for the result, records everything

If you skip a trade: the bot tracks what would have happened and reports the outcome at end of session.

---

## Smart Adaptive Features

**Loss Streak Protection**

After two consecutive losses the minimum required confluence score increases from 4 to 5 automatically. Only perfect setups fire until you get a winner. This prevents digging deeper by taking marginal trades while the market is not cooperating.

**Time Quality Filter**

After 11:00 AM liquidity drops and volatility becomes less directional. The bot automatically requires 5/5 after 11:00 AM. If you want to extend the high-quality window, change `PRIME_END_HOUR` in `config.py`.

**Sweep Quality Check**

Sweeps smaller than 3 points are noise. Sweeps larger than 80 points mean the entry zone will be too far from the stop to fit inside your risk limit. Both extremes are rejected. You can change these thresholds in `strategy/smart_filter.py`:

```python
MIN_SWEEP_POINTS = 3    # smaller than this = noise, ignored
MAX_SWEEP_POINTS = 80   # larger than this = unmanageable, ignored
```

**Choppiness Detection**

If the price range over the last 50 ticks is under 15 points, the market is chopping. The status line shows CHOPPY. No new setups are scored until range expands.

**Missed Trade Tracking**

Every skipped signal is tracked silently in the background. End-of-session summary shows whether the missed trades would have won, lost, or scratched. Over time this data tells you whether your instinct to skip was right or whether you are leaving money on the table.

---

## System Architecture

```
Live Price Feed (yfinance, 0.5s background thread)
         |
         v
   Sweep Detector  <-- compares live price to Asia High / Asia Low
         |
    Sweep found
         |
         v
   MSS Detector  <-- tracks swing pivots, waits for structure break
         |
    MSS confirmed
         |
         v
   Confluence Scorer  <-- 5-point check, returns score 0-5
         |
    Score meets threshold
         |
         v
   Risk Manager  <-- checks daily limits, drawdown buffer, consistency cap
         |
    Approved
         |
         v
   Signal Output  <-- terminal panel + macOS sound + notification
         |
         v
   You Execute on Broker Platform
         |
         v
   Trade Monitor  <-- background thread watching TP1/TP2/stop in real time
         |
         v
   Journal Update  <-- SQLite, balance, streak, stats
```

---

## File Structure

```
trading-strategy/
|
|-- live_detector.py          Main entry point, run this every morning
|-- backtest_run.py           Run strategy on 60 days of historical data
|-- config.py                 All settings: risk, timing, instrument, thresholds
|-- fast_feed.py              Background price cache (0.5s updates)
|-- notifications.py          macOS sound and popup alerts
|-- briefing.py               Morning briefing and session summary
|-- news_check.py             Economic calendar warning system
|-- tradovate_feed.py         Real-time Tradovate WebSocket (funded accounts)
|
|-- strategy/
|   |-- asia_range.py         Asia session high/low detection
|   |-- mss_detector.py       Market Structure Shift confirmation
|   |-- fvg_detector.py       Fair Value Gap identification
|   |-- vwap.py               Intraday VWAP calculation
|   |-- confluence_scorer.py  5-point scoring system
|   |-- signal_generator.py   Signal assembly and output
|   |-- smart_filter.py       Adaptive filters (loss streak, time, sweep quality)
|
|-- risk/
|   |-- position_sizer.py     Contract sizing (scales to your MAX_RISK setting)
|   |-- prop_firm_rules.py    Firm rules: trailing DD, consistency cap, targets
|   |-- risk_manager.py       Trade approval gateway
|
|-- broker/
|   |-- tradovate_client.py   Tradovate REST + WebSocket API (ready for funded)
|   |-- order_manager.py      Bracket orders, BE moves, emergency close
|
|-- server/
|   |-- webhook_server.py     FastAPI server for TradingView webhooks
|
|-- backtest/
|   |-- data_loader.py        Historical data via yfinance
|   |-- engine.py             Bar-by-bar strategy simulation
|   |-- results_analyzer.py   Performance statistics
|
|-- journal/
|   |-- trade_journal.py      SQLite trade database
|   |-- dashboard.py          Terminal performance dashboard
|
|-- pine_script/
|   |-- tjr_enhanced.pine     TradingView Pine Script v5 indicator
|
|-- images/                   README diagrams
|
|-- tests/
    |-- test_risk_manager.py
    |-- test_position_sizer.py
    |-- test_confluence_scorer.py
```

---

## Backtest Results

Run `python3 backtest_run.py` to test against the most recent 60 days of data. Results from May 2026 on MNQ with the default $25k configuration:

| Metric | Result |
|---|---|
| Total trades | 37 |
| Win rate | 43.2% |
| Average win | $150 |
| Average loss | $35.71 |
| Total PnL | $1,650 |
| Max drawdown in period | $250 |

At 43% win rate with 3:1 reward to risk, the expected value per trade:

```
EV = (0.43 * $150) + (0.57 * -$35.71)
   = $64.50 - $20.35
   = +$44.15 per trade
```

The break-even win rate for 3:1 reward to risk is 25%. Anything above 25% is profitable long term.

---

## Trade Journal

Every signal is recorded regardless of whether you took it. To view:

```bash
python3 live_detector.py /journal
```

Each entry stores:

| Field | Description |
|---|---|
| Timestamp | Exact time the signal fired |
| Direction | Long or Short |
| Entry | Calculated limit entry price |
| Stop | Stop loss price |
| TP1 / TP2 | Both take profit levels |
| PnL | Actual dollar result |
| Score | Confluence score at signal time |
| Outcome | WIN / LOSS / BE / SKIPPED |
| Buffer | Drawdown buffer remaining at signal time |

---

## Roadmap

**Current: Signal Mode**
* Real-time sweep and MSS detection
* 5-point confluence scoring
* macOS sound and popup notifications
* Trade monitoring (TP1, TP2, stop alerts)
* Full trade journal with /journal command
* Morning briefing and session summary
* Adaptive smart filters
* Missed trade outcome tracking
* Backtest engine on 60 days of data

**Next: Full Automation (Funded Account)**
* Bracket orders placed automatically via Tradovate API (code already exists in broker/)
* Stop moved to break-even when TP1 hits
* Position closed at TP2 automatically
* Zero manual interaction required

**Future**
* London session support
* Multi-instrument scanning (MES, M2K, MYM)
* Web dashboard
* Machine learning on confluence scores

---

## Disclaimer

This software is for educational and personal use only. Trading futures involves substantial risk of loss. Past backtest performance does not guarantee future results. Always trade within your risk tolerance and follow the rules of any account or evaluation you participate in.
