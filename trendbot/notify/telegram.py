"""Telegram notifications. Never include secrets in message bodies."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self.enabled = enabled and bool(bot_token) and bool(chat_id)

    def send(self, message: str) -> None:
        """Best-effort send. A notification failure must never break the loop."""
        if not self.enabled:
            log.info("telegram disabled; message dropped: %s", message)
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": message},
                timeout=10,
            )
        except requests.RequestException as exc:  # pragma: no cover - network
            log.warning("telegram send failed: %s", exc)

    def alert(self, severity: str, message: str) -> None:
        self.send(f"[{severity.upper()}] {message}")
