# SETUP GUIDE — How to Go Live Tomorrow

## Step 1 — Install Dependencies (5 minutes)
```bash
cd "/Users/cliff/Desktop/trading startegy"
pip install -r requirements.txt
```

## Step 2 — Get Tradovate API Credentials (10 minutes)
1. Go to **trader.tradovate.com** (your Tradeify account uses this)
2. Sign in with your Tradeify email/password
3. Top right → Account Settings → **API Access**
4. Click "Create App" → name it "TJRBot"
5. Copy the **CID** (client ID) and **SEC** (client secret)

## Step 3 — Set Up Your .env File (2 minutes)
```bash
cp .env.example .env
```
Edit `.env` with your real values:
```
TRADOVATE_USERNAME=your_tradeify_email
TRADOVATE_PASSWORD=your_tradeify_password
TRADOVATE_CID=123456         # from step 2
TRADOVATE_SECRET=abc123xyz   # from step 2
TRADOVATE_DEMO=true          # change to false when ready to go LIVE
WEBHOOK_SECRET=pick-something-random-and-long
```

## Step 4 — Run the Backtest (5 minutes)
```bash
python backtest_run.py
```
Review the results. If win rate is below 50% or max drawdown simulation > $800, tell Claude so we can tune.

## Step 5 — Run the Tests (2 minutes)
```bash
pytest tests/ -v
```
All tests should pass.

## Step 6 — Test the Server Locally (5 minutes)
```bash
python main.py
```
In a second terminal:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/status
```
You should get JSON back.

## Step 7 — Expose the Server to TradingView (10 minutes)
TradingView webhooks need a public HTTPS URL.

**Option A — ngrok (free, easiest for testing):**
```bash
# Install ngrok: brew install ngrok
ngrok http 8000
```
Copy the `https://xxxx.ngrok.io` URL.

**Option B — DigitalOcean $6/mo VPS (more reliable, recommended for live):**
- Create a Droplet running Ubuntu
- Clone this project there
- Run `python main.py` in a `screen` or `tmux` session
- Use the Droplet's IP + port 8000, or set up nginx

## Step 8 — Set Up TradingView (10 minutes)
1. Open TradingView → chart: **MNQ1!** on **5-minute** timeframe
2. Pine Script Editor → paste contents of `pine_script/tjr_enhanced.pine`
3. Save → Add to chart
4. Right-click → "Add Alert"
5. Condition: "TJR Long Signal" or "TJR Short Signal"
6. Alert actions: ✅ Webhook URL → paste your ngrok/VPS URL + `/webhook`
7. Alert message (JSON payload — MUST match this format exactly):
```json
{
  "secret": "your-webhook-secret-from-env",
  "symbol": "{{ticker}}",
  "direction": "long",
  "entry": {{close}},
  "stop": {{plot_0}},
  "target": {{plot_1}},
  "score": 4,
  "asia_high": {{plot_2}},
  "asia_low": {{plot_3}},
  "vwap": {{plot_4}},
  "asia_sweep": true,
  "mss_confirmed": true,
  "fvg_active": true,
  "vwap_aligned": true,
  "in_time_window": true
}
```
8. Create a separate alert for SHORT signals with `"direction": "short"`

## Step 9 — Go LIVE
1. In `.env`, change `TRADOVATE_DEMO=false`
2. Restart `python main.py`
3. Be at your desk at 9:00 AM EST
4. At 9:30 AM the system activates — watch the terminal
5. **Emergency stop:** `curl -X POST http://localhost:8000/emergency_stop`

---

## Active Contract Symbol
MNQ rolls quarterly. Update the `_get_active_mnq_symbol()` function in `server/webhook_server.py` if the auto-detection is wrong.

Current MNQ contracts:
- March → MNQH25
- June  → MNQM25
- September → MNQU25
- December → MNQZ25

---

## Daily Routine
```
8:45 AM  → python main.py (start server)
9:00 AM  → Check TradingView: Asia range drawn on chart?
9:30 AM  → System active, waiting for sweep + MSS
           You watch, system executes
11:30 AM → System locks (no new orders)
           Check /status for the day's results
EOD      → Update state.setup(already_lost=X) in webhook_server.py
           with your actual current loss vs starting balance
```

---

## Emergency Contacts
- Stop all trading: `curl -X POST http://localhost:8000/emergency_stop`
- Check status: open browser to `http://localhost:8000/status`
- Kill the server: Ctrl+C in terminal
