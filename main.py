"""
main.py — точка входа в бота.

Запуск:
    python main.py

Перед запуском:
    1. Создайте файл .env на основе .env.example
    2. Установите зависимости: pip install -r requirements.txt
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from bot_config import load_config
from database import Database
from handlers import root_router
from utils.notifications import notification_scheduler


# ── Настройка логирования ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ── Middleware для внедрения зависимостей ──────────────────────────────────────

class DatabaseMiddleware:
    """
    Middleware, который добавляет экземпляр Database в данные обработчика.
    Благодаря этому каждый хэндлер получает `db` как аргумент без
    дополнительной глобальной переменной.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(self, handler, event, data: dict):
        data["db"] = self.db
        return await handler(event, data)


# ── Главная асинхронная функция ────────────────────────────────────────────────

async def main() -> None:
    config = load_config()
    logger.info("Конфигурация загружена. DB: %s", config.db_path)

    # Инициализируем базу данных
    db = Database(config.db_path)

    # Создаём бота с HTML-парсингом по умолчанию
    bot = Bot(
        token= "8251494421:AAEonMZMFUOKyIiahRDgS7ij2bjquzw0dS0",
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # FSM-хранилище в оперативной памяти
    # В продакшне стоит заменить на RedisStorage
    storage = MemoryStorage()

    # Dispatcher — центр маршрутизации
    dp = Dispatcher(storage=storage)

    # Подключаем middleware к обоим типам апдейтов
    dp.message.middleware(DatabaseMiddleware(db))
    dp.callback_query.middleware(DatabaseMiddleware(db))

    # Регистрируем все роутеры
    dp.include_router(root_router)

    # Запускаем планировщик уведомлений как фоновую задачу
    asyncio.create_task(notification_scheduler(bot, db))
    logger.info("Планировщик уведомлений зарегистрирован как фоновая задача")

    # Удаляем возможный «застрявший» webhook и запускаем long-polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен, слушаем обновления...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
