"""
Конфигурация бота.
Все настройки загружаются из переменных окружения через .env файл.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Основной класс конфигурации."""
    bot_token: str
    db_path: str
    default_timezone: str


def load_config() -> Config:
    """Загружает конфигурацию из переменных окружения."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN не задан в .env файле")

    return Config(
        bot_token=token,
        db_path=os.getenv("DB_PATH", "f1_bot.db"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC"),
    )
