"""Acceptance test for telegram_publisher retry/send logic (no real network).

Run:  python telegram_publisher_selftest.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from telegram.error import RetryAfter

import telegram_publisher as tp

C1 = C2 = C3 = C4 = None


class _FakeBot:
    """Async bot that fails the first ``n_fail`` photo sends."""

    def __init__(self, n_fail: int = 1):
        self.n_fail = n_fail
        self.photo_calls = 0
        self.msg_calls = 0
        self.photo_chats: list[str] = []
        self.msg_chats: list[str] = []

    async def send_photo(self, **kwargs):
        self.photo_calls += 1
        chat = kwargs["chat_id"]
        if self.photo_calls <= self.n_fail:
            raise RetryAfter(retry_after=0)
        self.photo_chats.append(chat)
        return None

    async def send_message(self, **kwargs):
        self.msg_calls += 1
        chat = kwargs["chat_id"]
        if self.msg_calls <= self.n_fail:
            raise RetryAfter(retry_after=0)
        self.msg_chats.append(chat)
        return None


def _tmp_image() -> str:
    fd, path = tempfile.mkstemp(suffix=".png")
    Path(path).write_bytes(b"fake-image-bytes")
    return path


def run() -> int:
    results = []

    def check(name: str, cond: bool):
        results.append((name, cond))
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")

    img = _tmp_image()

    print("C1. transient RetryAfter is retried then succeeds")
    bot = _FakeBot(n_fail=2)
    tp.publish_photo(img, "c1", "100", bot=bot, max_retries=4)
    check("2 failures, then success (3 attempts)", bot.photo_calls == 3 and bot.photo_chats == ["100"])

    print("C2. exhausted retries raise RuntimeError")
    bot = _FakeBot(n_fail=5)
    try:
        tp.publish_photo(img, "c2", "100", bot=bot, max_retries=2)
        check("RuntimeError raised after max_retries", False)
    except RuntimeError:
        check("RuntimeError raised after max_retries", True)

    print("C3. multi-channel publish hits every chat id")
    bot = _FakeBot(n_fail=0)
    sent = tp.publish_photo_to_channels(img, "c3", bot=bot, chat_ids=("a", "b", "c"))
    check("all ids reached in order", bot.photo_chats == ["a", "b", "c"] and sent == ["a", "b", "c"])

    print("C4. send_message shares the retry path")
    bot = _FakeBot(n_fail=1)
    tp.send_message("admin", "alert", bot=bot, max_retries=3)
    check("retried then delivered to admin", bot.msg_calls == 2 and bot.msg_chats == ["admin"])

    ok = sum(1 for _, c in results if c)
    total = len(results)
    print(f"RESULT: {ok} passed, {total - ok} failed")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(run())