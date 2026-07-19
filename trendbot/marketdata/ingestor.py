"""Candle persistence to parquet + gap detection.

Local historical store used to build the price frame the signal consumes. The
exchange remains the source of truth for *positions*; this is only price data.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trendbot.marketdata.bybit_client import BybitPublicClient

_DAY_MS = 86_400_000


class CandleStore:
    """One parquet file per symbol under ``root``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.root / f"{symbol}.parquet"

    def load(self, symbol: str) -> pd.DataFrame:
        path = self._path(symbol)
        if not path.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return pd.read_parquet(path)

    def save(self, symbol: str, df: pd.DataFrame) -> None:
        df.sort_index().to_parquet(self._path(symbol))

    def closes(self, symbols: list[str]) -> pd.DataFrame:
        series = {s: self.load(s)["close"] for s in symbols if not self.load(s).empty}
        return pd.DataFrame(series).sort_index()


def detect_gaps(df: pd.DataFrame, bar_ms: int = _DAY_MS) -> list[tuple[int, int]]:
    """Return (prev_ms, next_ms) pairs where more than one bar is missing."""
    if len(df) < 2:
        return []
    idx = df.index.astype("int64") // 1_000_000
    gaps: list[tuple[int, int]] = []
    for prev, nxt in zip(idx[:-1], idx[1:], strict=False):
        if nxt - prev > bar_ms:
            gaps.append((int(prev), int(nxt)))
    return gaps


def ingest(store: CandleStore, client: BybitPublicClient, symbol: str, limit: int = 200) -> int:
    """Fetch recent candles and merge into the store. Returns rows written."""
    candles = client.fetch_kline(symbol, limit=limit)
    if not candles:
        return 0
    rows = {
        pd.Timestamp(c.start_ms, unit="ms", tz="UTC"): {
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    }
    fresh = pd.DataFrame.from_dict(rows, orient="index")
    merged = pd.concat([store.load(symbol), fresh])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    store.save(symbol, merged)
    return len(fresh)
