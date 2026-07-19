"""Engine tests — T-4 through T-10."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from tests.fakes import FakeClient, FakeNotifier, FakeRepo, FakeSignalSource, default_position
from trendbot.config import RiskLimits, RuntimeSettings, StrategyConfig, StrategyParams
from trendbot.core.signal import Signal
from trendbot.execution.engine import HALT_EXIT_CODE, EngineDeps, ExecutionEngine
from trendbot.execution.executor import SignalBundle

# Staleness is exercised in test_guards; here we widen it so dated test bars pass preflight.
_RISK = RiskLimits(max_signal_age_sec=10**9)
SINGLE = StrategyConfig(universe=("BTCUSDT",), params=StrategyParams(rebalance_band=0.0),
                        risk=_RISK)


def _bundle(weight=1.0, price="100", bar=None):
    ts = bar or datetime.now(UTC)
    return SignalBundle(
        signals=[Signal("BTCUSDT", ts, weight, 0.2)],
        mark_prices={"BTCUSDT": Decimal(price)},
        bar_close=ts,
    )


def _deps(client, repo, source, dry_run=True, config=SINGLE):
    settings = RuntimeSettings(dry_run=dry_run, testnet=True, idle_poll_sec=0, halt_file=None)
    return EngineDeps(config=config, settings=settings, client=client, repo=repo,
                      notifier=FakeNotifier(), signal_source=source)


def test_dry_run_never_calls_submit_order():
    client = FakeClient()
    client.submit_order = MagicMock()
    engine = ExecutionEngine(_deps(client, FakeRepo(), FakeSignalSource([_bundle()])))
    assert engine.run(once=True) == 0
    client.submit_order.assert_not_called()


def test_duplicate_order_link_id_is_skipped():
    client = FakeClient()
    repo = FakeRepo()
    bar = datetime.now(UTC)
    source = FakeSignalSource([_bundle(bar=bar), _bundle(bar=bar)])  # same bar twice
    engine = ExecutionEngine(_deps(client, repo, source, dry_run=False))
    engine._startup()
    engine._cycle()
    engine._cycle()  # same link id -> second submit skipped
    assert len(client.submitted) == 1


def test_withdrawal_permission_prevents_startup():
    client = FakeClient(can_withdraw=True)
    source = FakeSignalSource([_bundle()])
    engine = ExecutionEngine(_deps(client, FakeRepo(), source))
    assert engine.run(once=True) == HALT_EXIT_CODE
    assert source.calls == 0  # never reached IDLE / signal fetch


def test_partial_fill_recomputes_delta():
    client = FakeClient(equity="1000", positions={})
    repo = FakeRepo()
    day1 = datetime(2026, 7, 18, tzinfo=UTC)
    day2 = datetime(2026, 7, 19, tzinfo=UTC)
    source = FakeSignalSource([_bundle(bar=day1), _bundle(bar=day2)])
    engine = ExecutionEngine(_deps(client, repo, source, dry_run=False))
    engine._startup()
    engine._cycle()  # flat -> buy 10 (1000/100)
    assert client.submitted[-1].qty == Decimal("10")
    client.positions = {"BTCUSDT": default_position("BTCUSDT", "4")}  # partial fill
    engine._cycle()  # residual only: target 10, held 4 -> buy 6
    assert client.submitted[-1].qty == Decimal("6")


def test_supabase_failure_does_not_halt_trading():
    client = FakeClient()
    repo = FakeRepo(raise_all=True)  # every DB call raises
    engine = ExecutionEngine(_deps(client, repo, FakeSignalSource([_bundle()])))
    assert engine.run(once=True) == 0  # cycle completes despite DB being down


def test_symbol_exception_does_not_kill_loop():
    config = StrategyConfig(universe=("BTCUSDT", "ETHUSDT"),
                            params=StrategyParams(rebalance_band=0.0), risk=_RISK)
    client = FakeClient(rules_raise_for={"ETHUSDT"})
    repo = FakeRepo()
    notifier = FakeNotifier()
    ts = datetime.now(UTC)
    bundle = SignalBundle(
        signals=[Signal("BTCUSDT", ts, 1.0, 0.2), Signal("ETHUSDT", ts, 1.0, 0.2)],
        mark_prices={"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("50")},
        bar_close=ts,
    )
    deps = EngineDeps(config=config, settings=RuntimeSettings(dry_run=False, testnet=True,
                      idle_poll_sec=0, halt_file=None), client=client, repo=repo,
                      notifier=notifier, signal_source=FakeSignalSource([bundle]))
    engine = ExecutionEngine(deps)
    engine._startup()
    engine._cycle()
    assert any(s.symbol == "BTCUSDT" for s in client.submitted)  # BTC still traded
    assert any("ETHUSDT" in msg for _, msg in notifier.alerts)  # ETH failure alerted


def test_sigterm_triggers_clean_shutdown():
    client = FakeClient()
    repo = FakeRepo()
    source = FakeSignalSource([_bundle()])
    engine = ExecutionEngine(_deps(client, repo, source))
    source.on_latest = engine.request_shutdown  # SIGTERM arrives during the cycle
    code = engine.run(once=False)
    assert code == 0
    assert repo.equity_snaps, "final equity snapshot must be written"


def test_live_flag_requires_both_switches_off():
    live = RuntimeSettings(dry_run=False, testnet=False)
    safe = RuntimeSettings(dry_run=False, testnet=True)
    assert live.is_live is True
    assert safe.is_live is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
