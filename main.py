"""
Entry point for the Telegram bot.
"""

import asyncio
import logging
import socket
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
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
STARTUP_API_TIMEOUT_SECONDS = 20


def _build_bot_session(force_ipv4: bool, proxy: str | None) -> AiohttpSession:
    session = AiohttpSession(proxy=proxy)
    if force_ipv4:
        connector_init = getattr(session, "_connector_init", None)
        if not isinstance(connector_init, dict):
            connector_init = {}
            setattr(session, "_connector_init", connector_init)
        connector_init["family"] = socket.AF_INET
        logger.info("FORCE_IPV4 is enabled for Telegram Bot API session")
    if proxy:
        logger.info("BOT_PROXY is enabled for Telegram Bot API session")
    return session


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
    if config.force_ipv4:
        logger.info("FORCE_IPV4 is enabled")
    if config.bot_proxy:
        logger.info("BOT_PROXY is enabled")

    db = Database(config.db_path)
    api = ApiClient(force_ipv4=config.force_ipv4, proxy=config.bot_proxy)
    storage = SQLiteStorage(config.db_path)
    dp = Dispatcher(storage=storage)
    bot: Bot | None = None
    notification_task: asyncio.Task | None = None

    try:
        await api.open()

        try:
            bot_session = _build_bot_session(config.force_ipv4, config.bot_proxy)
        except RuntimeError as exc:
            if config.bot_proxy and "aiohttp-socks" in str(exc):
                raise RuntimeError(
                    "BOT_PROXY requires the 'aiohttp-socks' package. "
                    "Install it with: pip install aiohttp-socks"
                ) from exc
            raise

        bot = Bot(
            token=config.bot_token,
            session=bot_session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

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

        logger.info("Checking Telegram API connectivity")
        try:
            me = await asyncio.wait_for(bot.get_me(), timeout=STARTUP_API_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                "Telegram API did not respond within "
                f"{STARTUP_API_TIMEOUT_SECONDS} seconds. "
                "Check internet access, VPN/proxy, bot token "
                "or set FORCE_IPV4=1 / BOT_PROXY in .env."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Telegram API check failed: {exc}") from exc

        logger.info(
            "Telegram API reachable. Authorized as %s",
            f"@{me.username}" if me.username else me.id,
        )

        logger.info("Deleting webhook before polling")
        try:
            await asyncio.wait_for(
                bot.delete_webhook(drop_pending_updates=True),
                timeout=STARTUP_API_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "delete_webhook timed out after %d seconds, continuing to polling",
                STARTUP_API_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("delete_webhook failed: %s. Continuing to polling.", exc)

        notification_task = asyncio.create_task(notification_scheduler(bot, db, api))
        logger.info("Notification scheduler started")

        logger.info("Bot started, polling updates")

        await dp.start_polling(bot)
    finally:
        if notification_task is not None:
            notification_task.cancel()
            await asyncio.gather(notification_task, return_exceptions=True)
        await api.close()
        await storage.close()
        db.close()
        if bot is not None:
            await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
