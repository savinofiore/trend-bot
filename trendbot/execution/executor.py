"""Per-symbol execution: sizing → idempotency → submit (or dry-run record).

Isolated from the loop so a single symbol blowing up cannot take down the whole
cycle (EE-8): each symbol runs in its own try/except and failures are alerted,
not propagated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trendbot.core.signal import Signal
from trendbot.execution.models import InstrumentRules, OrderRecord, OrderRequest, Position
from trendbot.execution.order_sizer import SizingDecision, compute_order
from trendbot.execution.reconciler import make_order_link_id

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalBundle:
    signals: list[Signal]
    mark_prices: dict[str, Decimal]
    bar_close: datetime


def _make_record(deps, decision: SizingDecision, link_id: str, bundle: SignalBundle,
                 mark: Decimal, status: str, is_dry_run: bool, exch_id: str | None) -> OrderRecord:
    return OrderRecord(
        order_link_id=link_id,
        symbol=decision.symbol,
        side=str(decision.side),
        qty=decision.qty,
        price=mark,
        status=status,
        config_hash=deps.config.config_hash,
        bar_close_at=bundle.bar_close,
        is_dry_run=is_dry_run,
        exchange_order_id=exch_id,
    )


def _execute_symbol(deps, signal: Signal, bundle: SignalBundle, positions: dict[str, Position],
                    rules: InstrumentRules, allocated: Decimal, safe) -> None:
    mark = bundle.mark_prices[signal.symbol]
    decision = compute_order(
        target_weight=signal.target_weight,
        current_position=positions.get(signal.symbol),
        allocated_equity=allocated,
        mark_price=mark,
        rules=rules,
        rebalance_band=deps.config.params.rebalance_band,
    )
    if decision.side is None:
        safe(deps.repo.log_decision, "no_trade", {"symbol": signal.symbol}, signal.symbol,
             decision.reason)
        return

    link_id = make_order_link_id(deps.config.config_hash, signal.symbol, bundle.bar_close)
    if _already_sent(deps, link_id, safe):
        log.info("order %s already exists; skipping", link_id)
        return

    if deps.settings.dry_run:
        record = _make_record(deps, decision, link_id, bundle, mark, "dry_run", True, None)
        safe(deps.repo.record_order, record)
        safe(deps.repo.log_decision, "dry_run_order", {"link_id": link_id, "qty": decision.qty},
             signal.symbol, decision.reason)
        return

    ack = deps.client.submit_order(OrderRequest(
        symbol=signal.symbol, side=decision.side, qty=decision.qty,
        order_link_id=link_id, order_type="Limit", price=mark, time_in_force="PostOnly",
    ))
    record = _make_record(deps, decision, link_id, bundle, mark, "submitted", False, ack.order_id)
    safe(deps.repo.record_order, record)
    safe(deps.repo.log_decision, "submit_order", {"link_id": link_id}, signal.symbol,
         decision.reason)


def _already_sent(deps, link_id: str, safe) -> bool:
    try:
        return deps.repo.order_exists(link_id)
    except Exception:  # noqa: BLE001 - DB is observability; exchange rejects dup ids too
        safe(deps.notifier.alert, "warning", f"order_exists check failed for {link_id}")
        return False


def execute_signals(deps, bundle: SignalBundle, positions: dict[str, Position],
                    total_equity: Decimal, rules_of, safe) -> None:
    allocated = total_equity / Decimal(len(deps.config.universe))
    for signal in bundle.signals:
        try:
            rules = rules_of(signal.symbol)
            _execute_symbol(deps, signal, bundle, positions, rules, allocated, safe)
        except Exception as exc:  # noqa: BLE001 - EE-8: isolate per symbol
            log.exception("symbol %s failed", signal.symbol)
            safe(deps.notifier.alert, "error", f"{signal.symbol} execution failed: {exc}")
            safe(deps.repo.log_decision, "symbol_error", {"error": str(exc)}, signal.symbol,
                 "isolated")
