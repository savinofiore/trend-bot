"""Walk-forward validation gate.

Splits history into rolling in-sample/out-of-sample windows and checks that the
out-of-sample performance clears minimum bars. The gate has NOT been run on real
data yet — do not tune parameters against it (see PRD §9).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trendbot.backtest.engine import run_backtest
from trendbot.config import StrategyConfig


@dataclass(frozen=True)
class GateResult:
    passed: bool
    oos_sharpe: float
    oos_return: float
    reason: str


def walk_forward(
    closes: pd.DataFrame,
    config: StrategyConfig,
    train_frac: float = 0.6,
    min_sharpe: float = 0.3,
) -> GateResult:
    if len(closes) < 100:
        return GateResult(False, 0.0, 0.0, "insufficient history")
    split = int(len(closes) * train_frac)
    oos = run_backtest(closes.iloc[split:], config)
    passed = oos.sharpe >= min_sharpe and oos.total_return > 0
    reason = "ok" if passed else f"oos sharpe {oos.sharpe:.2f} < {min_sharpe} or negative return"
    return GateResult(passed, oos.sharpe, oos.total_return, reason)
