"""Pure trend-following signal, shared by backtest and live.

Contract: the weight for the bar closing at ``T`` depends only on data up to and
including ``T``. No look-ahead. ``test_no_lookahead`` pins this — do not change
this module without running it.

Long-only, no leverage: every per-symbol weight lands in [0, 1] and represents
the fraction of that symbol's *allocated* equity to hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from trendbot.config import StrategyParams

_ANNUALISER = 365.0**0.5


@dataclass(frozen=True)
class Signal:
    """One symbol's target for one bar."""

    symbol: str
    bar_close_at: datetime
    target_weight: float
    realized_vol: float


def compute_weights(closes: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Map a frame of close prices (index=timestamps, columns=symbols) to weights.

    Every operation is backward-looking, so row ``T`` uses only rows ``<= T``.
    """
    fast = closes.rolling(params.fast_window, min_periods=params.fast_window).mean()
    slow = closes.rolling(params.slow_window, min_periods=params.slow_window).mean()
    trend = (fast > slow).astype(float)

    rets = closes.pct_change()
    realized_vol = rets.rolling(params.vol_window, min_periods=params.vol_window).std()
    realized_vol = realized_vol * _ANNUALISER

    scale = (params.target_vol / realized_vol).clip(upper=1.0)
    weights = (trend * scale).clip(lower=0.0, upper=1.0)
    return weights.fillna(0.0)


def realized_vol(closes: pd.Series, params: StrategyParams) -> pd.Series:
    """Annualised realized volatility series (backward-looking)."""
    rets = closes.pct_change()
    return rets.rolling(params.vol_window, min_periods=params.vol_window).std() * _ANNUALISER


def latest_signals(closes: pd.DataFrame, params: StrategyParams) -> list[Signal]:
    """Build `Signal` objects for the most recent bar in ``closes``."""
    if closes.empty:
        return []
    weights = compute_weights(closes, params)
    vols = pd.DataFrame({c: realized_vol(closes[c], params) for c in closes.columns})
    bar = closes.index[-1]
    ts = bar.to_pydatetime() if hasattr(bar, "to_pydatetime") else bar
    out: list[Signal] = []
    for symbol in closes.columns:
        w = float(weights[symbol].iloc[-1])
        v = float(vols[symbol].iloc[-1]) if not pd.isna(vols[symbol].iloc[-1]) else 0.0
        out.append(Signal(symbol=symbol, bar_close_at=ts, target_weight=w, realized_vol=v))
    return out
