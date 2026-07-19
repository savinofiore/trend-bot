"""Compose concrete dependencies from the environment.

Kept apart from both the CLI and the engine so the loop stays pure and testable
(the engine depends only on injected collaborators, never on env/globals).
"""

from __future__ import annotations

import os
from decimal import Decimal

from trendbot.config import RuntimeSettings, StrategyConfig
from trendbot.core.signal import latest_signals
from trendbot.execution.engine import EngineDeps
from trendbot.execution.executor import SignalBundle
from trendbot.marketdata.bybit_client import BybitPublicClient
from trendbot.marketdata.bybit_private import BybitPrivateClient
from trendbot.marketdata.ingestor import CandleStore, ingest
from trendbot.notify.telegram import TelegramNotifier
from trendbot.storage.repository import TrendbotRepository


class MarketSignalSource:
    """Ingest candles, compute the latest signal, expose it as a `SignalBundle`."""

    def __init__(self, config: StrategyConfig, public: BybitPublicClient, store: CandleStore):
        self._config = config
        self._public = public
        self._store = store

    def latest(self) -> SignalBundle:
        for symbol in self._config.universe:
            ingest(self._store, self._public, symbol)
        closes = self._store.closes(list(self._config.universe))
        signals = latest_signals(closes, self._config.params)
        marks = {s: Decimal(str(closes[s].iloc[-1])) for s in closes.columns}
        bar_close = signals[0].bar_close_at if signals else None
        return SignalBundle(signals=signals, mark_prices=marks, bar_close=bar_close)


def build_deps(settings: RuntimeSettings, config: StrategyConfig | None = None) -> EngineDeps:
    config = config or StrategyConfig()
    private = BybitPrivateClient(
        api_key=os.environ.get("BYBIT_API_KEY", ""),
        api_secret=os.environ.get("BYBIT_API_SECRET", ""),
        testnet=settings.testnet,
    )
    public = BybitPublicClient(testnet=settings.testnet)
    repo = TrendbotRepository(
        url=os.environ.get("SUPABASE_URL", ""),
        service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    )
    notifier = TelegramNotifier(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
    )
    store = CandleStore(os.environ.get("TRENDBOT_DATA_DIR", "data/candles"))
    return EngineDeps(
        config=config,
        settings=settings,
        client=private,
        repo=repo,
        notifier=notifier,
        signal_source=MarketSignalSource(config, public, store),
        git_commit=os.environ.get("GIT_COMMIT"),
    )
