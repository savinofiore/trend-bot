"""Reconciliation and idempotency keys.

The exchange is the sole source of truth for positions. Reconciliation reports
where the local view diverges; the caller alerts and adopts the exchange value.
The order-link-id builder is deterministic per (config, symbol, bar) so replaying
a cycle cannot double-submit, while a genuinely new bar produces a fresh id and
naturally picks up any residual delta (partial fills).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from trendbot.execution.models import Position

_LINK_PREFIX = "tb"


@dataclass(frozen=True)
class Divergence:
    symbol: str
    exchange_qty: Decimal
    stored_qty: Decimal

    def __str__(self) -> str:
        return (
            f"{self.symbol}: exchange={self.exchange_qty} stored={self.stored_qty} "
            f"(delta={self.exchange_qty - self.stored_qty})"
        )


def _bar_key(bar_close: datetime | date) -> str:
    if isinstance(bar_close, datetime):
        return bar_close.strftime("%Y%m%d")
    return bar_close.strftime("%Y%m%d")


def make_order_link_id(config_hash: str, symbol: str, bar_close: datetime | date) -> str:
    """Deterministic idempotency key. Same inputs → same id → replay-safe."""
    return f"{_LINK_PREFIX}-{config_hash[:8]}-{symbol}-{_bar_key(bar_close)}"


def reconcile(
    exchange: dict[str, Position],
    stored: dict[str, Position],
    tolerance: Decimal = Decimal("0"),
) -> list[Divergence]:
    """Compare exchange (truth) against the stored view. Returns divergences."""
    symbols = set(exchange) | set(stored)
    divergences: list[Divergence] = []
    for symbol in sorted(symbols):
        ex_qty = exchange[symbol].qty if symbol in exchange else Decimal("0")
        st_qty = stored[symbol].qty if symbol in stored else Decimal("0")
        if abs(ex_qty - st_qty) > tolerance:
            divergences.append(Divergence(symbol, ex_qty, st_qty))
    return divergences
