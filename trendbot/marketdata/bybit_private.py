"""Authenticated Bybit v5 client. Thin wrapper: HMAC signing, retry, typing.

No business logic. No withdrawal / transfer / subaccount methods exist here —
by design (BP-6): the capability is simply absent, not merely unused. Quantities
and prices are ``Decimal`` and serialized with ``format(x, 'f')`` so a small qty
never leaves as scientific notation (BP-5).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any

import requests

from trendbot.execution.models import (
    ApiKeyInfo,
    CoinBalance,
    InstrumentRules,
    OpenOrder,
    OrderAck,
    OrderRequest,
    Position,
    WalletBalance,
)
from trendbot.marketdata.bybit_client import MAINNET, TESTNET, BybitError

_RECV_WINDOW = "5000"


def _fmt(value: Decimal) -> str:
    """Fixed-point string. Never scientific notation, never float()."""
    return format(value, "f")


class BybitPrivateClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True) -> None:
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self.base_url = TESTNET if testnet else MAINNET
        self.timeout = 10.0
        self._session = requests.Session()
        self._time_offset_ms = 0

    # -- signing / transport -------------------------------------------------
    def _sign(self, timestamp: str, payload: str) -> str:
        origin = f"{timestamp}{self._api_key}{_RECV_WINDOW}{payload}"
        return hmac.new(self._api_secret, origin.encode(), hashlib.sha256).hexdigest()

    def _headers(self, payload: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000) + self._time_offset_ms)
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
            "X-BAPI-SIGN": self._sign(timestamp, payload),
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, params: dict[str, Any]) -> dict:
        payload = self._encode(method, params)
        for attempt in range(4):
            resp = self._send(method, path, params, payload)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()  # any other 4xx: no retry
            body = resp.json()
            code = body.get("retCode", 0)
            if code == 10002 and attempt == 0:  # timestamp out of window: resync once
                self._resync_time()
                continue
            if code != 0:
                raise BybitError(code, body.get("retMsg", ""))
            return body["result"]
        raise BybitError(-1, f"exhausted retries on {method} {path}")

    @staticmethod
    def _encode(method: str, params: dict[str, Any]) -> str:
        if method == "GET":
            return "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return json.dumps(params, separators=(",", ":")) if params else ""

    def _send(self, method, path, params, payload):
        url = f"{self.base_url}{path}"
        headers = self._headers(payload)
        if method == "GET":
            return self._session.get(url, params=params, headers=headers, timeout=self.timeout)
        return self._session.post(url, data=payload, headers=headers, timeout=self.timeout)

    def _resync_time(self) -> None:
        result = self._session.get(f"{self.base_url}/v5/market/time", timeout=self.timeout).json()
        server_ms = int(result["result"]["timeNano"]) // 1_000_000
        self._time_offset_ms = server_ms - int(time.time() * 1000)

    # -- read endpoints ------------------------------------------------------
    def fetch_api_key_info(self) -> ApiKeyInfo:
        r = self._request("GET", "/v5/user/query-api", {})
        perms = r.get("permissions", {})
        withdraw = bool(perms.get("Withdraw")) or bool(r.get("withdraw"))
        trade = any(perms.get(k) for k in ("Spot", "SpotTrade", "ContractTrade"))
        return ApiKeyInfo(
            can_withdraw=withdraw,
            can_trade=trade,
            ip_whitelist=tuple(r.get("ips") or []),
            expires_at=None,
        )

    def fetch_wallet_balance(self, account_type: str = "UNIFIED") -> WalletBalance:
        r = self._request("GET", "/v5/account/wallet-balance", {"accountType": account_type})
        acct = (r.get("list") or [{}])[0]
        coins = tuple(
            CoinBalance(
                coin=c["coin"],
                equity=Decimal(str(c.get("equity") or "0")),
                available=Decimal(str(c.get("availableToWithdraw") or c.get("free") or "0")),
            )
            for c in acct.get("coin", [])
        )
        return WalletBalance(Decimal(str(acct.get("totalEquity") or "0")), coins)

    def fetch_positions(self, category: str = "spot") -> dict[str, Position]:
        r = self._request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        acct = (r.get("list") or [{}])[0]
        out: dict[str, Position] = {}
        for c in acct.get("coin", []):
            qty = Decimal(str(c.get("walletBalance") or "0"))
            if qty != 0 and c["coin"] not in ("USDT", "USDC", "USD"):
                out[f"{c['coin']}USDT"] = Position(f"{c['coin']}USDT", qty)
        return out

    def fetch_open_orders(self, category: str = "spot") -> list[OpenOrder]:
        r = self._request("GET", "/v5/order/realtime", {"category": category})
        return [
            OpenOrder(
                order_link_id=o.get("orderLinkId", ""),
                symbol=o["symbol"],
                side=o["side"],
                qty=Decimal(str(o.get("qty") or "0")),
                price=Decimal(str(o["price"])) if o.get("price") else None,
                status=o.get("orderStatus", ""),
            )
            for o in r.get("list", [])
        ]

    def fetch_instrument_rules(self, symbol: str) -> InstrumentRules:
        r = self._request(
            "GET", "/v5/market/instruments-info", {"category": "spot", "symbol": symbol}
        )
        info = r["list"][0]
        lot = info["lotSizeFilter"]
        price_f = info["priceFilter"]
        return InstrumentRules(
            symbol=symbol,
            tick_size=Decimal(str(price_f["tickSize"])),
            qty_step=Decimal(str(lot["basePrecision"])),
            min_order_qty=Decimal(str(lot["minOrderQty"])),
            min_order_amt=Decimal(str(lot.get("minOrderAmt") or "0")),
        )

    # -- write endpoints (order lifecycle only) ------------------------------
    def submit_order(self, request: OrderRequest) -> OrderAck:
        params: dict[str, Any] = {
            "category": "spot",
            "symbol": request.symbol,
            "side": request.side,
            "orderType": request.order_type,
            "qty": _fmt(request.qty),
            "orderLinkId": request.order_link_id,
            "timeInForce": request.time_in_force,
        }
        if request.price is not None:
            params["price"] = _fmt(request.price)
        r = self._request("POST", "/v5/order/create", params)
        return OrderAck(order_id=r.get("orderId", ""), order_link_id=r.get("orderLinkId", ""))

    def cancel_order(self, symbol: str, order_link_id: str) -> None:
        self._request(
            "POST",
            "/v5/order/cancel",
            {"category": "spot", "symbol": symbol, "orderLinkId": order_link_id},
        )
