import os
from dotenv import load_dotenv

load_dotenv()

# Tradovate credentials
TRADOVATE_USERNAME = os.getenv("TRADOVATE_USERNAME", "")
TRADOVATE_PASSWORD = os.getenv("TRADOVATE_PASSWORD", "")
TRADOVATE_APP_ID = os.getenv("TRADOVATE_APP_ID", "TJRBot")
TRADOVATE_APP_VERSION = os.getenv("TRADOVATE_APP_VERSION", "1.0")
TRADOVATE_CID = int(os.getenv("TRADOVATE_CID", "0"))
TRADOVATE_SECRET = os.getenv("TRADOVATE_SECRET", "")
TRADOVATE_DEMO = os.getenv("TRADOVATE_DEMO", "true").lower() == "true"

TRADOVATE_BASE_URL = (
    "https://demo.tradovateapi.com/v1"
    if TRADOVATE_DEMO
    else "https://live.tradovateapi.com/v1"
)
TRADOVATE_MD_WS_URL = "wss://md.tradovateapi.com/v1/websocket"

# Webhook
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-me-to-something-random")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8000"))

# ── Risk parameters (non-negotiable) ──────────────────────────────────────────
MAX_RISK_PER_TRADE   = 50       # dollars
MAX_TRADES_PER_DAY   = 2       # 2 high-quality 15m setups beats 4 noisy 5m entries
MAX_DAILY_LOSS       = 100      # dollars — 2 × $50 max-risk trades
MIN_CONFLUENCE_SCORE = 4        # out of 12; shorts need 7+ via smart_filter
TRADE_START_HOUR     = 9
TRADE_START_MIN      = 30
TRADE_END_HOUR       = 12      # Noon — captures London close sweep window
TRADE_END_MIN        = 0
MAX_STOP_POINTS      = 25       # MNQ: $50 / $2 per point
SWEEP_TIMEOUT_MINUTES = 90     # Reset sweep detection after 90 min without MSS
MIN_TARGET_RR        = 3.0      # Minimum reward-to-risk (all setups)
MAX_TARGET_RR        = 5.0      # Maximum reward-to-risk (best setups)
CONSISTENCY_BUFFER   = 0.38     # fire at 38%; Tradeify rule is 40%
DRAWDOWN_ALERT       = 200      # warn when remaining buffer < $200
DRAWDOWN_BLOCK       = 100      # hard block when remaining buffer < $100

# ── Backtest default timeframe ─────────────────────────────────────────────────
BACKTEST_INTERVAL    = "15m"    # 15m: absorbs 5m whipsaw, better signal quality

# ── Tradeify account constants ─────────────────────────────────────────────────
STARTING_BALANCE       = 25_000
TRAILING_MAX_DRAWDOWN  = 1_000
PROFIT_TARGET          = 1_500
CONSISTENCY_RULE       = 0.40
MAX_CONTRACTS_MNQ      = 10

# ── Instrument ─────────────────────────────────────────────────────────────────
MNQ_DOLLARS_PER_POINT  = 2.0    # $2 per index point on Micro Nasdaq
MNQ_TICK_SIZE          = 0.25   # minimum price movement
MNQ_SYMBOL             = "MNQ"  # base symbol; active contract e.g. MNQM5

# ── Session times (EST / New York) ────────────────────────────────────────────
ASIA_SESSION_START_HOUR = 20    # 8:00 PM
ASIA_SESSION_START_MIN  = 0
ASIA_SESSION_END_HOUR   = 0     # midnight (next calendar day)
ASIA_SESSION_END_MIN    = 0
