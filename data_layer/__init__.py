"""Data layer for the AlnasrawyTV football project.

Fetches and parses matches from Yalla Shoot (ysscores.com) into clean
dataclass models. No visuals, no Telegram — consumed by later stages.
"""

from data_layer.config import (
    TZ,
    BASE_URL,
    USER_AGENT,
)

__all__ = ["TZ", "BASE_URL", "USER_AGENT"]