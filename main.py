"""
Main entry point — starts the webhook server.

Before running:
  1. Copy .env.example to .env and fill in your Tradovate credentials
  2. Set TRADOVATE_DEMO=true for testing, false for live
  3. Run ngrok (for local testing): ngrok http 8000
  4. Add the ngrok URL as your TradingView alert webhook URL

Usage:
  python main.py
"""
import logging
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from server.webhook_server import app
from config import WEBHOOK_PORT

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║          TJR Enhanced — MNQ Auto Trader                     ║
║          Webhook server starting on port {WEBHOOK_PORT}            ║
║                                                              ║
║  Endpoints:                                                  ║
║    POST /webhook        → receive TradingView alert          ║
║    GET  /status         → current account stats              ║
║    POST /emergency_stop → close everything NOW               ║
║    GET  /health         → ping                               ║
╚══════════════════════════════════════════════════════════════╝
""")
    uvicorn.run(app, host="0.0.0.0", port=WEBHOOK_PORT, log_level="info")
