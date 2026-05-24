# Asia Session Sweep: Automated Futures Trading System

A real-time signal detection and risk management system for day trading futures. Built around the ICT/TJR Asia Session Sweep model with a 9-point confluence scoring system, 4-layer market context intelligence (VIX, SMT divergence, economic calendar, weekly levels), London session bias, order block entries, OTE zone detection, and adaptive smart filters. Works out of the box for MNQ on a $25k Tradeify evaluation. Fully configurable for any account size, instrument, or prop firm rules.

![Strategy Flow](images/strategy_flow.png)

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

## What This Is

This bot runs in your terminal every morning from 9:30 to 11:30 AM EST. You open it, read the morning briefing, then go do something else. If a valid signal forms it sends you a notification with exact entry, stop, and take profit numbers. You place the trade on your broker platform manually. The bot monitors the open position and alerts you at every milestone.

It does not place trades automatically in its current form. It is the detection and calculation layer. The full execution layer (bracket orders, stop management, break-even moves) is already coded and ready to activate when Tradovate API access is available on a funded account.

**What you need to run it:**

* Python 3.9+ on macOS
* Any broker platform open on the side (TradingView, Tradovate, etc.)
* A futures account (prop firm evaluation or live funded account)

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

## Adapt It to Your Account

Everything that controls risk, targets, and firm rules lives in `config.py`.

![Risk Scaling Reference](images/risk_scaling.png)

### Step 1: Set your risk per trade

```python
MAX_RISK_PER_TRADE = 50      # dollars you are willing to lose per trade
MAX_STOP_POINTS    = 25      # MNQ: 50 / $2 per point = 25 pts
MAX_DAILY_LOSS     = 100     # session auto-stops here
MAX_TRADES_PER_DAY = 2
```

**Formula for any account size:**

```
MAX_RISK_PER_TRADE = account_size * 0.002
MAX_STOP_POINTS    = MAX_RISK_PER_TRADE / dollars_per_point
MAX_DAILY_LOSS     = MAX_RISK_PER_TRADE * 2
```

### Step 2: Set your instrument

```python
TICKER            = "NQ=F"   # NQ=F, ES=F, RTY=F
DOLLARS_PER_POINT = 2.0      # MNQ=$2, MES=$5, NQ=$20, ES=$50
```

### Step 3: Set your prop firm rules

```python
STARTING_BALANCE      = 25_000
TRAILING_MAX_DRAWDOWN = 1_000
PROFIT_TARGET         = 1_500
CONSISTENCY_RULE      = 0.40    # Tradeify 40% single-day cap
CONSISTENCY_BUFFER    = 0.38    # bot stops at 38%, 2% safety margin
```

### Step 4: Adjust the minimum confluence score

```python
MIN_CONFLUENCE_SCORE = 4   # 4/9 = balanced, 5/9 = tighter, 6/9 = near-perfect only
```

The smart filter raises this dynamically based on conditions. This is the floor.

## The Strategy Explained

### Why This Works

Institutions push price through obvious stop levels to fill their own orders at better prices, then reverse. Retail traders have stops clustered just above session highs and just below session lows. When those stops get collected, the institutional order is filled and the reversal begins. This strategy identifies those moments using multiple layers of confirmation before entering.

### The Three-Session Framework

**Asia Session (8 PM to midnight EST):** Consolidation range forms overnight. The high and low of this range are the primary liquidity levels. Every retail stop in the building is sitting just outside these lines.

**London Session (2 AM to 8 AM EST):** Institutions begin positioning. In roughly 60 to 70 percent of sessions, London sweeps one side of the Asia range before New York opens. If London swept the Asia Low, institutions loaded longs overnight. The NY long setup has higher probability. The bot captures this bias before the first NY bar.

**New York Session (9:30 AM to 11:30 AM EST):** The only window where the bot takes trades. Session ends at 11:30 AM regardless of conditions. No midday or afternoon trading.

### The Setup: Five Steps

![Confluence Scoring](images/confluence_score.png)

**Step 1: Asia Range Formation**

