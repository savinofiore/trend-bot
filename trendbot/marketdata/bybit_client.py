"""Public Bybit v5 market-data client. No authentication, read-only."""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

MAINNET = "https://api.bybit.com"
TESTNET = "https://api-testnet.bybit.com"


class BybitError(RuntimeError):
    """Non-zero retCode from Bybit. Carries the raw code and message."""

    def __init__(self, ret_code: int, ret_msg: str) -> None:
        super().__init__(f"bybit retCode={ret_code}: {ret_msg}")
        self.ret_code = ret_code
        self.ret_msg = ret_msg


@dataclass(frozen=True)
class Candle:
    start_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BybitPublicClient:
    """Thin wrapper over public endpoints (kline, server time)."""

    def __init__(self, testnet: bool = True, timeout: float = 10.0) -> None:
        self.base_url = TESTNET if testnet else MAINNET
        self.timeout = timeout
        self._session = requests.Session()

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(4):
            resp = self._session.get(
                f"{self.base_url}{path}", params=params, timeout=self.timeout
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            body = resp.json()
            if body.get("retCode", 0) != 0:
                raise BybitError(body.get("retCode", -1), body.get("retMsg", ""))
            return body["result"]
        raise BybitError(-1, f"exhausted retries on GET {path}")

    def fetch_kline(
        self, symbol: str, interval: str = "D", limit: int = 200, category: str = "spot"
    ) -> list[Candle]:
        result = self._get(
            "/v5/market/kline",
            {"category": category, "symbol": symbol, "interval": interval, "limit": limit},
        )
        rows = result.get("list", [])
        candles = [
            Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in rows
        ]
        candles.sort(key=lambda c: c.start_ms)
        return candles

    def server_time_ms(self) -> int:
        result = self._get("/v5/market/time", {})
        return int(result["timeNano"]) // 1_000_000
