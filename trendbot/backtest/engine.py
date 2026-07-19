"""Vectorised daily-rebalance backtest with a simple cost model.

Uses the same pure signal as live (`core.signal.compute_weights`) so there is a
single source of truth for target weights.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trendbot.config import StrategyConfig
from trendbot.core.signal import compute_weights


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.Series
    returns: pd.Series
    total_return: float
    sharpe: float
    max_drawdown: float


def _sharpe(returns: pd.Series) -> float:
    if returns.std() == 0 or returns.empty:
        return 0.0
    return float(returns.mean() / returns.std() * (365**0.5))


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())


def run_backtest(closes: pd.DataFrame, config: StrategyConfig) -> BacktestResult:
    weights = compute_weights(closes, config.params) / max(len(closes.columns), 1)
    asset_rets = closes.pct_change().fillna(0.0)

    gross = (weights.shift(1) * asset_rets).sum(axis=1)
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    cost_rate = config.costs.taker_fee + config.costs.slippage_bps / 10_000
    net = gross - turnover * cost_rate

    equity = (1.0 + net).cumprod()
    return BacktestResult(
        equity_curve=equity,
        returns=net,
        total_return=float(equity.iloc[-1] - 1.0) if not equity.empty else 0.0,
        sharpe=_sharpe(net),
        max_drawdown=_max_drawdown(equity) if not equity.empty else 0.0,
    )
