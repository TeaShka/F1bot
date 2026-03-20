"""
Entry point for the Telegram bot.
"""

import asyncio
import logging
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot_config import load_config
from database import Database, SQLiteStorage
from handlers import root_router
from utils.api_client import ApiClient
from utils.notifications import notification_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class DatabaseMiddleware:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(self, handler, event, data: dict):
        data["db"] = self.db
        return await handler(event, data)


class ApiMiddleware:
    def __init__(self, api: ApiClient) -> None:
        self.api = api

    async def __call__(self, handler, event, data: dict):
        data["api"] = self.api
        return await handler(event, data)


class LastSeenMiddleware:
    def __init__(self, db: Database, *, min_interval_seconds: int = 300) -> None:
        self.db = db
        self.min_interval_seconds = min_interval_seconds
        self._recent_updates: dict[int, float] = {}

    async def __call__(self, handler, event, data: dict):
        user = getattr(event, "from_user", None)
        if user:
            now = time.monotonic()
            last_update = self._recent_updates.get(user.id)
            if last_update is None or now - last_update >= self.min_interval_seconds:
                self.db.update_last_seen(user.id)
                self._recent_updates[user.id] = now
        return await handler(event, data)


async def main() -> None:
    config = load_config()
    logger.info("Configuration loaded. DB: %s", config.db_path)

    db = Database(config.db_path)
    api = ApiClient()
    await api.open()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = SQLiteStorage(config.db_path)
    dp = Dispatcher(storage=storage)

    db_middleware = DatabaseMiddleware(db)
    api_middleware = ApiMiddleware(api)
    last_seen_middleware = LastSeenMiddleware(db)

    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)
    dp.message.middleware(api_middleware)
    dp.callback_query.middleware(api_middleware)
    dp.message.middleware(last_seen_middleware)
    dp.callback_query.middleware(last_seen_middleware)

    dp.include_router(root_router)

    notification_task = asyncio.create_task(notification_scheduler(bot, db, api))
    logger.info("Notification scheduler started")

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot started, polling updates")

    try:
        await dp.start_polling(bot)
    finally:
        notification_task.cancel()
        await asyncio.gather(notification_task, return_exceptions=True)
        await api.close()
        await storage.close()
        db.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
