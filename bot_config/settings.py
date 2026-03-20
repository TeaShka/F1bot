"""
Bot configuration loaded from environment variables and `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class Config:
    bot_token: str
    db_path: str
    default_timezone: str
    force_ipv4: bool
    bot_proxy: str | None


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN is not set in .env")

    return Config(
        bot_token=token,
        db_path=os.getenv("DB_PATH", "f1_bot.db"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC"),
        force_ipv4=_as_bool(os.getenv("FORCE_IPV4"), default=False),
        bot_proxy=os.getenv("BOT_PROXY") or None,
    )