8 PM to midnight, the bot records the session high and low. Previous Day High/Low and Previous Week High/Low are also computed.

**Step 2: London Bias Detection**

2 AM to 8 AM, the bot scans for London sweeps. Bullish (swept Low) adds confidence to NY longs. Bearish (swept High) adds confidence to NY shorts. Shown in the morning briefing.

**Step 3: The NY Sweep**

After 9:30 AM, the bot watches for price to break an Asia level. Sweep depth is measured. Sweeps under 20 points are noise and are rejected. Sweeps over 80 points are news spikes and are rejected. Backtest confirmed 0% win rate on sweeps below 20 points.

**Step 4: Market Structure Shift (MSS)**

After the sweep, the bot waits for confirmation. Price must close above a prior swing high (long) or below a prior swing low (short). The MSS candle is evaluated for displacement strength (body ratio and relative size). Weak MSS raises the required score by 1 point.

**Step 5: Order Block Entry and OTE Zone**

The bot identifies the last opposing candle before the displacement (the order block) and checks whether price has retraced into the ICT Optimal Trade Entry zone (61.8 to 78.6 percent Fibonacci retracement from the swing origin to the sweep extreme). OTE entries score point 9 and produce tighter stops with better reward-to-risk.

### The 9-Point Confluence Scoring System

A setup scores one point for each condition met. Minimum to fire is 4 points. The smart filter raises this dynamically based on context.

| Point | Condition | Meaning |
|---|---|---|
| 1 | Asia sweep detected | Required. No sweep, no trade. |
| 2 | MSS confirmed | Required. No structure break, no trade. |
| 3 | Fair Value Gap present | Imbalance zone in the entry area. |
| 4 | VWAP aligned | Price on the correct side of the daily average. |
| 5 | Prime time window | Signal fires 9:30 to 11:00 AM. |
| 6 | PDH/PDL confluence | Sweep also takes out a previous day level. |
| 7 | Opening range opposed | Setup reverses the 9:30 AM retail trap. |
| 8 | Weekly level confluence | Sweep also takes out the previous week H/L. |
| 9 | OTE zone entry | Price is in the 61.8 to 78.6% Fibonacci zone. |

London alignment and MSS strength are not scored but they raise the threshold. A setup with weak MSS or opposing London direction requires 1 extra point to fire.

### Entry, Stop, and Targets

**Entry:** Limit at the order block price. Falls back to fixed limit if no valid OB exists.

**Stop Loss:** 1 point beyond the order block wick. Fixed at 25 points for fallback entries.

**Take Profit 1:** 1.5x the stop distance. When hit, stop moves to break-even. Trade is now risk-free.

**Take Profit 2:** 3.0x the stop distance. Minimum 3:1 reward-to-risk on every trade.

**MNQ math:** $2.00 per point. 25-point stop on 1 contract = $50 risk. TP2 at 75 points = $150 profit.

## How the Bot Works

### Startup

When you run `python3 live_detector.py`:

1. Fast price feed starts (background thread, updates every 0.5 seconds)
2. 60 days of 5-minute bar data downloads. ES futures data downloads for SMT checks. VIX downloads for regime classification.
3. London session is analyzed and bias is determined before briefing
4. Morning briefing prints: Asia levels, London bias, VIX regime, news calendar, prev week H/L, SMT status, account buffer, consistency cap, ICT day phase, min score today, game plan
5. Main detection loop begins

### Morning Briefing

Every morning at startup you see:

* **Account panel:** balance, drawdown buffer, total P&L, win/loss streak, day profile (Monday = Accumulation, Tuesday = Manipulation, etc.)
* **Market context panel:** VIX level and regime, news calendar status, any blackout windows, previous week H/L, ES/NQ SMT status
* **Key levels panel:** current price, Asia High and Low, distances, Prev Day H/L
* **London bias panel:** what London did overnight and directional implication
* **Consistency cap panel:** if in profit, shows the max you can make today (Tradeify 40% rule)
* **Game plan panel:** what to watch for, entry rules, min score, risk/target

