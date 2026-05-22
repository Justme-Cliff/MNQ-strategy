"""
Tradovate REST API client.

Demo URL:  https://demo.tradovateapi.com/v1
Live URL:  https://live.tradovateapi.com/v1

Auth: POST /auth/accesstokenrequest
      body: {name, password, appId, appVersion, cid, sec, deviceId}

To get API credentials:
  1. Go to trader.tradovate.com
  2. Sign in with your Tradeify credentials
  3. Account Settings → API Access → Create App
  4. Copy CID and SEC into .env
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from config import (
    TRADOVATE_BASE_URL,
    TRADOVATE_USERNAME,
    TRADOVATE_PASSWORD,
    TRADOVATE_APP_ID,
    TRADOVATE_APP_VERSION,
    TRADOVATE_CID,
    TRADOVATE_SECRET,
    TRADOVATE_DEMO,
)

log = logging.getLogger(__name__)


class TradovateClient:
    def __init__(self):
        self._token: str | None = None
        self._token_expiry: datetime | None = None
        self._account_id: int | None = None
        self._account_spec: str | None = None
        self._client = httpx.AsyncClient(base_url=TRADOVATE_BASE_URL, timeout=10.0)

    # ── Auth ────────────────────────────────────────────────────────────────────

    async def authenticate(self) -> bool:
        payload = {
            "name": TRADOVATE_USERNAME,
            "password": TRADOVATE_PASSWORD,
            "appId": TRADOVATE_APP_ID,
            "appVersion": TRADOVATE_APP_VERSION,
            "cid": TRADOVATE_CID,
            "sec": TRADOVATE_SECRET,
            "deviceId": "tjr-bot-v1",
        }
        resp = await self._client.post("/auth/accesstokenrequest", json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "accessToken" not in data:
            log.error("Auth failed: %s", data)
            return False

        self._token = data["accessToken"]
        expiry_str = data.get("expirationTime", "")
        if expiry_str:
            try:
                self._token_expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            except ValueError:
                self._token_expiry = None

        log.info("Tradovate auth OK (demo=%s)", TRADOVATE_DEMO)
        await self._load_account()
        return True

    async def _ensure_auth(self) -> None:
        if self._token is None:
            await self.authenticate()
        elif self._token_expiry and datetime.now(timezone.utc) > self._token_expiry:
            await self.authenticate()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def _get(self, path: str) -> Any:
        await self._ensure_auth()
        r = await self._client.get(path, headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: dict) -> Any:
        await self._ensure_auth()
        r = await self._client.post(path, json=body, headers=self._headers())
        r.raise_for_status()
        return r.json()

    # ── Account ─────────────────────────────────────────────────────────────────

    async def _load_account(self) -> None:
        accounts = await self._get("/account/list")
        if accounts:
            self._account_id = accounts[0]["id"]
            self._account_spec = accounts[0]["name"]
            log.info("Account: %s (id=%s)", self._account_spec, self._account_id)

    async def get_cash_balance(self) -> float:
        data = await self._get(f"/cashBalance/getCashBalanceSnapshot?accountId={self._account_id}")
        return float(data.get("totalCashValue", 0))

    async def get_positions(self) -> list[dict]:
        return await self._get(f"/position/list?accountId={self._account_id}")

    async def get_open_orders(self) -> list[dict]:
        return await self._get(f"/order/list?accountId={self._account_id}")

    # ── Orders ──────────────────────────────────────────────────────────────────

    async def place_bracket_order(
        self,
        symbol: str,
        direction: str,
        entry: float,
        stop: float,
        tp2: float,
        contracts: int,
        order_type: str = "Limit",
    ) -> dict:
        """
        Place entry + stop + tp bracket (entry fills → OCO activates).
        Tradovate's bracket fields: bracket1 = stop, bracket2 = take profit.
        """
        action = "Buy" if direction == "long" else "Sell"
        close_action = "Sell" if direction == "long" else "Buy"

        body = {
            "accountSpec": self._account_spec,
            "accountId": self._account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": contracts,
            "orderType": order_type,
            "price": entry,
            "isAutomated": True,
            "bracket1": {
                "action": close_action,
                "orderType": "Stop",
                "stopPrice": stop,
                "orderQty": contracts,
            },
            "bracket2": {
                "action": close_action,
                "orderType": "Limit",
                "price": tp2,
                "orderQty": contracts,
            },
        }

        resp = await self._post("/order/placeorder", body)
        log.info("Bracket order placed: %s", resp)
        return resp

    async def modify_order(self, order_id: int, new_stop: float) -> dict:
        """Move stop loss (used to bring to break-even after TP1)."""
        body = {"orderId": order_id, "orderQty": None, "orderType": "Stop", "stopPrice": new_stop}
        return await self._post("/order/modifyorder", body)

    async def cancel_order(self, order_id: int) -> dict:
        return await self._post("/order/cancelorder", {"orderId": order_id})

    async def cancel_all_orders(self) -> None:
        orders = await self.get_open_orders()
        for order in orders:
            try:
                await self.cancel_order(order["id"])
            except Exception as e:
                log.error("Failed to cancel order %s: %s", order["id"], e)
        log.warning("All open orders cancelled")

    async def close_all_positions(self) -> None:
        """Emergency: liquidate all open positions at market."""
        positions = await self.get_positions()
        for pos in positions:
            if pos.get("netPos", 0) == 0:
                continue
            qty = abs(pos["netPos"])
            action = "Sell" if pos["netPos"] > 0 else "Buy"
            body = {
                "accountSpec": self._account_spec,
                "accountId": self._account_id,
                "action": action,
                "symbol": pos["contractId"],
                "orderQty": qty,
                "orderType": "Market",
                "isAutomated": True,
            }
            try:
                await self._post("/order/placeorder", body)
                log.warning("Emergency close sent for %s", pos["contractId"])
            except Exception as e:
                log.error("Emergency close failed: %s", e)

    async def close(self) -> None:
        await self._client.aclose()
