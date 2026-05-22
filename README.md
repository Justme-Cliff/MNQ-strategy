# TJR Enhanced — Automated MNQ Futures Trading System

> An institutional-grade signal detection and risk management system for trading Micro E-mini Nasdaq-100 (MNQ) futures on the Tradeify $25k evaluation challenge. Built on the TJR Asia Session Sweep methodology, enhanced with data-driven confluence scoring, adaptive smart filters, and real-time execution guidance.

---

## Table of Contents

1. [What This Is](#what-this-is)
2. [The Strategy Explained](#the-strategy-explained)
3. [How the Bot Works](#how-the-bot-works)
4. [System Architecture](#system-architecture)
5. [File Structure](#file-structure)
6. [Installation](#installation)
7. [Configuration](#configuration)
8. [Running the Bot](#running-the-bot)
9. [Signal Output](#signal-output)
10. [Risk Management](#risk-management)
11. [Smart Adaptive Features](#smart-adaptive-features)
12. [Trade Journal](#trade-journal)
13. [Backtest Results](#backtest-results)
14. [Prop Firm Rules](#prop-firm-rules)
15. [Roadmap](#roadmap)

---

## What This Is

This project is a complete trading assistant built for day trading MNQ futures during the New York morning session (9:30 AM to 11:30 AM EST). It detects high-probability reversal setups using the TJR Asia Session Sweep model, scores them with a 5-point confluence system, manages risk automatically, and outputs clear actionable signals directly to your terminal.

The system does not place trades automatically in its current form. It acts as an intelligent co-pilot — detecting setups faster than any human can, calculating exact entry, stop loss, and take profit levels, and alerting you with sound and macOS notifications so you never miss a signal.

The entire automation layer (bracket orders, stop management, break-even moves) is already coded and will activate when Tradovate API access becomes available on a funded account.

---

## The Strategy Explained

### Background — Why This Works

Professional traders and institutions operate differently from retail traders. Retail traders place stop losses at obvious levels — just above resistance, just below support, just outside key session highs and lows. Institutions know exactly where these stops cluster. They deliberately push price through those levels to trigger the stops, collect the liquidity, and then reverse in the opposite direction at a better price.

This is called a liquidity sweep or stop hunt. The TJR strategy is built entirely around identifying these moments and trading the reversal.

### The Asia Session Range

Every night from 8:00 PM to 12:00 AM EST, the futures market trades in a relatively quiet range. This is the Asian session. The high and low of this session represent where price consolidated overnight. These two levels are significant because retail traders will have:

* Buy stops sitting above the Asia High (short sellers protecting positions)
* Sell stops sitting below the Asia Low (long holders protecting positions)

These stops are the target. When New York opens at 9:30 AM, institutions have a playbook: run the stops on one side, collect the liquidity, then trade the real direction.

### The Four Step Setup

**Step 1 — Asia Range Formation**

Between 8:00 PM and midnight EST, the bot records every price bar and builds the high and low of that session. These become the two orange horizontal lines on your TradingView chart. No action is taken during this phase.

**Step 2 — The Sweep**

After 9:30 AM EST, the bot watches for price to pierce through one of the orange lines:

* Price drops below the Asia Low → Bullish setup forming (institutions swept buy stops, will reverse up)
* Price rises above the Asia High → Bearish setup forming (institutions swept sell stops, will reverse down)

The moment this happens, the bot fires a yellow warning: SWEEP DETECTED — GET READY.

The sweep itself is not the entry signal. It is the precondition. Many sweeps are false. You need confirmation before entering.

**Step 3 — Market Structure Shift (MSS)**

After the sweep, the bot watches for a Market Structure Shift. This is the confirmation that the institutional reversal has begun. For a bullish setup:

* After sweeping the Asia Low, price must create a local low (a swing point)
* Price then breaks back above a prior swing high
* This break above structure is the MSS — it confirms the reversal is real

For a bearish setup, the inverse applies — price must break below a prior swing low after the sweep.

The bot detects MSS in real time by tracking swing pivots and monitoring when price breaks through them with a closing candle.

**Step 4 — Fair Value Gap Entry**

When institutions move price aggressively, they often leave an imbalance — a range of prices that were skipped over entirely. This is called a Fair Value Gap (FVG). It appears as a gap between the high of a candle two bars ago and the low of the current bar (for bullish), or the low of a candle two bars ago and the high of the current bar (for bearish).

Price frequently returns to fill these gaps before continuing in the original direction. This retracement is the entry point. The bot identifies these zones and the entry price is calculated to be within the zone, keeping risk within the $50 maximum per trade.

### The Five Point Confluence Score

Not every sweep and MSS leads to a profitable trade. The bot scores each potential setup on five criteria. A trade is only signalled when the score reaches 4 or 5 out of 5.

| Point | Condition | Bullish | Bearish |
|---|---|---|---|
| 1 | Asia Sweep | Low swept Asia Low | High swept Asia High |
| 2 | MSS Confirmed | Close above prior swing high | Close below prior swing low |
| 3 | FVG Present | Bullish gap in entry zone | Bearish gap in entry zone |
| 4 | VWAP Aligned | Price above session VWAP | Price below session VWAP |
| 5 | Time Window | Between 9:30 and 11:00 AM | Between 9:30 and 11:00 AM |

The VWAP (Volume Weighted Average Price) is the fairest average price of the session weighted by volume. Trading in the direction of VWAP is trading with the institutional flow of the day.

Requiring 4 out of 5 points means the bot rejects the majority of setups. This is intentional. Fewer trades with higher confluence win more often than many trades with weak setups.

### Entry, Stop Loss, and Take Profit

**Entry** — A limit order placed at a level within 25 points of the stop. For a long trade after a sweep, entry is placed at stop + 25 points. Price must pull back to this level after the MSS for the order to fill. If price never pulls back, the trade is skipped — no loss, no stress.

**Stop Loss** — Placed beyond the sweep wick. For a long, the stop goes 1 point below the lowest low since the sweep bar. This protects against the trade invalidating by taking out the sweep level again.

**Take Profit 1** — At 1.5 times the stop distance. When hit, the stop moves to break-even (entry price). The trade becomes risk-free.

**Take Profit 2** — At 3.0 times the stop distance. This is the full target. On 1 MNQ contract with a 25-point stop, TP2 yields $150.

**Risk/Reward** — Every trade targets at minimum 3:1. With a $50 risk, the minimum reward is $150. Even at a 40% win rate, this strategy is profitable in the long run.

---

## How the Bot Works

### Startup Sequence

When you run `python3 live_detector.py`, the bot executes the following sequence:

1. Starts the fast price feed (persistent yfinance connection, updates every 0.5 seconds)
2. Downloads 3 days of 1-minute bar data to build the Asia range and VWAP context
3. Prints the morning briefing: Asia levels, key distances, consistency cap status, game plan
4. Checks the economic calendar for high-impact news events
5. Starts the keyboard listener (s, j, q, h commands)
6. Enters the main detection loop

### Main Detection Loop

Every 0.5 seconds:

1. Read the cached live price (instant — no network wait)
2. Check if current time is inside the trade window (9:30 to 11:30 AM)
3. Check if price has crossed the Asia High or Asia Low (sweep detection)
4. If a sweep was detected on a prior tick, check for MSS formation
5. If MSS is detected, score the setup (1 to 5 points)
6. If score meets the minimum threshold, calculate entry/stop/targets and fire signal

Every 5 minutes:
* Refresh bar data from yfinance to keep VWAP and Asia range accurate
* Print status update to terminal

At 11:30 AM:
* Session ends automatically
* End-of-session summary prints (trades taken, P&L, missed trade outcomes)

### After Signal Fires

1. Terminal shows a large colored panel with exact numbers to type into TradingView
2. Sound plays twice (Hero sound on macOS)
3. macOS notification banner appears even if terminal is minimized
4. Bot asks: "Did you take this trade? (y/n)"
5. If yes: bot monitors live price for TP1, TP2, and stop hits while you are in the trade
6. When TP1 hits: sound + popup + terminal alert "MOVE STOP TO BREAK-EVEN NOW"
7. When TP2 or stop hits: sound + popup + terminal asks for result
8. Result recorded: balance updates, journal logs, smart filter updates streak

If the trade is skipped: bot watches what would have happened and reports the outcome at end of session.

---

## System Architecture

```
Live Price Feed (yfinance fast_info, 0.5s)
         |
         v
   Sweep Detector
   (price vs Asia H/L)
         |
    Sweep found
         |
         v
   MSS Detector
   (pivot break confirmation)
         |
    MSS confirmed
         |
         v
   Confluence Scorer
   (5 point system)
         |
    Score >= threshold
         |
         v
   Risk Manager
   (size, daily limits, prop firm rules)
         |
    Approved
         |
         v
   Signal Output
   (terminal + sound + macOS notification)
         |
         v
   You Execute on TradingView
         |
         v
   Trade Monitor
   (watches TP1/TP2/stop while in trade)
         |
         v
   Journal Update
   (P&L, balance, streak, stats)
```

---

## File Structure

```
trading-strategy/
|
|-- live_detector.py          Main entry point — run this every morning
|-- backtest_run.py           Run strategy on 60 days of historical data
|-- config.py                 All settings and constants
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
|   |-- smart_filter.py       Adaptive filters (loss streak, time quality)
|
|-- risk/
|   |-- position_sizer.py     Contract sizing ($50 max risk)
|   |-- prop_firm_rules.py    Tradeify rules (trailing DD, consistency)
|   |-- risk_manager.py       Trade approval gateway
|
|-- broker/
|   |-- tradovate_client.py   Tradovate REST + WebSocket API
|   |-- order_manager.py      Bracket orders, BE moves, emergency close
|
|-- server/
|   |-- webhook_server.py     FastAPI server for TradingView webhooks
|
|-- backtest/
|   |-- data_loader.py        Historical NQ data via yfinance
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
|-- tests/
    |-- test_risk_manager.py
    |-- test_position_sizer.py
    |-- test_confluence_scorer.py
```

---

## Installation

**Requirements**

* Python 3.9 or higher
* macOS (for sound and notification features)
* TradingView account (any plan — used for chart reference only)
* Tradeify evaluation account on Tradovate

**Setup**

Clone or download this repository to your computer.

Open Terminal and navigate to the folder:

```
cd "/Users/yourname/Desktop/trading startegy"
```

Install all Python dependencies:

```
pip3 install -r requirements.txt
```

Copy the environment template and fill in your values:

```
cp .env.example .env
```

Edit `.env` with your Tradeify credentials (found under View Credentials on the Tradeify dashboard).

---

## Configuration

All core settings live in `config.py`. The values below reflect the Tradeify $25k evaluation rules and personal trading rules.

| Setting | Value | Purpose |
|---|---|---|
| MAX_RISK_PER_TRADE | $50 | Maximum dollar loss per trade |
| MAX_TRADES_PER_DAY | 2 | Daily trade limit |
| MAX_DAILY_LOSS | $100 | Self-imposed daily stop |
| MIN_CONFLUENCE_SCORE | 4 | Minimum score to signal a trade |
| MAX_STOP_POINTS | 25 | Max stop distance in MNQ points |
| TRADE_START | 9:30 AM EST | Session opens |
| TRADE_END | 11:30 AM EST | Session closes |
| CONSISTENCY_BUFFER | 38% | Daily cap (Tradeify rule is 40%) |
| DRAWDOWN_ALERT | $200 | Warning threshold |
| DRAWDOWN_BLOCK | $100 | Hard block threshold |

The smart filter in `strategy/smart_filter.py` dynamically adjusts the minimum score based on:

* Consecutive loss streak (2+ losses → requires 5/5)
* Time of day (after 11:00 AM → requires 5/5)
* Sweep quality (too shallow or too deep → rejected automatically)

---

## Running the Bot

**Every morning at 9:00 AM:**

```
python3 live_detector.py
```

**To view your trade journal:**

```
python3 live_detector.py /journal
```

**To run a backtest on 60 days of historical data:**

```
python3 backtest_run.py
```

**While the bot is running, keyboard commands:**

| Key | Action |
|---|---|
| s + Enter | Print current status |
| j + Enter | Show trade journal |
| h + Enter | Show help |
| q + Enter | Quit safely |

---

## Signal Output

When a valid signal fires, the terminal displays:

```
╔══════════════════════════════════════════════════════════╗
║   SHORT MNQ — PLACE THIS TRADE NOW   10:23:47 EST       ║
║                                                          ║
║  Step 1 — Click SELL on TradingView                     ║
║  Step 2 — Set order type to LIMIT                       ║
║  Step 3 — Enter these exact numbers:                    ║
║                                                          ║
║  Entry (Limit price):  29,643.75                        ║
║  Stop Loss:            29,668.75    max loss $50        ║
║  Take Profit 1:        29,606.25    move stop to BE     ║
║  Take Profit 2:        29,568.75    pocket $150         ║
║                                                          ║
║  Size: 1 MNQ contract   Score: 4/5                      ║
╚══════════════════════════════════════════════════════════╝
```

Simultaneously:

* Hero sound plays twice on your Mac speakers
* macOS notification banner appears in the top right corner
* Bot begins monitoring price for TP1/TP2/stop milestones

---

## Risk Management

### Position Sizing

MNQ is $2 per index point. With a maximum risk of $50 per trade:

```
Maximum stop distance = $50 / $2 = 25 points
Minimum target (3:1) = 25 * 3 = 75 points = $150
```

The position sizer always rounds down. If a stop requires 30 points and risk exceeds $50 on 1 contract, the trade is rejected automatically. There is no override.

### Daily Kill Switch

If the total daily loss reaches $100 (two maximum losses), the bot locks out all new signals for the rest of the session. This prevents revenge trading and protects the account buffer.

### Prop Firm Drawdown Tracking

Tradeify uses a trailing maximum drawdown. The floor moves up as your end-of-day balance grows. The bot tracks:

* Current drawdown buffer (distance from floor)
* Alert threshold at $200 remaining
* Hard block at $100 remaining

### Consistency Rule

Tradeify requires that no single trading day represents more than 40% of total profit earned. The bot calculates this in real time:

```
max_allowed_today = total_profit * 0.38
```

Using 38% instead of 40% provides a safety buffer. When daily profit approaches this cap, the bot auto-closes monitoring for that session.

---

## Smart Adaptive Features

### Loss Streak Protection

After two consecutive losses the bot automatically increases the minimum required confluence score from 4 to 5. Only perfect setups (all five conditions aligned) will trigger a signal. This prevents digging deeper into a losing streak by taking suboptimal trades.

### Time Quality Filter

The 9:30 to 10:00 AM window has the highest probability for setups because the institutional participation is highest at the New York open. After 11:00 AM, market volatility and directional conviction decrease. The bot automatically requires 5/5 after 11:00 AM.

### Sweep Quality Validation

Not all sweeps are equal. A sweep of only 2 to 3 points is likely noise — price briefly crossed the level without real institutional intent. A sweep of 90 points means the entry zone will be too far from the stop to manage risk within $50. Both extremes are filtered:

* Sweeps under 3 points: rejected as noise
* Sweeps over 80 points: rejected as unmanageable risk

### Market Choppiness Detection

The bot tracks the price range over the last 50 ticks. If the range is under 15 points, the market is chopping and setups are likely to fail. The status display shows CHOPPY as a warning.

### Missed Trade Outcome Tracking

Every signal the user skips is tracked in a background thread. The bot continues watching price and reports at the end of the session whether the skipped trade would have won, lost, or broken even. This data builds confidence in the system over time.

---

## Trade Journal

Every signal is recorded regardless of whether it was taken. The journal stores:

| Field | Description |
|---|---|
| Timestamp | Exact time of signal |
| Direction | Long or Short |
| Entry price | Calculated limit entry |
| Stop price | Calculated stop loss |
| TP1 and TP2 | Both take profit levels |
| PnL | Actual result in dollars |
| Score | Confluence score at signal time |
| Outcome | WIN / LOSS / BE / SKIPPED |
| Drawdown remaining | Buffer at time of signal |
| Progress | % toward $1,500 target |

To view the journal:

```
python3 live_detector.py /journal
```

---

## Backtest Results

Running `python3 backtest_run.py` against 60 days of NQ futures data (May 2026) produced:

| Metric | Result |
|---|---|
| Total trades | 37 |
| Win rate | 43.2% |
| Average win | $150 |
| Average loss | $35.71 |
| Total PnL | $1,650 |
| Max drawdown | $250 |
| Consistency violations | 2 |
| Would pass challenge | YES |

At a 43% win rate with 3:1 reward to risk, the expected value per trade is positive:

```
EV = (0.43 * $150) + (0.57 * -$35.71) = $64.50 - $20.35 = $44.15 per trade
```

Over 37 trades that projects to $1,633 — sufficient to pass the $1,500 challenge.

---

## Prop Firm Rules (Tradeify $25k)

| Rule | Value | How Bot Handles It |
|---|---|---|
| Profit Target | $1,500 | Tracks progress in real time |
| Trailing Max Drawdown | $1,000 | Monitors buffer, blocks when < $100 |
| Daily Loss Limit | None | Self-imposed $100 stop |
| Consistency Rule | 40% max per day | Uses 38% cap with auto-lock |
| Max Contracts | 10 MNQ | Bot uses 1 contract only |
| Instrument | MNQ on Tradovate | Fully configured |

---

## Roadmap

**Current (Signal Mode)**
* Real-time sweep and MSS detection
* 5-point confluence scoring
* macOS sound and popup notifications
* Trade monitoring (TP1, TP2, stop alerts)
* Full trade journal
* Morning briefing and session summary
* Adaptive smart filters
* Missed trade outcome tracking

**After Passing (Funded Account)**
* Full automation via Tradovate API (already coded in broker/)
* Bracket orders placed automatically
* Stop moved to break-even at TP1 automatically
* Position closed automatically at TP2
* Zero manual interaction required

**Future Improvements**
* Multi-session support (London session)
* Machine learning confluence scoring
* Multi-instrument support (MES, M2K)
* Web dashboard

---

## Disclaimer

This software is for educational and personal use only. Trading futures involves substantial risk of loss. Past backtest performance does not guarantee future results. Always trade within your risk tolerance and understand the rules of any prop firm evaluation you participate in.
