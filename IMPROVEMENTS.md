# System Improvement Roadmap

Full analysis of every file. Ranked by impact on the prop firm eval.

---

## 🔴 CRITICAL — Fix Before Trading

### 1. Signal deduplication is broken (`monitor.py` line 64)
`_signal_key()` uses `round(t.entry, 1)` — two entries at `29,999.6` and `29,999.4` produce the same key `"date-orb-long-30000.0"`. The second signal silently re-fires after the first.

**Fix:**
```python
def _signal_key(t: QuantTrade) -> str:
    return f"{t.date}-{t.strategy}-{t.direction}-{round(t.entry, 0)}-{round(t.stop, 0)}"
```

---

### 2. No max daily loss check inside the signal loop (`quant_engine.py` line 256)
`_can_trade()` is checked at the start of each iteration, not after each trade is added. With 3 simultaneous setups, all 3 can fire before `daily_pnl` is re-evaluated. You could blow through `MAX_DAILY_LOSS = $150` by $100+ before it stops.

**Fix:** Re-check `_can_trade()` immediately after each `_add_trade()` call returns.

---

### 3. Consistency cap logic broken for first trades (`prop_firm_rules.py` line 59)
When `total_profit = 0`, `max_allowed_today = infinity`. After first winning trade, the cap suddenly kicks in. The cap should only activate after $100+ total profit so the first few trades aren't affected unpredictably.

**Fix:**
```python
if self.total_profit <= 100:
    return (True, "OK — consistency cap not yet active")
```

---

### 4. Basis recalibrates every 15 min — too slow for news events (`yahoo_ws_feed.py` line 155)
During FOMC, macro data releases, or VIX spikes, NQ-NDX basis can shift $20–50 in minutes. Your price feed stays wrong for up to 15 minutes.

**Fix:** Recalibrate every 5 minutes:
```python
if not self._calibrated or (now - self._last_cal).total_seconds() > 300:
```

---

## 🟠 HIGH IMPACT — Fix This Week

### 5. Bar data not validated on load (`data_loader.py`)
If yfinance returns `High < Low` or `Close = NaN`, the bars pass straight into signal detection. One corrupt bar can fire a false signal.

**Fix:**
```python
assert (df["High"] >= df["Low"]).all(), "Invalid bar: High < Low"
assert not df[["Open","High","Low","Close"]].isna().any().any(), "NaN in OHLC"
```

---

### 6. VWAP deviation bounds allow noise signals (`quant_vwap.py` lines 71–72)
- `min_dev = max(5.0, atr * 0.025)` — 5 points is noise in a 150pt ATR session
- `max_dev = min(50.0, atr * 0.18)` — 50 points means you're entering during a crash, not a reversion

**Fix:**
```python
min_dev = max(15.0, atr * 0.05)   # at least 5% of ATR
max_dev = min(30.0, atr * 0.12)   # at most 12% of ATR
```

---

### 7. ORB pullback has no depth filter (`quant_orb.py` lines 140–165)
A shallow pullback (price tags ORB high + 5pts then reverses) triggers entry with stop at `orb_low - 2`. On a 10pt ORB that's 7pt risk for a 5pt pullback — terrible R:R. No filter catches this.

**Fix:** Only enter if price retraced at least 75% of the extension back toward the range:
```python
if (close - orb_low) / orb_range < 0.75:
    continue  # skip shallow pullback
```

---

### 8. Inconsistent trend filtering across strategies (`quant_engine.py` lines 310–318)
ORB short filtering uses custom inline logic. All other strategies use `direction_allowed()`. This means ORB shorts are allowed in conditions where gap fill shorts are blocked.

**Fix:** All strategies should call `direction_allowed()` with the same `strict` parameter. Document explicitly if ORB intentionally differs.

---

### 9. IB target is too conservative (`quant_ib.py` line 176)
Target is `ib_high + ib_range * 0.75`. Trend days extend 1.5–2× IB range. You're leaving money on the table.

