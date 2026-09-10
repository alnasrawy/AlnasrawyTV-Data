"""Telegram publishing via `python-telegram-bot` (step 5).

Public helpers:

- :func:`publish_photo(image_path, caption, chat_id)` — send one card with
  bounded retries on flaky network / Telegram rate limits.
- :func:`send_message(chat_id, text)` — admin alerts (same retry rules).

``chat_id`` is always an explicit parameter, so sending to more channels
later means calling ``publish_photo`` with another id — no code changes.
A configured batch helper (:func:`publish_photo_to_channels`) iterates the
chat ids from :mod:`config`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable

import telegram
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut

from config import config

logger = logging.getLogger("telegram_publisher")

# Lazy per-process Bot (one shared HTTP session).
_bot: telegram.Bot | None = None

_RETRYABLE = (RetryAfter, TimedOut, NetworkError)


def _get_bot() -> telegram.Bot:
    global _bot
    if _bot is None:
        if not config.bot_token:
            raise RuntimeError("TG_BOT_TOKEN is not set (add it to .env)")
        _bot = telegram.Bot(token=config.bot_token)
    return _bot


def _run(coro):
    """Run one async telegram call from our synchronous scheduler."""
    try:
        return asyncio.run(coro)
    except RuntimeError:  # an event loop is already running in this thread
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


def _dispatch(fn: Callable[[], None], *, max_retries: int = 4) -> None:
    """Retry a single telegram operation with backoff; hard-fail after N tries."""
    delay = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            fn()
            return
        except RetryAfter as exc:
            wait = float(getattr(exc, "retry_after", delay)) + 1.0
            logger.warning("rate limited, sleeping %.0fs (attempt %d)", wait, attempt)
            time.sleep(wait)
            delay = wait
        except _RETRYABLE as exc:
            logger.warning("transient failure (%s), retrying in %.0fs", exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
        except TelegramError as exc:
            logger.error("non-retryable telegram error: %s", exc)
            raise
    raise RuntimeError(f"telegram publish failed after {max_retries} attempts")


def publish_photo(
    image_path: str,
    caption: str,
    chat_id: str,
    *,
    bot: telegram.Bot | None = None,
    max_retries: int = 4,
) -> None:
    """Send one image card to a chat with simple retry-on-failure."""
    bot = bot or _get_bot()

    def send_once() -> None:
        with open(image_path, "rb") as fh:
            _run(bot.send_photo(chat_id=chat_id, photo=fh, caption=caption))

    _dispatch(send_once, max_retries=max_retries)
    logger.info("published photo -> %s (%s)", chat_id, Path(image_path).name)


def send_message(
    chat_id: str,
    text: str,
    *,
    bot: telegram.Bot | None = None,
    max_retries: int = 4,
) -> None:
    """Send a plain text message (admin alerts) with the same retry policy."""
    bot = bot or _get_bot()

    def send_once() -> None:
        _run(bot.send_message(chat_id=chat_id, text=text))

    _dispatch(send_once, max_retries=max_retries)
    logger.info("sent message -> %s", chat_id)


def publish_photo_to_channels(
    image_path: str,
    caption: str,
    *,
    chat_ids: tuple[str, ...] | None = None,
    bot: telegram.Bot | None = None,
) -> list[str]:
    """Send a card to every configured channel — add channels in config only."""
    targets = chat_ids if chat_ids is not None else config.chat_ids
    if not targets:
        raise RuntimeError("no chat_ids configured (TG_CHANNELS)")
    sent: list[str] = []
    for chat_id in targets:
        publish_photo(image_path, caption, chat_id=chat_id, bot=bot)
        sent.append(chat_id)
    return sent


def alert_admin(text: str) -> None:
    """Alert the private admin chat; a no-op when it is not configured."""
    if config.admin_chat_id:
        send_message(config.admin_chat_id, text)