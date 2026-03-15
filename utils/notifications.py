"""
Сервис напоминаний.
Запускается как фоновая задача asyncio и рассылает уведомления
пользователям за 1 час до старта квалификации и гонки.

Архитектура:
  - Каждую минуту планировщик проверяет расписание.
  - Если до квалификации или гонки осталось ровно 60 ± 1 минута,
    рассылаем уведомления всем подписчикам.
  - Чтобы избежать дублей, храним «отправленные» события в памяти
    (в продакшне лучше использовать отдельную таблицу БД).
"""

import asyncio
import logging
from datetime import timedelta, timezone

from aiogram import Bot

from bot_config.schedule import SCHEDULE_2026, SESSION_NAMES
from database import Database
from utils.time_utils import now_utc, format_dt

logger = logging.getLogger(__name__)

# Порог: уведомляем, если до сессии осталось от 59 до 61 минуты
NOTIFY_WINDOW_MIN = 59
NOTIFY_WINDOW_MAX = 61

# Хранилище уже отправленных уведомлений: ключ = (round, session_key)
_sent_notifications: set[tuple[int, str]] = set()


async def notification_scheduler(bot: Bot, db: Database) -> None:
    """
    Бесконечный цикл планировщика уведомлений.
    Проверяет расписание каждые 60 секунд.
    """
    logger.info("Планировщик уведомлений запущен")
    while True:
        try:
            await _check_and_notify(bot, db)
        except Exception as exc:
            logger.exception("Ошибка в планировщике уведомлений: %s", exc)
        await asyncio.sleep(60)


async def _check_and_notify(bot: Bot, db: Database) -> None:
    """Проверяет ближайшие сессии и рассылает уведомления."""
    now = now_utc()

    for race in SCHEDULE_2026:
        for session_key in ("qualifying", "race"):
            dt = race["sessions"].get(session_key)
            if dt is None:
                continue

            session_utc = dt.replace(tzinfo=timezone.utc)
            delta_minutes = (session_utc - now).total_seconds() / 60

            # Проверяем попадание в окно уведомлений
            if not (NOTIFY_WINDOW_MIN <= delta_minutes <= NOTIFY_WINDOW_MAX):
                continue

            event_key = (race["round"], session_key)
            if event_key in _sent_notifications:
                continue  # уже отправляли

            _sent_notifications.add(event_key)
            await _broadcast(bot, db, race, session_key, dt)


async def _broadcast(
    bot: Bot,
    db: Database,
    race: dict,
    session_key: str,
    session_dt,
) -> None:
    """Рассылает уведомление всем подписчикам."""
    kind = "qual" if session_key == "qualifying" else "race"
    subscribers = db.get_subscribers(kind)

    if not subscribers:
        return

    session_label = SESSION_NAMES[session_key]
    logger.info(
        "Рассылаем уведомление: %s, %s — %d подписчиков",
        race["name"], session_label, len(subscribers)
    )

    for sub in subscribers:
        user_id = sub["user_id"]
        tz = sub["timezone"]
        time_str = format_dt(session_dt, tz)

        text = (
            f"⏰ <b>Через 1 час</b> — {race['name']}\n"
            f"{session_label} · {time_str}"
        )
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Не удалось отправить уведомление пользователю %d: %s",
                           user_id, exc)