# MNQ Automated Trading Strategy — Tradeify $25k Challenge

## Situation Right Now
- **Platform:** Tradeify evaluation, $25k account on Tradovate
- **Already lost:** ~$400
- **Remaining drawdown buffer:** ~$600 (floor is $24,000 since trailing DD = $1,000 from start)
- **Target:** $1,500 profit to pass
- **Max contracts:** 10 MNQ (micros) — we will use 1–2 to stay safe
- **Instrument:** MNQ (Micro E-mini Nasdaq-100) = **$2 per point**

---

## The Critical Numbers Before We Write a Single Line of Code

### Tradeify Rule Breakdown
| Rule | Value | What It Means For Us |
|------|-------|----------------------|
| Profit Target | $1,500 | Need ~10–15 good trades |
| Trailing Max DD (EOD) | $1,000 | Floor moves UP as balance grows EOD |
| Daily Loss Limit | None | But we self-impose $100/day max loss |
| Consistency | 40% | No single day can be >40% of total profit made so far |
| Max Contracts | 10 MNQ | We use 1–2 max until consistently profitable |

### Consistency Rule Math (Very Important)
- If total profit so far = $300, one day cannot exceed $120 (40% of $300)
- System must track this in real time and refuse to open new trades if limit is near
- Target: spread wins across many days, never one blow-up win day

### Per-Trade Risk Math
```
Risk per trade:   $50 max  
MNQ = $2/point → $50 / $2 = 25 points max stop loss  
Min RR = 3:1   → Target = 75 points minimum  

With 2 MNQ contracts:  
  Stop  = 12–15 points (tighter, need better entry)  
  Target = 40–50 points  
  Win   = $80–$100 per trade  

Start with 1 MNQ until win rate is proven.
```

### Path to $1,500
```
Average win per trade:  $120 (3:1 on $40 risk with some variance)  
Win rate target:        55%+  
Trades per day:         2 max  
Days needed:            ~20–25 trading days (4–5 weeks)  
Daily profit cap (40%): Never exceed 40% of cumulative PnL in one day  
```

---

## Strategy: Enhanced TJR (Asia Session Sweep Model)

The TJR strategy is built on ICT (Inner Circle Trader) concepts. The core idea:
**Institutions clear out retail stop losses (the "sweep") before reversing price. We trade the reversal.**

### Original TJR Rules
1. Mark the Asia session range: high and low from **8:00 PM – 12:00 AM EST**
2. During London/NY session, watch for price to **sweep** (spike through) Asia High or Low
3. Wait for a **Market Structure Shift (MSS)** — a confirmed break of the previous swing
4. Enter inside a **Fair Value Gap (FVG)** left behind by the reversal candle
5. Stop below the sweep wick, target previous structure

### Why Just TJR Is Not Enough
Raw TJR gives too many signals. We filter with data-driven confluence scoring:

### Enhanced Entry Rules (All 5 Scored, Need 4+/5 to Trade)

| # | Filter | Bullish | Bearish |
|---|--------|---------|---------|
| 1 | Asia Sweep | Price swept Asia Low | Price swept Asia High |
| 2 | MSS Confirmed | Broke a prior swing high | Broke a prior swing low |
| 3 | FVG Present | Bullish FVG in entry zone | Bearish FVG in entry zone |
| 4 | VWAP Side | Price above session VWAP | Price below session VWAP |
| 5 | Time Window | Between 9:30–11:00 AM EST | Between 9:30–11:00 AM EST |

**Optional bonus confluences (recorded but not required):**
- Previous Day Low swept (for bullish) / Previous Day High swept (for bearish)
- Volume spike on the sweep candle (>1.5x average)
- 50% retracement of the sweep leg hit before entry

### Time Rules
- **9:00–9:30 AM:** Observe only. No trades. Mark Asia range, pre-market levels.
- **9:30–11:00 AM:** Active trading window. Best setups happen here.
- **11:00–11:30 AM:** Only take trade if signal is near-perfect (5/5 confluence). Otherwise done for the day.
- **After 11:30 AM:** System locked. No new orders.

