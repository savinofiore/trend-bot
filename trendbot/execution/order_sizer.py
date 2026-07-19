"""Translate a target weight into an executable order. Pure, no I/O.

Every rounding is ROUND_DOWN so we never ask for more base than the balance
covers (OS-1). Sub-minimum and within-band results are *no-trades*, not errors
(OS-2, OS-3). The resulting position notional can never exceed the allocated
equity, so no path produces implicit leverage (OS-4).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from trendbot.execution.models import InstrumentRules, Position


@dataclass(frozen=True)
class SizingDecision:
    symbol: str
    side: Literal["Buy", "Sell"] | None
    qty: Decimal
    reason: str  # human-readable, lands in the decision_log


def _round_down_to_step(qty: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return qty
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def _no_trade(symbol: str, reason: str) -> SizingDecision:
    assert reason, "no-trade decisions must carry a reason (OS-5)"
    return SizingDecision(symbol=symbol, side=None, qty=Decimal("0"), reason=reason)


def compute_order(
    target_weight: float,
    current_position: Position | None,
    allocated_equity: Decimal,
    mark_price: Decimal,
    rules: InstrumentRules,
    rebalance_band: float = 0.0,
) -> SizingDecision:
    """Compute the order (delta) that moves the position toward the target weight."""
    if mark_price <= 0 or allocated_equity <= 0:
        return _no_trade(rules.symbol, "prezzo o equity non validi: nessuna operazione")

    # Clamp to [0, 1]: long-only, no leverage. Guarantees notional <= equity (OS-4).
    weight = min(max(target_weight, 0.0), 1.0)
    target_notional = Decimal(str(weight)) * allocated_equity
    target_qty = _round_down_to_step(target_notional / mark_price, rules.qty_step)

    current_qty = current_position.qty if current_position else Decimal("0")
    delta = target_qty - current_qty
    if delta == 0:
        return _no_trade(rules.symbol, "nessun ribilanciamento necessario")

    order_qty = _round_down_to_step(abs(delta), rules.qty_step)
    delta_notional = order_qty * mark_price

    band = Decimal(str(rebalance_band)) * allocated_equity
    if delta_notional < band:
        return _no_trade(rules.symbol, "entro la banda di non-negoziazione")

    if order_qty < rules.min_order_qty or delta_notional < rules.min_order_amt:
        return _no_trade(rules.symbol, "sotto la soglia minima dello strumento")

    side: Literal["Buy", "Sell"] = "Buy" if delta > 0 else "Sell"
    reason = f"ribilanciamento {side}: target_qty={target_qty} current_qty={current_qty}"
    return SizingDecision(symbol=rules.symbol, side=side, qty=order_qty, reason=reason)
