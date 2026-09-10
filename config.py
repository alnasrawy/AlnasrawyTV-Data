"""Central, environment-driven configuration for the whole pipeline.

Every deploy-specific value comes from the environment (.env / systemd
EnvironmentFile). Nothing secret lives in the repo.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


class Config:
    def __init__(self) -> None:
        # Telegram
        self.bot_token: str = _env("TG_BOT_TOKEN")
        raw_channels = _env("TG_CHANNELS")
        self.chat_ids: tuple[str, ...] = tuple(
            c for c in (x.strip() for x in raw_channels.replace(" ", "").split(","))
            if c
        )
        self.admin_chat_id: str = _env("TG_ADMIN_CHAT_ID")

        # Local paths
        root = Path(__file__).resolve().parent
        self.image_dir: Path = Path(_env("IMAGE_DIR", str(root / "out_imgs")))

    @property
    def telegram_ready(self) -> bool:
        return bool(self.bot_token) and bool(self.chat_ids)


config = Config()