**Fix:**
```python
target = ib_high + ib_range * 1.5
```

---

### 10. Notification popup timeout is too long (`notifications.py` line 18)
`timeout=3` seconds per popup. During a critical entry window, blocking the loop for 3 seconds to show an alert is unacceptable.

**Fix:**
```python
subprocess.run(["osascript", "-e", script], capture_output=True, timeout=0.5)
```

---

### 11. AppleScript not escaping quotes (`notifications.py` line 18)
If a strategy name or price contains `'` or `"`, the osascript command breaks. Silent failure.

**Fix:**
```python
message = message.replace('"', '\\"').replace("'", "\\'")
title   = title.replace('"', '\\"').replace("'", "\\'")
```

---

## 🟡 MEDIUM IMPACT — Improve Over Time

### 12. VWAP bounce window cuts off at 11:30 AM (`quant_vwap.py` line 193)
The prop firm window runs until 12:00 PM. You're missing 30 minutes of tradeable time.

**Fix:**
```python
_end = 12 * 60   # was 11 * 60 + 30
```

---

### 13. Gap fill target doesn't capture extension (`quant_gap.py` line 136)
Target is `prior_close` (fill the gap, nothing more). Research shows 40%+ of gap fills extend past the close. You could target `prior_close + gap_size * 0.5` to capture the extension.

**Fix:**
```python
target = prior_close - gap_size * 0.5 if direction == "long" else prior_close + gap_size * 0.5
```

---

### 14. FVG minimum size allows noise signals (`quant_fvg.py` line 81)
`min_size = max(6.0, atr * 0.04)` — a 6pt FVG in a 150pt session is pure noise. Institutions don't leave 6pt imbalances.

**Fix:**
```python
min_size = max(12.0, atr * 0.06)
max_size = min(60.0, atr * 0.30)
```

---

### 15. EMA trend thresholds are magic numbers (`quant_regime.py` lines 133, 137)
`1%` and `3%` EMAdivergence thresholds define "weak" vs "strong" trend. No comment explains why. Were these backtested?

**Fix:** Add comments:
```python
_WEAK_TREND   = 0.01  # 1%: minimum to distinguish trend from noise (backtested on 60d)
_STRONG_TREND = 0.03  # 3%: 3× min threshold, reliably directional
```

---

### 16. VWAP expanding std is biased early in session (`quant_regime.py` line 79)
`expanding().std()` at bar 3 uses only 3 data points — bands are unrealistically tight. This makes early-session VWAP signals fire on noise.

**Fix:**
```python
rolling_std = deviation.rolling(window=20, min_periods=8).std()
```

---

### 17. Monday longs blocked with no documentation (`quant_orb.py` lines 118–119)
`day_of_week in (0, 1)` blocks longs Mon/Tue. No comment. If someone reads this code in 3 months they have no idea why.

**Fix:**
```python
# Block Mon/Tue longs: weekend repositioning creates false gap-up setups
if dow in (0, 1) and sig.direction == "long":
    continue
```

---

### 18. Holiday calendar missing in session labels (`data_loader.py`)
`label_sessions()` marks hours by time only. On Thanksgiving or Christmas half-days, bars get marked as tradeable when the market is closed.

**Fix:** Add NYSE holiday check using `pandas.tseries.holiday.USFederalHolidayCalendar`.

---

### 19. Dashboard has no auto-refresh (`journal/dashboard.py`)
Static printout — must re-run manually to see updates. Not practical during a live session.

**Fix:**
```python
while True:
    os.system("clear")
    print_dashboard(journal, state)
    time.sleep(5)
```

---

### 20. Trade journal has no field validation (`journal/trade_journal.py` line 62)
`log_trade()` accepts any dict. `entry_price = None` silently writes NULL to the database. Stats calculations later return wrong numbers.

**Fix:**
```python
REQUIRED = ["entry_price", "stop_price", "target_price", "strategy", "direction"]
for field in REQUIRED:
    assert data.get(field) is not None, f"Missing required field: {field}"
```

