"""Guard tests. Every ambiguity must resolve to TradingHalted."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trendbot.config import RiskLimits
from trendbot.execution.guards import (
    ObservedState,
    TradingHalted,
    assert_can_trade,
    assert_no_withdrawal,
    check_kill_switch,
    check_notional_cap,
    check_staleness,
    run_preflight,
)
from trendbot.execution.models import ApiKeyInfo, Position

_OK_KEY = ApiKeyInfo(can_withdraw=False, can_trade=True)


def test_withdrawal_permission_halts():
    with pytest.raises(TradingHalted):
        assert_no_withdrawal(ApiKeyInfo(can_withdraw=True, can_trade=True))


def test_missing_api_info_halts():
    with pytest.raises(TradingHalted):
        assert_no_withdrawal(None)


def test_no_trade_permission_halts():
    with pytest.raises(TradingHalted):
        assert_can_trade(ApiKeyInfo(can_withdraw=False, can_trade=False))


def test_stale_signal_halts():
    now = datetime.now(UTC)
    with pytest.raises(TradingHalted):
        check_staleness(now - timedelta(days=5), now, RiskLimits().max_signal_age_sec)


def test_future_signal_halts():
    now = datetime.now(UTC)
    with pytest.raises(TradingHalted):
        check_staleness(now + timedelta(hours=1), now, RiskLimits().max_signal_age_sec)


def test_kill_switch_sentinel_halts(tmp_path):
    sentinel = tmp_path / "trendbot.halt"
    sentinel.write_text("manual stop")
    with pytest.raises(TradingHalted):
        check_kill_switch(str(sentinel))


def test_notional_cap_halts():
    limits = RiskLimits(max_position_notional=1000.0)
    positions = {"BTCUSDT": Position("BTCUSDT", Decimal("100"), Decimal("50"))}
    with pytest.raises(TradingHalted):
        check_notional_cap(positions, limits)


def test_run_preflight_passes_when_clear():
    state = ObservedState(now=datetime.now(UTC), api_key_info=_OK_KEY, positions={}, halt_file=None)
    run_preflight(state, datetime.now(UTC), RiskLimits())  # must not raise