### Stop Loss Placement
- Stop goes **below the sweep wick** (for longs) / **above sweep wick** (for shorts)
- Hard cap: never more than 25 points risk = $50 on 1 MNQ
- If the proper stop requires >25 points, **skip the trade entirely**

### Take Profit
- **TP1 (50%):** At 1.5:1 RR — move stop to break-even
- **TP2 (50%):** At 3:1 RR — full exit
- This locks in profit and removes pressure

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   TRADINGVIEW                           │
│  Enhanced TJR Pine Script → Alert triggered             │
│  Sends JSON webhook: {direction, entry, stop, target}   │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS POST (webhook)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              PYTHON FASTAPI SERVER                      │
│  (runs on your Mac or cheap $5/mo VPS)                  │
│                                                         │
│  1. Validate webhook secret                             │
│  2. Risk Manager checks:                                │
│     - Trade count today (<= 2)                          │
│     - Time window (9:30–11:30 AM EST)                   │
│     - Daily P&L (within limits)                         │
│     - Consistency rule (< 40% of total profit)          │
│     - Drawdown buffer remaining                         │
│  3. If approved → send to Tradovate API                 │
│  4. Log everything to trade journal                     │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API
                       ▼
┌─────────────────────────────────────────────────────────┐
│                TRADOVATE API                            │
│  Places bracket order:                                  │
│    - Entry (limit or market)                            │
│    - Stop loss (OCO)                                    │
│    - Take profit x2 (OCO)                               │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              TRADE JOURNAL (SQLite)                     │
│  Every trade logged: entry, exit, PnL, score,           │
│  reason, time, drawdown remaining                       │
│  Dashboard in terminal or simple web page               │
└─────────────────────────────────────────────────────────┘
```

---

## Project File Structure

```
trading-strategy/
│
├── plan.md                        # This file
├── requirements.txt               # Python dependencies
├── config.py                      # API keys, account settings (never commit)
├── .env                           # Secrets (gitignored)
│
├── strategy/
│   ├── __init__.py
│   ├── asia_range.py              # Detect and store Asia H/L
│   ├── mss_detector.py            # Market Structure Shift detection
│   ├── fvg_detector.py            # Fair Value Gap detection
│   ├── vwap.py                    # Intraday VWAP calculation
│   ├── confluence_scorer.py       # Score 1–5, require 4+ to trade
│   └── signal_generator.py        # Combines all above, outputs signal
│
├── risk/
│   ├── __init__.py
│   ├── risk_manager.py            # Core guard: drawdown, trades, time
│   ├── position_sizer.py          # Always $50 max risk, calc contracts/points
│   └── prop_firm_rules.py         # Tradeify-specific: consistency 40%, trailing DD
│
├── broker/
│   ├── __init__.py
│   ├── tradovate_client.py        # Tradovate REST + WebSocket wrapper
│   └── order_manager.py           # Place, monitor, cancel bracket orders
│
├── server/
│   ├── __init__.py
│   └── webhook_server.py          # FastAPI server that receives TV alerts
│
├── backtest/
│   ├── __init__.py
│   ├── data_loader.py             # Pull historical MNQ 1m/5m data
│   ├── engine.py                  # Replay bars, apply strategy, score results
│   └── results_analyzer.py        # Win rate, avg RR, max DD, consistency
│
├── journal/
│   ├── __init__.py
│   ├── trade_journal.py           # SQLite: log every trade and decision
│   └── dashboard.py               # Terminal dashboard showing today's stats
│
├── pine_script/
│   └── tjr_enhanced.pine          # TradingView script — copy/paste into TV
│
└── tests/
    ├── test_risk_manager.py
    ├── test_position_sizer.py
    └── test_confluence_scorer.py
