"""Telegram transport used by the scheduler (cards + admin alerts).

Small and dependency-light (httpx already available). Cards go to the
public channel, operational alerts to a private admin chat. Everything is
injective so the scheduler can be tested without credentials.
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Protocol

import httpx

logger = logging.getLogger("notify")

API_BASE = "https://api.telegram.org/bot{token}"


# ── protocols ──────────────────────────────────────────────────────────────


class Publisher(Protocol):
    """Posts a rendered card to the public channel."""

    def send_photo(self, photo_path: str, caption: str = "") -> None: ...


class Notifier(Protocol):
    """Sends a text alert to a private admin chat."""

    def alert(self, text: str) -> None: ...


# ── real implementation ────────────────────────────────────────────────────


class TelegramPublisher:
    """sendPhoto to the channel, sendMessage to the admin chat."""

    def __init__(self, bot_token: str, channel_id: str, admin_chat_id: str) -> None:
        self._token = bot_token
        self._channel_id = channel_id
        self._admin_chat_id = admin_chat_id
        base = API_BASE.format(token=bot_token)
        self._photo_url = f"{base}/sendPhoto"
        self._text_url = f"{base}/sendMessage"

    def send_photo(self, photo_path: str, caption: str = "") -> None:
        path = pathlib.Path(photo_path)
        if not path.exists():
            raise FileNotFoundError(f"image not found: {photo_path}")
        with path.open("rb") as fh:
            with httpx.Client(timeout=30) as client:
                r = client.post(
                    self._photo_url,
                    data={"chat_id": self._channel_id, "caption": caption},
                    files={"photo": (path.name, fh, "image/png")},
                )
                r.raise_for_status()
        logger.info("photo sent to %s (%s)", self._channel_id, path.name)

    def alert(self, text: str) -> None:
        with httpx.Client(timeout=15) as client:
            r = client.post(
                self._text_url,
                data={"chat_id": self._admin_chat_id, "text": text},
            )
            r.raise_for_status()
        logger.info("alert sent to %s", self._admin_chat_id)


class LogPublisher:
    """Fallback when Telegram is not configured: log loudly instead of fail."""

    def __init__(self, admin_chat_id: str | None = None) -> None:
        self._admin_chat_id = admin_chat_id

    def send_photo(self, photo_path: str, caption: str = "") -> None:
        logger.info("PUBLISH(card) %s | %s", photo_path, caption.replace("\n", " / "))

    def alert(self, text: str) -> None:
        logger.error("ALERT(admin) %s", text)


def build_publisher() -> Publisher:
    """Real Telegram publisher when env vars are set, else a console fallback."""
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    channel = os.getenv("TG_CHANNEL_ID", "").strip()
    admin = os.getenv("TG_ADMIN_CHAT_ID", "").strip()
    if token and channel and admin:
        return TelegramPublisher(token, channel, admin)
    return LogPublisher(admin or None)