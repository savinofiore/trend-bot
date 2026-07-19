"""Shared execution/exchange domain types.

Kept in one leaf module so ``bybit_private``, ``order_sizer``, ``engine`` and
``repository`` can all import them without creating import cycles. Money-like
fields are ``Decimal`` — never ``float`` — for anything sent to the exchange.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class ApiKeyInfo:
    can_withdraw: bool
    can_trade: bool
    ip_whitelist: tuple[str, ...] = ()
    expires_at: datetime | None = None


@dataclass(frozen=True)
class CoinBalance:
    coin: str
    equity: Decimal
    available: Decimal


@dataclass(frozen=True)
class WalletBalance:
    total_equity: Decimal
    coins: tuple[CoinBalance, ...] = ()

    def available(self, coin: str) -> Decimal:
        for cb in self.coins:
            if cb.coin == coin:
                return cb.available
        return Decimal("0")


@dataclass(frozen=True)
class Position:
    """A spot position. The exchange is the sole source of truth for this."""

    symbol: str
    qty: Decimal
    avg_price: Decimal = Decimal("0")


@dataclass(frozen=True)
class OpenOrder:
    order_link_id: str
    symbol: str
    side: Literal["Buy", "Sell"]
    qty: Decimal
    price: Decimal | None
    status: str


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Literal["Buy", "Sell"]
    qty: Decimal
    order_link_id: str
    order_type: Literal["Limit", "Market"] = "Limit"
    price: Decimal | None = None
    time_in_force: Literal["PostOnly", "GTC", "IOC"] = "PostOnly"


@dataclass(frozen=True)
class OrderAck:
    order_id: str
    order_link_id: str


@dataclass(frozen=True)
class InstrumentRules:
    symbol: str
    tick_size: Decimal
    qty_step: Decimal
    min_order_qty: Decimal
    min_order_amt: Decimal


@dataclass(frozen=True)
class OrderRecord:
    order_link_id: str
    symbol: str
    side: str
    qty: Decimal
    price: Decimal | None
    status: str
    config_hash: str
    bar_close_at: datetime | None = None
    is_dry_run: bool = True
    exchange_order_id: str | None = None


@dataclass(frozen=True)
class EquitySnapshot:
    at: datetime
    total_equity: Decimal
    positions: dict[str, Decimal] = field(default_factory=dict)