```

---

## Implementation Phases

### Phase 1 — Backtest First, Build Confidence (Week 1)
**Goal:** Prove the strategy works on real MNQ historical data before touching live money.

**Tasks:**
1. `data_loader.py` — Pull 6 months of MNQ 1-minute data (free via Tradovate demo API or yfinance for NQ proxy)
2. `asia_range.py` — Define and mark 8 PM–midnight EST high/low for each session
3. `mss_detector.py` — Detect swing structure breaks on 1m/5m bars
4. `fvg_detector.py` — Identify 3-candle FVG patterns
5. `vwap.py` — Rolling intraday VWAP from session open
6. `confluence_scorer.py` — Score each potential entry 1–5
7. `engine.py` — Replay bars, fire signals at 4+ score, log hypothetical trades
8. `results_analyzer.py` — Output: win rate, avg winner, avg loser, max drawdown

**Success criteria before moving on:**
- Backtest win rate > 50%
- Avg RR achieved > 2.5:1
- Max simulated drawdown < $500 over 6 months
- Consistency rule never violated in sim

---

### Phase 2 — Tradovate API Integration (Week 2)
**Goal:** Connect Python to Tradovate DEMO account. Place orders automatically.

**Tasks:**
1. `tradovate_client.py`:
   - OAuth2 authentication (Tradovate uses access tokens)
   - REST: get account info, positions, P&L
   - WebSocket: stream live quotes for MNQ
   - Place bracket order (entry + stop + TP) as OCO
   - Cancel all orders emergency function
2. `position_sizer.py`:
   - Input: entry price, stop price
   - Output: number of MNQ contracts (1 or 2 max) such that loss <= $50
   - Always rounds DOWN (never risk more)
3. `order_manager.py`:
   - Track open orders
   - Move stop to break-even after TP1 hit
   - Hard timeout: force-close any position at 11:30 AM EST
4. `prop_firm_rules.py`:
   - Track daily P&L (real-time from Tradovate)
   - Track total P&L for consistency calculation
   - Alert + block if approaching 40% consistency limit
   - Alert + block if drawdown buffer drops below $200

**Demo testing:** Paper trade 2 full weeks on Tradovate sim before any live eval trading.

---

### Phase 3 — TradingView Pine Script + Webhook (Week 2–3)
**Goal:** Pine Script fires a webhook alert → Python server receives it → trade executes.

**Pine Script (tjr_enhanced.pine) features:**
```pinescript
// Inputs
asia_start   = 20:00 EST  
asia_end     = 00:00 EST  
trade_start  = 09:30 EST  
trade_end    = 11:30 EST  
min_score    = 4  

// Detects
asia_high, asia_low   → drawn on chart  
sweep_detected        → label on chart  
mss_confirmed         → label on chart  
fvg_zone              → box on chart  
vwap                  → line on chart  
confluence_score      → label: "Score: 4/5"  

// Alert fires when score >= 4 during trade window
// JSON payload sent to webhook:
{
  "secret": "{{your_secret_key}}",
  "symbol": "MNQ1!",
  "direction": "long",
  "entry": {{close}},
  "stop": 21450.25,
  "target": 21600.75,
  "score": 4,
  "reason": "Asia Low Sweep + MSS + FVG + VWAP"
}
```

**webhook_server.py (FastAPI):**
```
POST /webhook
  → validate secret key
  → call risk_manager.approve_trade()
  → if approved: tradovate_client.place_bracket_order()
  → log to journal
  → return 200 OK

GET /status
  → returns today's trades, P&L, drawdown remaining

POST /emergency_stop
  → cancels all orders, closes all positions
