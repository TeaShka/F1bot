"""
Сервис напоминаний.
Запускается как фоновая задача asyncio и рассылает уведомления
пользователям за 60 или 15 минут до старта сессии.

Архитектура:
  - Каждую минуту планировщик проверяет расписание.
  - Если до квалификации или гонки осталось время, попадающее в окна 60 или 15 минут,
    рассылаем уведомления нужным подписчикам.
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

# Хранилище уже отправленных уведомлений: ключ = (round, session_key, target_minutes)
_sent_notifications: set[tuple[int, str, int]] = set()


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
            target_minutes = None
            if 59 <= delta_minutes <= 61:
                target_minutes = 60
            elif 14 <= delta_minutes <= 16:
                target_minutes = 15

            if target_minutes is None:
                continue

            event_key = (race["round"], session_key, target_minutes)
            if event_key in _sent_notifications:
                continue  # уже отправляли

            _sent_notifications.add(event_key)
            await _broadcast(bot, db, race, session_key, dt, target_minutes)


async def _broadcast(
    bot: Bot,
    db: Database,
    race: dict,
    session_key: str,
    session_dt,
    minutes_left: int
) -> None:
    """Рассылает уведомление всем подписчикам, выбравшим данное время."""
    kind = "qual" if session_key == "qualifying" else "race"
    subscribers = db.get_subscribers_by_time(kind, minutes_left)

    if not subscribers:
        return

    session_label = SESSION_NAMES[session_key]
    logger.info(
        "Рассылаем уведомление (за %d мин): %s, %s — %d подписчиков",
        minutes_left, race["name"], session_label, len(subscribers)
    )

    for sub in subscribers:
        user_id = sub["user_id"]
        tz = sub["timezone"]
        time_str = format_dt(session_dt, tz)

        text = (
            f"⏰ <b>Через {minutes_left} минут</b> — {race['name']}\n"
            f"{session_label} · {time_str}"
        )
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Не удалось отправить уведомление пользователю %d: %s",
                           user_id, exc)