### After a Signal Fires

![Terminal Signal](images/terminal_signal.png)

1. Large colored panel prints with entry, stop, TP1, TP2, score breakdown, London bias, MSS strength, OTE status, SMT status
2. macOS notification fires even if terminal is minimized
3. Bot asks whether you took the trade
4. If yes: live monitoring starts, watching TP1, TP2, and stop
5. When TP1 hits: alert fires, move stop to break-even
6. When TP2 or stop hits: result is recorded in the journal

Skipped trades are also tracked and reported at end of session.

## Smart Adaptive Features

### 4-Layer Market Context System

The bot builds a full market context picture at the start of each day and updates it when sweeps are detected.

**Layer 1: VIX Regime**

Downloads live VIX data every morning. Classifies the volatility environment.

| VIX Level | Regime | Effect |
|---|---|---|
| Below 15 | Low | Standard thresholds |
| 15 to 20 | Medium | Standard thresholds |
| 20 to 25 | High | No change (backtest: high VIX favors short sweeps) |
| 25 to 30 | Very High | No change |
| Above 30 | Extreme | Raise threshold |

Shown in the morning briefing every day.

**Layer 2: ES/NQ SMT Divergence**

Downloads ES futures data (E-mini S&P 500) and checks whether ES confirms the NQ sweep. If NQ sweeps the Asia Low but ES holds above its own range, this is a divergence. Institutions use ES as the primary instrument. NQ divergence signals are fakes.

Backtest result: SMT divergent signals had 0% win rate. These signals are now hard-blocked in both the bot and the Pine Script.

**Layer 3: Economic Calendar**

Hardcoded 2026 schedule for NFP, CPI, FOMC, and weekly jobless claims.

| Event | Rule |
|---|---|
| Thursday 8:30 AM (jobless claims) | Hard blackout 8:10 to 8:45 AM. +1 score required all session. |
| NFP, CPI (8:30 AM days) | 20-minute pre-release blackout. 15-minute post-release blackout. +2 required all session. |
| FOMC days | +2 required all session. |

**Layer 4: Weekly Levels (Power of 3)**

Previous week high and low are computed from the bar data. When a sweep also takes out a weekly level, point 8 is scored. Two liquidity pools cleared in one move is a much stronger signal.

The morning briefing shows the previous week H/L every day.

### ICT Power of 3 Day Profiles

Each day of the week has a known institutional behavior pattern. The bot applies this every morning.

| Day | ICT Phase | Behavior | Min Score |
|---|---|---|---|
| Monday | Accumulation | Range forms, both sides may sweep. Strong day overall. | 4/9 |
| Tuesday | Manipulation (Judas Swing) | First sweep is often fake. Real move starts Wednesday. | 8/9 |
| Wednesday | Distribution | Real weekly direction begins. Best day for setups. | 4/9 |
| Thursday | Continuation | Claims at 8:30 creates unpredictable spike. Hard blackout added. | 8/9 |
| Friday | Close | Profit taking and liquidity close. Normal rules apply. | 4/9 |

Tuesday is called the Judas Swing day in ICT theory. Institutions run price in the wrong direction to collect stops before the real weekly move starts Wednesday. The first sweep on Tuesday is frequently a trap. The bot requires 8/9 to fire on Tuesday and Thursday, which in backtest testing eliminated all signals on those days.

### Sweep Depth Filter

Backtest data on 60 days of NQ showed a clean threshold:

| Depth | Win Rate | Action |
|---|---|---|
| 0 to 20 pts | 0% | Hard rejected. Not recorded. |
| 20 to 30 pts | Variable | Requires elevated score |
| 30 to 80 pts | 89% | Standard thresholds apply |
| Above 80 pts | Skip | News event spike |

The minimum sweep depth was raised from 8 to 20 points based on this data.

### OTE Zone (Optimal Trade Entry)