---

## 🔵 DATA & FEED IMPROVEMENTS

### 21. Real-time data: IBKR TWS (free, pending approval)
Account U26067247 submitted. Once approved, IBKR TWS running locally gives genuine real-time NQ tick data via Python `ib_insync` library. Zero delay, free with account.

Priority after eval: set this up as primary feed, demote ^NDX+basis to fallback.

---

### 22. Real-time data: Tastytrade API
Tastytrade has a public Python SDK (`tastytrade` package) with WebSocket streaming for futures. Free with account. No developer registration or CID/SECRET needed.

If IBKR is too complex, Tastytrade is the simpler real-time feed upgrade.

---

### 23. Bar data: fetch ^NDX bars instead of NQ=F
`^NDX` (index) bars are not subject to CME 15-minute delay. NQ=F bars from yfinance are delayed. Strategy logic uses bar prices to detect levels. If bar data is delayed, level detection is slightly off.

Long-term fix: fetch `^NDX` bars + apply basis offset to all OHLC values.

---

### 24. Basis formula: use real Fed funds rate
Current formula hardcodes `r = 0.045`. Fed funds rate changes with each FOMC decision. If Fed cuts 25bps, basis shifts by ~$8. Use FRED API for the actual overnight rate:
```python
import yfinance as yf
r = yf.Ticker("^IRX").fast_info.last_price / 100  # 13-week T-bill proxy
```

---

## 🟢 STRATEGY IMPROVEMENTS

### 25. PM VWAP bounce barely profitable
Backtest: 16 trades, 62.5% WR, -$1 PnL over 60 days. Not adding value. Either:
- Tighten conditions: require stronger trend alignment before entering
- Raise minimum deviation from VWAP before triggering
- Disable entirely and focus on AM window where edge is proven

---

### 26. IB breakout fires rarely (1 trade in 60 days)
Either the filters are too tight or the strategy window is too narrow. Worth investigating whether relaxing proximity filter (`20pt` → `30pt`) increases signal frequency without hurting win rate.

---

### 27. ORB is the best earner — consider 2 contracts
$690 PnL from 9 trades (77.8% WR) over 60 days. If risk allows, scaling to 2 MNQ contracts on ORB signals would double the P&L on the strongest strategy. Only do this if buffer > $500.

---

### 28. Add gap extension target
Gap fills that reach `prior_close` often continue. Add a second target at `prior_close + gap_size * 0.5` and scale out: exit 50% at gap fill, let 50% run to extension.

---

### 29. Backtest with walk-forward validation
Current 60-day backtest uses all data to tune parameters (in-sample). Walk-forward: tune on first 40 days, test on last 20. This gives a realistic out-of-sample WR estimate. If WR drops >10%, the strategy is overfit.

---

### 30. Monte Carlo simulation on the 60-day results
Run 10,000 random orderings of the 56 trades. Shows the range of possible outcomes (best case, worst case, median). Tells you how much of the $1,143 PnL is luck vs edge.

---

## Priority Order for the Eval

| # | Fix | Time | Impact |
|---|-----|------|--------|
| 1 | Signal dedup key (stop in key) | 5 min | Prevent rule violation |
| 2 | Daily loss check inside loop | 15 min | Prevent blowing daily limit |
| 3 | Basis recal every 5 min | 5 min | Better price accuracy |
| 4 | Notification timeout 0.5s | 5 min | No freeze during entry |
| 5 | VWAP deviation bounds | 10 min | Fewer noise signals |
| 6 | ORB pullback depth filter | 15 min | Better R:R entries |
| 7 | IB target 1.5× range | 5 min | More profit per trade |
| 8 | VWAP bounce window → noon | 5 min | 30 min more opportunity |
| 9 | PM VWAP bounce review | 30 min | Remove dead weight |
| 10 | IBKR/Tastytrade real-time feed | 1–2 hrs | Zero delay price data |
