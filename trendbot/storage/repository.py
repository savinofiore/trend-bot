"""Supabase persistence — the ONLY place SQL/PostgREST is touched.

The database is observability, not authoritative state (ST-3): callers must
treat every method here as best-effort and never let a failure alter a trading
decision. All writes are idempotent upserts on natural keys (ST-2). Money-like
values are serialized as strings, datetimes as ISO-8601 (ST-4).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from trendbot.config import StrategyConfig
from trendbot.core.signal import Signal
from trendbot.execution.models import EquitySnapshot, OrderRecord, Position

_SCHEMA = "trendbot"
_TIMEOUT = 10  # seconds — ST-5, no unbounded call in the loop


def _jsonable(value: Any) -> Any:
    """Recursively coerce to JSON primitives: Decimal→str, datetime→ISO."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class TrendbotRepository:
    def __init__(self, url: str, service_role_key: str, client: Any | None = None) -> None:
        self._client = client if client is not None else _make_client(url, service_role_key)

    def _table(self, name: str):
        return self._client.schema(_SCHEMA).table(name)

    # -- config / signals ----------------------------------------------------
    def ensure_config(self, config: StrategyConfig, git_commit: str | None) -> None:
        self._table("config").upsert(
            {
                "config_hash": config.config_hash,
                "universe": list(config.universe),
                "params": _jsonable(config.params.__dict__),
                "git_commit": git_commit,
            },
            on_conflict="config_hash",
        ).execute()

    def save_signal(self, signal: Signal, config_hash: str) -> None:
        self._table("signals").upsert(
            {
                "bar_close_at": _jsonable(signal.bar_close_at),
                "symbol": signal.symbol,
                "config_hash": config_hash,
                "target_weight": signal.target_weight,
                "realized_vol": signal.realized_vol,
            },
            on_conflict="bar_close_at,symbol,config_hash",
        ).execute()

    def latest_signal_timestamp(self) -> datetime | None:
        res = (
            self._table("signals")
            .select("bar_close_at")
            .order("bar_close_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return datetime.fromisoformat(rows[0]["bar_close_at"]) if rows else None

    def target_weights_for(self, bar_close_at: date) -> dict[str, float]:
        res = (
            self._table("signals")
            .select("symbol,target_weight")
            .eq("bar_close_at", bar_close_at.isoformat())
            .execute()
        )
        return {r["symbol"]: float(r["target_weight"]) for r in (res.data or [])}

    # -- orders --------------------------------------------------------------
    def record_order(self, order: OrderRecord) -> None:
        self._table("orders").upsert(
            {
                "order_link_id": order.order_link_id,
                "symbol": order.symbol,
                "side": order.side,
                "qty": str(order.qty),
                "price": str(order.price) if order.price is not None else None,
                "status": order.status,
                "config_hash": order.config_hash,
                "bar_close_at": _jsonable(order.bar_close_at),
                "is_dry_run": order.is_dry_run,
                "exchange_order_id": order.exchange_order_id,
            },
            on_conflict="order_link_id",
        ).execute()

    def order_exists(self, order_link_id: str) -> bool:
        res = (
            self._table("orders")
            .select("order_link_id")
            .eq("order_link_id", order_link_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    # -- positions / equity / observability ---------------------------------
    def snapshot_positions(self, positions: dict[str, Position]) -> None:
        rows = [
            {"symbol": s, "qty": str(p.qty), "avg_price": str(p.avg_price)}
            for s, p in positions.items()
        ]
        if rows:
            self._table("positions").upsert(rows, on_conflict="symbol").execute()

    def upsert_equity(self, snapshot: EquitySnapshot) -> None:
        self._table("equity").upsert(
            {
                "at": snapshot.at.isoformat(),
                "total_equity": str(snapshot.total_equity),
                "positions": _jsonable(snapshot.positions),
            },
            on_conflict="at",
        ).execute()

    def log_decision(
        self,
        decision_type: str,
        observed_state: dict,
        symbol: str | None = None,
        outcome: str | None = None,
    ) -> None:
        self._table("decision_log").insert(
            {
                "decision_type": decision_type,
                "symbol": symbol,
                "observed_state": _jsonable(observed_state),
                "outcome": outcome,
            }
        ).execute()

    def raise_alert(self, severity: str, message: str) -> None:
        self._table("alerts").insert({"severity": severity, "message": message}).execute()


def _make_client(url: str, service_role_key: str):  # pragma: no cover - network
    from supabase import ClientOptions, create_client

    options = ClientOptions(postgrest_client_timeout=_TIMEOUT, storage_client_timeout=_TIMEOUT)
    return create_client(url, service_role_key, options=options)