After a sweep is detected, the bot computes the 61.8 to 78.6 percent Fibonacci retracement from the swing origin to the sweep extreme. If price retraces into this zone before MSS confirmation, point 9 is scored. This is where institutional traders re-enter after clearing liquidity. OTE entries have tighter natural stops and higher R:R.

Shown as a green (bull) or red (bear) box on the Pine Script chart.

### London Session Bias

Before the NY open, the bot records whether London swept the Asia Low (bullish), Asia High (bearish), both, or neither. A NY signal that conflicts with the London direction requires 1 extra point to fire.

### MSS Displacement Strength

The MSS candle is evaluated. Body ratio above 55% and candle size above 1.3x the 10-bar average = strong MSS. Weak MSS raises the required score by 1 point.

### Loss Streak Protection

After two consecutive losses the minimum score rises to 6/9 automatically. Only near-perfect setups fire until a winner is recorded. Prevents compounding losses on bad days.

### Persistent Bot Memory

The bot writes `memory/bot_memory.json` after every trade. After 8 or more trades in a category, real observed win rates replace the hardcoded baseline thresholds. Categories tracked: day of week, confluence score, signal hour, London alignment, MSS strength, sweep depth, entry type, direction.

After enough live trading data accumulates, Tuesday and Thursday thresholds will be calibrated to your specific performance rather than using the backtest baseline.

## System Architecture

```
Live Price Feed (yfinance 5m bars, background thread)
         |
         v
   Market Context Builder
     VIX regime (^VIX daily)
     SMT divergence (ES=F 5m bars)
     Economic calendar (hardcoded 2026)
     Weekly levels (prev week H/L from bar data)
         |
         v
   London Bias Detection (2-8 AM bars)
         |
         v
   Asia Range Builder (8 PM to midnight bars)
         |
         v
   Sweep Detector (checks depth: 20 to 80 pts only)
         |
     Sweep found and depth valid
         |
         v
   SMT Check (does ES confirm the NQ sweep?)
         |
     Not divergent
         |
         v
   OTE Zone Computer (61.8 to 78.6% Fibonacci zone)
         |
         v
   MSS Detector (swing pivots, structure break, displacement strength)
         |
     MSS confirmed
         |
         v
   Order Block Finder (last opposing candle before displacement)
         |
         v
   Confluence Scorer (9-point check)
         |
         v
   Smart Filter (DOW base, context penalty, streak, time, sweep depth)
         |
     Score meets threshold
         |
         v
   News Calendar Check (blackout window?)
         |
     Not in blackout
         |
         v
   Risk Manager (daily limits, drawdown buffer, consistency cap)
         |
     Approved
         |
         v
   Signal Output (terminal panel + macOS notification)
         |
         v
   You Execute on Broker Platform
         |
         v
   Trade Monitor (TP1, TP2, stop in real time)
         |
         v
   Bot Memory Update (win rates by category)
         |
         v
   Journal Update (SQLite, balance, streak, stats)
```

## File Structure

```
trading-strategy/
|
|-- live_detector.py          Main entry point. Run this every morning.
|-- backtest_run.py           Run strategy on 60 days of historical data.
|-- config.py                 All settings: risk, timing, instrument, thresholds.
|-- briefing.py               Morning briefing and end-of-session summary.
|-- bot_memory.py             Persistent JSON win rate memory across sessions.
|-- notifications.py          macOS sound and popup alerts.
|
|-- strategy/
|   |-- asia_range.py         Asia session high/low detection.
|   |-- mss_detector.py       MSS confirmation and displacement strength.
|   |-- order_block.py        Order block entry detection.
|   |-- london_session.py     London session bias analysis.
|   |-- fvg_detector.py       Fair Value Gap identification.
|   |-- vwap.py               Intraday VWAP calculation.
|   |-- confluence_scorer.py  9-point scoring system.
|   |-- smart_filter.py       Adaptive filters (DOW, streak, time, sweep depth, context).
|   |-- market_context.py     VIX regime, SMT divergence, economic calendar, weekly levels.
|
|-- risk/
|   |-- position_sizer.py     Contract sizing based on MAX_RISK setting.
|   |-- account_state.py      Trailing drawdown, consistency cap, buffer tracking.
|   |-- risk_manager.py       Trade approval gateway.
|
|-- tradovate/
|   |-- executor.py           Tradovate REST and WebSocket API (ready for funded account).
|
|-- backtest/
|   |-- data_loader.py        Historical data via yfinance.
|   |-- engine.py             Bar-by-bar simulation with full context integration.
|   |-- results_analyzer.py   Breakdowns: day, direction, score, sweep, VIX, SMT, OTE.
|
|-- pine_script/
|   |-- tjr_enhanced.pine     TradingView Pine Script v5 (visual reference only).
|
|-- journal/
|   |-- trade_journal.py      SQLite trade database.
|
|-- memory/
|   |-- bot_memory.json       Persistent win rate memory (auto-created on first trade).
|
|-- images/                   README diagrams.
```