```

**Hosting options:**
- Option A: Run on your Mac (easiest to start — just keep it open during trading hours)
- Option B: $6/month VPS on DigitalOcean or Vultr (more reliable, runs 24/7)
- TradingView requires the webhook URL to be publicly accessible (HTTPS)
- For local Mac: use `ngrok` free tier during development

---

### Phase 4 — Paper Trading Full System (Week 3–4)
**Goal:** Run the complete pipeline end-to-end on Tradovate DEMO for 2 full weeks.

**Daily routine during paper trading:**
```
8:45 AM  → Start Python server + dashboard
9:00 AM  → Review Asia range marked on TradingView
9:30 AM  → System active, waiting for signals
11:30 AM → System locks, review trades
EOD      → Check journal: score accuracy, P&L, drawdown tracking
```

**Pass criteria for Phase 4:**
- Zero system errors over 10 trading days
- All risk rules firing correctly
- Consistency rule tracked accurately
- At least 60% of signals paper traded correctly

---

### Phase 5 — Live Evaluation (Week 5+)
**Goal:** Pass the Tradeify $25k challenge. Make $1,500. Protect the $600 buffer you have left.

**Live trading rules (hardcoded, non-negotiable):**
1. Max 2 trades per day
2. Max $50 loss per trade
3. Stop trading if down $100 on the day
4. Stop trading after $1,500 daily profit (though Tradeify has no daily limit, protect consistency)
5. No trades outside 9:30–11:30 AM EST
6. Minimum 4/5 confluence score — system rejects anything below
7. Emergency stop button available at any time

**Consistency rule management:**
- System calculates: `max_allowed_today = total_profit_so_far * 0.38` (leaves 2% buffer under 40%)
- Once daily P&L hits 38% of total, system auto-closes and locks for the day
- Target: roughly equal profitable days across the challenge period

---

## Risk Management Rules (Non-Negotiable)

```python
MAX_RISK_PER_TRADE   = 50      # dollars
MAX_TRADES_PER_DAY   = 2
MAX_DAILY_LOSS       = 100     # dollars (self-imposed, Tradeify has none)
MIN_CONFLUENCE_SCORE = 4       # out of 5
TRADE_START          = "09:30" # EST
TRADE_END            = "11:30" # EST
MAX_STOP_POINTS      = 25      # on MNQ ($50 / $2 per point)
MIN_TARGET_POINTS    = 75      # 3:1 RR minimum
CONSISTENCY_BUFFER   = 0.38    # use 38%, Tradeify rule is 40%
DRAWDOWN_ALERT       = 200     # alert when buffer < $200
DRAWDOWN_BLOCK       = 100     # block all trades when buffer < $100
```

---

## Trade Journal Fields
Every single trade logged automatically:

| Field | Example |
|-------|---------|
| timestamp | 2026-05-21 09:47:23 |
| direction | long |
| entry_price | 21,450.25 |
| stop_price | 21,425.00 |
| target_price | 21,525.75 |
| exit_price | 21,524.00 |
| contracts | 1 |
| pnl_dollars | +147.50 |
| score | 4/5 |
| score_breakdown | Asia Sweep ✓ MSS ✓ FVG ✓ VWAP ✓ Time ✓ |
| outcome | WIN - TP2 hit |
| drawdown_remaining | $820 |
| daily_pnl | +147.50 |
| total_pnl | +592.00 |
| consistency_used | 24.9% |

---

## Dependencies (requirements.txt)

```
fastapi>=0.111.0
uvicorn>=0.29.0
httpx>=0.27.0          # async HTTP for Tradovate REST
websockets>=12.0        # Tradovate WebSocket stream
python-dotenv>=1.0.0
pandas>=2.2.0           # data manipulation for backtest
numpy>=1.26.0
ta-lib                  # technical indicators
sqlite3                 # built into Python, trade journal
rich>=13.7.0            # beautiful terminal dashboard
schedule>=1.2.0         # time-based task runner
pytest>=8.0.0           # tests
```

---

## TradingView Setup Guide

### Account Requirements
- TradingView **Essential plan** or higher ($14.95/mo) — required for webhook alerts
- Chart: MNQ1! (Micro Nasdaq Continuous) on 1-minute or 5-minute chart

### Pine Script Installation
1. Open TradingView → Pine Script Editor
2. Paste content of `pine_script/tjr_enhanced.pine`
3. Add to chart
4. Set alert: condition = "TJR Signal Fired", webhook = your Python server URL

### Broker Connection (Tradovate)
- TradingView has native Tradovate integration (Paper and Live)
- This is a visual backup — our Python code is the actual executor
- Both can run simultaneously for redundancy

---

## Tradovate API Quick Reference

```python
# Authentication
POST /auth/accesstokenrequest
  body: {"name": "user", "password": "pass", "appId": "MyApp", "cid": 0, "sec": "secret"}
  returns: {"accessToken": "...", "expirationTime": "..."}

