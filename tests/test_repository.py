"""Repository tests. Verify idempotent upserts and JSON-safe serialization."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from trendbot.config import StrategyConfig
from trendbot.core.signal import Signal
from trendbot.execution.models import EquitySnapshot, OrderRecord, Position
from trendbot.storage.repository import TrendbotRepository, _jsonable


class _Table:
    def __init__(self):
        self.ops: list = []
        self.result: list = []

    def upsert(self, row, on_conflict=None):
        self.ops.append(("upsert", row, on_conflict))
        return self

    def insert(self, row):
        self.ops.append(("insert", row, None))
        return self

    def select(self, cols):
        return self

    def eq(self, col, val):
        return self

    def order(self, col, desc=False):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return SimpleNamespace(data=self.result)


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, _Table] = {}

    def schema(self, name):
        return self

    def table(self, name):
        return self.tables.setdefault(name, _Table())


def _repo():
    client = FakeSupabase()
    return TrendbotRepository("url", "key", client=client), client


def test_jsonable_coerces_decimal_and_datetime():
    out = _jsonable({"qty": Decimal("1.5"), "at": datetime(2026, 7, 19, tzinfo=UTC),
                     "nested": [Decimal("2")]})
    assert out["qty"] == "1.5"
    assert out["at"].startswith("2026-07-19")
    assert out["nested"] == ["2"]


def test_ensure_config_upserts_on_hash():
    repo, client = _repo()
    repo.ensure_config(StrategyConfig(), git_commit="abc123")
    op, row, on_conflict = client.tables["config"].ops[0]
    assert op == "upsert"
    assert on_conflict == "config_hash"


def test_save_signal_upserts_on_composite_key():
    repo, client = _repo()
    sig = Signal("BTCUSDT", datetime(2026, 7, 19, tzinfo=UTC), 0.5, 0.2)
    repo.save_signal(sig, "hash1")
    _, row, on_conflict = client.tables["signals"].ops[0]
    assert on_conflict == "bar_close_at,symbol,config_hash"
    assert isinstance(row["bar_close_at"], str)


def test_record_order_serializes_decimal_as_string():
    repo, client = _repo()
    order = OrderRecord("lnk", "BTCUSDT", "Buy", Decimal("0.001"), Decimal("100"),
                        "submitted", "hash1")
    repo.record_order(order)
    _, row, on_conflict = client.tables["orders"].ops[0]
    assert on_conflict == "order_link_id"
    assert row["qty"] == "0.001"
    assert row["price"] == "100"


def test_order_exists_reflects_backing_rows():
    repo, client = _repo()
    client.table("orders").result = [{"order_link_id": "lnk"}]
    assert repo.order_exists("lnk") is True
    client.table("orders").result = []
    assert repo.order_exists("missing") is False


def test_target_weights_for_maps_symbol_to_weight():
    repo, client = _repo()
    client.table("signals").result = [{"symbol": "BTCUSDT", "target_weight": 0.7}]
    assert repo.target_weights_for(date(2026, 7, 19)) == {"BTCUSDT": 0.7}


def test_upsert_equity_serializes_positions():
    repo, client = _repo()
    snap = EquitySnapshot(datetime(2026, 7, 19, tzinfo=UTC), Decimal("1000"),
                          {"BTCUSDT": Decimal("1.5")})
    repo.upsert_equity(snap)
    _, row, _oc = client.tables["equity"].ops[0]
    assert row["total_equity"] == "1000"
    assert row["positions"]["BTCUSDT"] == "1.5"


def test_snapshot_positions_writes_rows():
    repo, client = _repo()
    repo.snapshot_positions({"BTCUSDT": Position("BTCUSDT", Decimal("2"))})
    op, row, on_conflict = client.tables["positions"].ops[0]
    assert on_conflict == "symbol"