## Backtest Results

Run `python3 backtest_run.py` to test against the most recent 60 days of data. Results from a 3-round iteration on March to May 2026 MNQ data with default $25k Tradeify configuration:

**Iteration history:**

| Round | Change Made | Win Rate | Trades | P&L |
|---|---|---|---|---|
| Baseline | Original filters | 40% | 20 | $803 |
| Round 2 | Raised Tue/Thu threshold to 8/9 | 67% | 12 | $1,077 |
| Round 3 | Sweep depth 20 pts min, SMT hard block | 89% | 9 | $1,118 |

**Final backtest results:**

| Metric | Result |
|---|---|
| Backtest period | 60 days (49 trading days) |
| Total trades taken | 9 |
| Win rate | 89% (8W / 1L) |
| Average win | $146 |
| Average loss | $50 |
| Total P&L | $1,118 |
| Max simulated drawdown | $250 |
| Drawdown limit | $1,000 |
| Consistency violations | 2 |
| Days traded | 7 of 49 |

**Day-of-week breakdown:**

| Day | Trades | Win Rate | Notes |
|---|---|---|---|
| Monday | 3 | 100% | Best day. Trust clean setups. |
| Tuesday | 0 | Blocked | 8/9 threshold eliminates Judas Swing traps. |
| Wednesday | 4 | 100% | Real weekly direction begins. Strong day. |
| Thursday | 0 | Blocked | 8/9 threshold plus jobless claims blackout. |
| Friday | 2 | 50% | Normal rules. Small sample. |

**Sweep depth breakdown:**

| Depth | Win Rate | Action |
|---|---|---|
| 0 to 20 pts | 0% | Hard rejected at sweep detection. |
| 20 to 30 pts | 0% | Passes depth filter but requires elevated score. |
| 30 to 80 pts | 89% | The real institutional move. |

**Market context breakdown:**

| Context | Win Rate | Notes |
|---|---|---|
| SMT confirmed (ES aligned) | 89% | All winning trades. |
| SMT divergent | 0% | Hard blocked. |
| High VIX (>20) | 100% | High vol trending markets favor short sweep setups. |
| News penalized (Thu, events) | 0% | Hard blocked or threshold raised too high to fire. |

The low trade count is intentional. The multi-layer filter rejects the vast majority of setups. Only setups where every condition lines up are taken. At roughly 1 to 2 trades per week with an 89% win rate and $146 average win, the path to passing a $1,500 Tradeify target from a standing start is approximately 8 to 10 weeks.

## Trade Journal

Every signal is recorded whether you took it or not. To view:

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
| Score | Confluence score (x/9) |
| London | London bias at signal time |
| MSS strength | Strong or weak |
| VIX regime | Volatility environment |
| SMT status | ES confirmed or divergent |
| OTE | Whether price was in OTE zone |
| P&L | Dollar result |
| Outcome | WIN / LOSS / BE / SKIPPED |
| Buffer | Drawdown buffer remaining |

## Disclaimer

This software is for educational and personal use only. Trading futures involves substantial risk of loss. Past backtest performance does not guarantee future results. Always trade within your risk tolerance and follow the rules of any account or evaluation you participate in.
