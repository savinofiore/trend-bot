"""Strategy configuration and runtime settings.

`StrategyConfig` is the deterministic, hashable description of the strategy — it
feeds the ``config_hash`` used everywhere for idempotency. `RuntimeSettings`
holds operational, non-strategy toggles (dry-run, testnet, intervals) parsed
from the environment with *safe* defaults.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class StrategyParams:
    """Trend-following signal parameters."""

    fast_window: int = 20
    slow_window: int = 100
    vol_window: int = 30
    target_vol: float = 0.20
    rebalance_band: float = 0.05


@dataclass(frozen=True)
class CostModel:
    """Execution cost assumptions used by backtest and sizing sanity checks."""

    taker_fee: float = 0.0006
    maker_fee: float = 0.0001
    slippage_bps: float = 5.0


@dataclass(frozen=True)
class RiskLimits:
    """Hard risk limits. These are guards, not tunables."""

    max_weight: float = 1.0
    max_signal_age_sec: int = 90_000  # a daily bar is stale after ~25h
    max_position_notional: float = 1_000_000.0


@dataclass(frozen=True)
class StrategyConfig:
    """Full, hashable strategy description."""

    universe: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    quote_ccy: str = "USDT"
    params: StrategyParams = field(default_factory=StrategyParams)
    costs: CostModel = field(default_factory=CostModel)
    risk: RiskLimits = field(default_factory=RiskLimits)

    def __post_init__(self) -> None:
        # Non-negotiable: no leverage. max_weight > 1.0 is a config error.
        if self.risk.max_weight > 1.0:
            raise ValueError(
                f"max_weight={self.risk.max_weight} > 1.0 implies leverage; forbidden"
            )
        if not self.universe:
            raise ValueError("universe must not be empty")

    @property
    def config_hash(self) -> str:
        """Stable hash over the full config — the idempotency anchor."""
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _env_safe_flag(name: str) -> bool:
    """Return True (the *safe* mode) unless the env var is literally "false".

    Deliberately strict: "true", "1", "", missing → all safe. Only the exact
    (case-insensitive, stripped) string "false" disables the safe mode.
    """
    raw = os.getenv(name)
    if raw is None:
        return True
    return raw.strip().lower() != "false"


@dataclass(frozen=True)
class RuntimeSettings:
    """Operational toggles parsed from the environment with safe defaults."""

    dry_run: bool = True
    testnet: bool = True
    reconcile_interval_sec: int = 300
    post_only_timeout_sec: int = 60
    idle_poll_sec: int = 15
    halt_file: str = "/data/trendbot.halt"

    @property
    def is_live(self) -> bool:
        """Live only when BOTH safety switches are explicitly disabled."""
        return not self.dry_run and not self.testnet

    @classmethod
    def from_env(cls) -> RuntimeSettings:
        return cls(
            dry_run=_env_safe_flag("DRY_RUN"),
            testnet=_env_safe_flag("BYBIT_TESTNET"),
            reconcile_interval_sec=int(os.getenv("RECONCILE_INTERVAL_SEC", "300")),
            post_only_timeout_sec=int(os.getenv("POST_ONLY_TIMEOUT_SEC", "60")),
            idle_poll_sec=int(os.getenv("IDLE_POLL_SEC", "15")),
            halt_file=os.getenv("TRENDBOT_HALT_FILE", "/data/trendbot.halt"),
        )
