"""Reconciler + idempotency-key tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from trendbot.execution.models import Position
from trendbot.execution.reconciler import make_order_link_id, reconcile


def _pos(symbol: str, qty: str) -> Position:
    return Position(symbol, Decimal(qty))


def test_link_id_is_deterministic():
    a = make_order_link_id("abcdef1234567890", "BTCUSDT", date(2026, 7, 19))
    b = make_order_link_id("abcdef1234567890", "BTCUSDT", date(2026, 7, 19))
    assert a == b


def test_link_id_differs_per_bar():
    a = make_order_link_id("abcdef1234567890", "BTCUSDT", date(2026, 7, 19))
    b = make_order_link_id("abcdef1234567890", "BTCUSDT", date(2026, 7, 20))
    assert a != b


def test_link_id_differs_per_symbol():
    a = make_order_link_id("abcdef1234567890", "BTCUSDT", date(2026, 7, 19))
    b = make_order_link_id("abcdef1234567890", "ETHUSDT", date(2026, 7, 19))
    assert a != b


def test_no_divergence_when_equal():
    ex = {"BTCUSDT": _pos("BTCUSDT", "1.5")}
    assert reconcile(ex, dict(ex)) == []


def test_divergence_on_quantity_mismatch():
    ex = {"BTCUSDT": _pos("BTCUSDT", "1.5")}
    stored = {"BTCUSDT": _pos("BTCUSDT", "1.0")}
    divs = reconcile(ex, stored)
    assert len(divs) == 1
    assert divs[0].symbol == "BTCUSDT"


def test_divergence_when_position_missing_locally():
    ex = {"ETHUSDT": _pos("ETHUSDT", "3.0")}
    divs = reconcile(ex, {})
    assert len(divs) == 1
    assert divs[0].exchange_qty == Decimal("3.0")
    assert divs[0].stored_qty == Decimal("0")


def test_tolerance_suppresses_tiny_divergence():
    ex = {"BTCUSDT": _pos("BTCUSDT", "1.00000001")}
    stored = {"BTCUSDT": _pos("BTCUSDT", "1.0")}
    assert reconcile(ex, stored, tolerance=Decimal("0.0001")) == []
