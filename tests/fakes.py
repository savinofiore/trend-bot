"""In-memory fakes for engine tests. No network, ever."""

from __future__ import annotations

from decimal import Decimal

from trendbot.execution.models import (
    ApiKeyInfo,
    InstrumentRules,
    OrderAck,
    Position,
    WalletBalance,
)

_RULES = InstrumentRules("BTCUSDT", Decimal("0.01"), Decimal("0.0001"),
                         Decimal("0.0001"), Decimal("1"))


class FakeClient:
    def __init__(self, can_withdraw=False, can_trade=True, equity="1000",
                 positions=None, rules_raise_for=None):
        self.api_info = ApiKeyInfo(can_withdraw=can_withdraw, can_trade=can_trade)
        self.equity = Decimal(equity)
        self.positions = positions or {}
        self.submitted: list = []
        self.rules_raise_for = rules_raise_for or set()
        self._wallet_calls = 0

    def fetch_api_key_info(self):
        return self.api_info

    def fetch_positions(self, category="spot"):
        return dict(self.positions)

    def fetch_wallet_balance(self, account_type="UNIFIED"):
        self._wallet_calls += 1
        return WalletBalance(total_equity=self.equity)

    def fetch_instrument_rules(self, symbol):
        if symbol in self.rules_raise_for:
            raise RuntimeError(f"boom for {symbol}")
        return InstrumentRules(symbol, Decimal("0.01"), Decimal("0.0001"),
                               Decimal("0.0001"), Decimal("1"))

    def submit_order(self, request):
        self.submitted.append(request)
        return OrderAck(order_id=f"ex-{len(self.submitted)}", order_link_id=request.order_link_id)


class FakeRepo:
    def __init__(self, raise_all=False):
        self.raise_all = raise_all
        self.orders: set[str] = set()
        self.decisions: list = []
        self.snapshots: list = []
        self.equity_snaps: list = []
        self.alerts: list = []

    def _maybe_raise(self):
        if self.raise_all:
            raise RuntimeError("supabase down")

    def ensure_config(self, config, git_commit):
        self._maybe_raise()

    def save_signal(self, signal, config_hash):
        self._maybe_raise()

    def record_order(self, order):
        self._maybe_raise()
        self.orders.add(order.order_link_id)

    def order_exists(self, order_link_id):
        self._maybe_raise()
        return order_link_id in self.orders

    def snapshot_positions(self, positions):
        self._maybe_raise()
        self.snapshots.append(positions)

    def upsert_equity(self, snapshot):
        self._maybe_raise()
        self.equity_snaps.append(snapshot)

    def log_decision(self, decision_type, observed_state, symbol=None, outcome=None):
        self._maybe_raise()
        self.decisions.append((decision_type, symbol, outcome))

    def raise_alert(self, severity, message):
        self._maybe_raise()
        self.alerts.append((severity, message))


class FakeNotifier:
    def __init__(self):
        self.alerts: list = []
        self.messages: list = []

    def send(self, message):
        self.messages.append(message)

    def alert(self, severity, message):
        self.alerts.append((severity, message))


class FakeSignalSource:
    """Returns a bundle whose bar_close advances each call (new bar per cycle)."""

    def __init__(self, bundles, on_latest=None):
        self._bundles = list(bundles)
        self._i = 0
        self.on_latest = on_latest
        self.calls = 0

    def latest(self):
        self.calls += 1
        if self.on_latest:
            self.on_latest()
        bundle = self._bundles[min(self._i, len(self._bundles) - 1)]
        self._i += 1
        return bundle


def default_position(symbol="BTCUSDT", qty="0"):
    return Position(symbol, Decimal(qty))
