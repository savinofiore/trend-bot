"""Safety guards. Any ambiguity about state resolves to ``TradingHalted``.

These are the last line of defence and are deliberately blunt: they raise, they
never "try anyway", and they never assume a safe-looking default. The kill
switch is a sentinel file so a logical halt survives a container restart (a
``restart: always`` policy must not be able to revive a halted bot).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trendbot.config import RiskLimits
from trendbot.execution.models import ApiKeyInfo, Position


class TradingHalted(Exception):
    """Raised when the bot must stop operating. Terminal for the loop."""


@dataclass(frozen=True)
class ObservedState:
    """Everything a preflight needs, captured once, so checks are pure."""

    now: datetime
    api_key_info: ApiKeyInfo | None
    positions: dict[str, Position] = field(default_factory=dict)
    halt_file: str | None = None


def assert_no_withdrawal(info: ApiKeyInfo | None) -> None:
    """A key that can withdraw is categorically unsafe — never operate with it."""
    if info is None:
        raise TradingHalted("api key info unavailable; cannot verify permissions")
    if info.can_withdraw:
        raise TradingHalted("api key has withdrawal permission; refusing to trade")


def assert_can_trade(info: ApiKeyInfo | None) -> None:
    if info is None or not info.can_trade:
        raise TradingHalted("api key lacks trade permission")


# Small grace for benign clock skew between the local clock and the bar close.
_FUTURE_GRACE_SEC = 5.0


def check_staleness(signal_ts: datetime | None, now: datetime, max_age_sec: int) -> None:
    if signal_ts is None:
        raise TradingHalted("no signal timestamp; state is ambiguous")
    age = (now - signal_ts).total_seconds()
    if age < -_FUTURE_GRACE_SEC:
        raise TradingHalted(f"signal timestamp is in the future by {-age:.0f}s")
    if age > max_age_sec:
        raise TradingHalted(f"signal is stale: {age:.0f}s > {max_age_sec}s")


def check_notional_cap(positions: dict[str, Position], limits: RiskLimits) -> None:
    cap = Decimal(str(limits.max_position_notional))
    for pos in positions.values():
        notional = abs(pos.qty) * pos.avg_price
        if notional > cap:
            raise TradingHalted(
                f"{pos.symbol} notional {notional} exceeds cap {cap}"
            )


def halt_active(halt_file: str | None) -> bool:
    return bool(halt_file) and Path(halt_file).exists()


def write_halt_sentinel(halt_file: str | None, reason: str) -> None:
    """Persist a sticky halt. Best-effort: never mask the original failure."""
    if not halt_file:
        return
    path = Path(halt_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(reason)
    except OSError:
        pass


def check_kill_switch(halt_file: str | None) -> None:
    if halt_active(halt_file):
        reason = Path(halt_file).read_text().strip() if halt_file else ""
        raise TradingHalted(f"kill switch active: {reason}")


def run_preflight(state: ObservedState, signal_ts: datetime | None, limits: RiskLimits) -> None:
    """Run every guard. Returns ``None`` if clear, raises ``TradingHalted`` otherwise."""
    check_kill_switch(state.halt_file)
    assert_no_withdrawal(state.api_key_info)
    assert_can_trade(state.api_key_info)
    check_staleness(signal_ts, state.now, limits.max_signal_age_sec)
    check_notional_cap(state.positions, limits)
