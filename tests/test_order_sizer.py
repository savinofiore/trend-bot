"""Order sizer tests, including the OS-* requirements and the T-3 property."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from trendbot.execution.models import InstrumentRules, Position
from trendbot.execution.order_sizer import compute_order

RULES = InstrumentRules(
    symbol="BTCUSDT",
    tick_size=Decimal("0.01"),
    qty_step=Decimal("0.001"),
    min_order_qty=Decimal("0.001"),
    min_order_amt=Decimal("5"),
)


def test_qty_rounds_down_to_step():
    # 1000 * 1.0 / 333 = 3.003003...; step 0.001 → floor to 3.003, never 3.004.
    d = compute_order(1.0, None, Decimal("1000"), Decimal("333"), RULES)
    assert d.side == "Buy"
    assert d.qty == Decimal("3.003")
    assert d.qty * Decimal("333") <= Decimal("1000")


def test_below_min_order_amt_is_no_trade():
    # target notional 3 USDT < min_order_amt 5 → no-trade, not an error.
    d = compute_order(0.003, None, Decimal("1000"), Decimal("100"), RULES)
    assert d.side is None
    assert d.qty == Decimal("0")
    assert "soglia minima" in d.reason


def test_below_min_order_qty_is_no_trade():
    rules = InstrumentRules("BTCUSDT", Decimal("0.01"), Decimal("0.001"),
                            Decimal("1"), Decimal("0"))
    d = compute_order(0.0005, None, Decimal("1000"), Decimal("100"), rules)
    assert d.side is None
    assert d.reason


def test_within_band_is_no_trade():
    pos = Position("BTCUSDT", Decimal("9.9"))
    d = compute_order(1.0, pos, Decimal("1000"), Decimal("100"), RULES, rebalance_band=0.05)
    assert d.side is None
    assert "banda" in d.reason


def test_sell_side_when_over_target():
    pos = Position("BTCUSDT", Decimal("8"))
    d = compute_order(0.5, pos, Decimal("1000"), Decimal("100"), RULES)
    assert d.side == "Sell"
    assert d.qty == Decimal("3")  # target 5, current 8 → sell 3


def test_zero_delta_is_no_trade():
    pos = Position("BTCUSDT", Decimal("5"))
    d = compute_order(0.5, pos, Decimal("1000"), Decimal("100"), RULES)
    assert d.side is None
    assert d.reason


def test_every_no_trade_has_reason():
    for weight in (0.0, 0.0001, 0.5, 1.0):
        d = compute_order(weight, None, Decimal("1"), Decimal("100000"), RULES)
        if d.side is None:
            assert d.reason


@settings(max_examples=300)
@given(
    weight=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    equity=st.integers(min_value=1, max_value=10_000_000),
    price=st.integers(min_value=1, max_value=1_000_000),
    step_exp=st.integers(min_value=0, max_value=6),
)
def test_notional_never_exceeds_equity(weight, equity, price, step_exp):
    """T-3: from flat, a Buy's resulting notional never exceeds allocated equity."""
    rules = InstrumentRules(
        symbol="BTCUSDT",
        tick_size=Decimal("0.01"),
        qty_step=Decimal(1).scaleb(-step_exp),
        min_order_qty=Decimal("0"),
        min_order_amt=Decimal("0"),
    )
    allocated = Decimal(equity)
    d = compute_order(weight, None, allocated, Decimal(price), rules)
    if d.side == "Buy":
        assert d.qty * Decimal(price) <= allocated
