"""Execution engine — the loop.

State machine: STARTUP → RECONCILE → IDLE ⇄ (PREFLIGHT → EXECUTE) → IDLE, with
HALTED as a terminal sink. A logical HALT is sticky (sentinel file, EE-6) so a
container ``restart: always`` cannot revive it. Transient errors alert and
continue; only a ``TradingHalted`` is terminal (§1.3).
"""

from __future__ import annotations

import logging
import signal as os_signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from trendbot.config import RuntimeSettings, StrategyConfig
from trendbot.execution import guards
from trendbot.execution.executor import SignalBundle, execute_signals
from trendbot.execution.guards import ObservedState, TradingHalted
from trendbot.execution.models import ApiKeyInfo, EquitySnapshot, InstrumentRules, Position
from trendbot.execution.reconciler import reconcile

log = logging.getLogger(__name__)

HALT_EXIT_CODE = 42  # dedicated code so an orchestrator can distinguish a logical halt


@dataclass
class EngineDeps:
    config: StrategyConfig
    settings: RuntimeSettings
    client: object  # BybitPrivateClient-shaped
    repo: object  # TrendbotRepository-shaped
    notifier: object  # TelegramNotifier-shaped
    signal_source: object  # .latest() -> SignalBundle
    git_commit: str | None = None


class ExecutionEngine:
    def __init__(self, deps: EngineDeps) -> None:
        self.d = deps
        self._shutdown = False
        self._api_info: ApiKeyInfo | None = None
        self._positions: dict[str, Position] = {}
        self._rules: dict[str, InstrumentRules] = {}

    # -- lifecycle -----------------------------------------------------------
    def install_signal_handlers(self) -> None:
        os_signal.signal(os_signal.SIGTERM, lambda *_: self.request_shutdown())
        os_signal.signal(os_signal.SIGINT, lambda *_: self.request_shutdown())

    def request_shutdown(self) -> None:
        log.warning("shutdown requested; finishing current work")
        self._shutdown = True

    def run(self, once: bool = False) -> int:
        if self.d.settings.is_live:
            log.warning("LIVE TRADING ATTIVO — testnet=false dry_run=false")
        try:
            self._startup()
            while not self._shutdown:
                self._cycle()
                if once:
                    break
                if not self._shutdown:
                    time.sleep(self.d.settings.idle_poll_sec)
        except TradingHalted as exc:
            return self._halt(str(exc))
        self._final_snapshot()
        return 0

    # -- states --------------------------------------------------------------
    def _startup(self) -> None:
        guards.check_kill_switch(self.d.settings.halt_file)  # sticky halt survives restart
        self._api_info = self.d.client.fetch_api_key_info()
        guards.assert_no_withdrawal(self._api_info)
        guards.assert_can_trade(self._api_info)
        self._safe(self.d.repo.ensure_config, self.d.config, self.d.git_commit)
        self._reconcile()

    def _cycle(self) -> None:
        self._reconcile()
        bundle: SignalBundle = self.d.signal_source.latest()
        for sig in bundle.signals:
            self._safe(self.d.repo.save_signal, sig, self.d.config.config_hash)
        self._preflight(bundle)
        equity = Decimal(str(self.d.client.fetch_wallet_balance().total_equity))
        execute_signals(self.d, bundle, self._positions, equity, self._rules_of, self._safe)
        self._safe(self.d.repo.log_decision, "cycle_complete",
                   {"bar_close": bundle.bar_close, "symbols": len(bundle.signals)})

    def _reconcile(self) -> None:
        exchange = self.d.client.fetch_positions()
        for div in reconcile(exchange, self._positions):
            self._safe(self.d.notifier.alert, "warning", f"position divergence {div}")
            self._safe(self.d.repo.log_decision, "divergence", {"detail": str(div)}, div.symbol)
        self._positions = exchange  # exchange is the source of truth: it wins
        self._safe(self.d.repo.snapshot_positions, exchange)

    def _preflight(self, bundle: SignalBundle) -> None:
        state = ObservedState(
            now=datetime.now(UTC),
            api_key_info=self._api_info,
            positions=self._positions,
            halt_file=self.d.settings.halt_file,
        )
        guards.run_preflight(state, bundle.bar_close, self.d.config.risk)

    def _halt(self, reason: str) -> int:
        log.critical("HALTED: %s", reason)
        guards.write_halt_sentinel(self.d.settings.halt_file, reason)
        self._safe(self.d.notifier.alert, "critical", f"HALTED: {reason}")
        self._safe(self.d.repo.raise_alert, "critical", f"HALTED: {reason}")
        self._final_snapshot()
        return HALT_EXIT_CODE

    def _final_snapshot(self) -> None:
        try:
            positions = self.d.client.fetch_positions()
            equity = Decimal(str(self.d.client.fetch_wallet_balance().total_equity))
        except Exception as exc:  # noqa: BLE001 - snapshot is best-effort
            log.warning("final snapshot skipped: %s", exc)
            return
        self._safe(self.d.repo.snapshot_positions, positions)
        self._safe(self.d.repo.upsert_equity, EquitySnapshot(
            at=datetime.now(UTC), total_equity=equity,
            positions={s: p.qty for s, p in positions.items()},
        ))

    # -- helpers -------------------------------------------------------------
    def _rules_of(self, symbol: str) -> InstrumentRules:
        if symbol not in self._rules:
            self._rules[symbol] = self.d.client.fetch_instrument_rules(symbol)
        return self._rules[symbol]

    def _safe(self, fn, *args) -> None:
        """Run a side-effecting call; a failure alerts but never halts trading (ST-3)."""
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            log.warning("non-fatal call %s failed: %s", getattr(fn, "__name__", fn), exc)
