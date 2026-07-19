"""Signal tests. `test_no_lookahead` is load-bearing — never weaken it."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trendbot.config import StrategyParams
from trendbot.core.signal import Signal, compute_weights, latest_signals, realized_vol

PARAMS = StrategyParams(fast_window=10, slow_window=30, vol_window=20)


def _frame(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    btc = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    eth = 50 * np.exp(np.cumsum(rng.normal(0.0008, 0.025, n)))
    return pd.DataFrame({"BTCUSDT": btc, "ETHUSDT": eth}, index=idx)


def test_weights_have_same_shape_as_input():
    closes = _frame()
    assert compute_weights(closes, PARAMS).shape == closes.shape


def test_weights_are_bounded_zero_to_one():
    w = compute_weights(_frame(seed=1), PARAMS)
    assert (w >= 0).all().all()
    assert (w <= 1).all().all()


def test_warmup_period_is_flat():
    w = compute_weights(_frame(seed=2), PARAMS)
    # First valid slow MA lands at index slow_window-1, so bars before it are flat.
    assert (w.iloc[: PARAMS.slow_window - 1] == 0).all().all()


def test_strict_uptrend_goes_long():
    idx = pd.date_range("2023-01-01", periods=200, freq="D", tz="UTC")
    up = pd.DataFrame({"BTCUSDT": np.linspace(100, 400, 200)}, index=idx)
    assert compute_weights(up, PARAMS)["BTCUSDT"].iloc[-1] > 0


def test_strict_downtrend_is_flat():
    idx = pd.date_range("2023-01-01", periods=200, freq="D", tz="UTC")
    down = pd.DataFrame({"BTCUSDT": np.linspace(400, 100, 200)}, index=idx)
    assert compute_weights(down, PARAMS)["BTCUSDT"].iloc[-1] == 0


def test_no_lookahead():
    """Weight at bar T must not change when future bars are appended."""
    closes = _frame(seed=3)
    full = compute_weights(closes, PARAMS)
    for t in (60, 120, 200, 299):
        truncated = compute_weights(closes.iloc[: t + 1], PARAMS)
        for sym in closes.columns:
            assert truncated[sym].iloc[-1] == pytest.approx(full[sym].iloc[t])


def test_realized_vol_is_backward_looking():
    closes = _frame(seed=4)["BTCUSDT"]
    full = realized_vol(closes, PARAMS)
    truncated = realized_vol(closes.iloc[:150], PARAMS)
    assert truncated.iloc[-1] == pytest.approx(full.iloc[149])


def test_latest_signals_one_per_symbol():
    signals = latest_signals(_frame(seed=5), PARAMS)
    assert len(signals) == 2
    assert all(isinstance(s, Signal) for s in signals)
    assert {s.symbol for s in signals} == {"BTCUSDT", "ETHUSDT"}