# Place Order (Bracket)
POST /order/placeorder
  body: {
    "accountSpec": "account_name",
    "symbol": "MNQM6",
    "action": "Buy",
    "orderQty": 1,
    "orderType": "Limit",
    "price": 21450.25,
    "bracket1": {"stopLoss": {"stopPrice": 21425.00}},
    "bracket2": {"takeProfit": {"limitPrice": 21525.75}}
  }

# Get Account P&L
GET /account/cashbalancelog

# WebSocket Stream (Live Quotes)
wss://md.tradovate.com/v1/websocket
  subscribe: {"op":"subscribe", "args":["md/subscribeQuote", {"symbol":"MNQM6"}]}
```

---

## What "Better Than TJR" Actually Means

| Original TJR | Enhanced Version |
|-------------|-----------------|
| Manual entry | Fully automated via webhook + API |
| No score filter | 4/5 confluence required |
| No VWAP filter | VWAP direction confirmation |
| Manual stop management | Auto break-even after TP1 |
| No prop firm awareness | Consistency rule tracked live |
| No journal | Every trade logged automatically |
| Subjective entries | Objective, backtested rules |
| No kill switch | Hard stop at $100/day, 11:30 AM lock |
| Emotion-driven | System executes, human only monitors |

---

## Build Order (What We Code First)

1. `risk/position_sizer.py` — The math must be right before anything else
2. `risk/risk_manager.py` — Safety first: guards that protect your $600 buffer
3. `risk/prop_firm_rules.py` — Tradeify-specific consistency tracker
4. `backtest/data_loader.py` — Get historical MNQ data
5. `strategy/asia_range.py` — Core TJR foundation
6. `strategy/mss_detector.py` — Signal quality
7. `strategy/fvg_detector.py` — Entry precision
8. `strategy/vwap.py` — Filter layer
9. `strategy/confluence_scorer.py` — The gatekeeper
10. `backtest/engine.py` — Prove it works on paper
11. `broker/tradovate_client.py` — Connect to money
12. `server/webhook_server.py` — The glue
13. `pine_script/tjr_enhanced.pine` — TradingView signal source
14. `journal/dashboard.py` — Real-time awareness

---

## Realistic Timeline

| Week | Focus | Milestone |
|------|-------|-----------|
| 1 | Backtest engine + strategy logic | See 6-month sim results |
| 2 | Tradovate API + risk manager | Paper orders placing correctly |
| 3 | Pine Script + webhook + full pipeline | Full system running on sim |
| 4 | 2 weeks paper trading | Zero errors, rules firing right |
| 5–9 | Live Tradeify evaluation | Target $1,500, protect $600 buffer |

---

## Before You Start the Eval Again
- Do NOT trade manually while building this — your $600 buffer is precious
- Run paper trades on Tradovate sim during build phase
- Only go live on eval when backtest AND paper trading both pass
- The system will be emotionless — that is the whole point

---

*Built for: Tradeify $25k | Instrument: MNQ | Hours: 9:30–11:30 AM EST | Strategy: Enhanced TJR (Asia Session Sweep + MSS + FVG + VWAP)*
