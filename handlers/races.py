"""
Обработчики, связанные с гонками:
  - следующая гонка
  - полный календарь сезона
  - детали конкретного этапа
"""

import logging
from aiogram import Router
from aiogram.types import CallbackQuery

from bot_config.schedule import SCHEDULE_2026, SESSION_NAMES
from database import Database
from keyboards import back_to_menu_kb, calendar_kb
from utils import get_next_race, format_dt

logger = logging.getLogger(__name__)

router = Router(name="races")


def _build_race_detail(race: dict, tz: str) -> str:
    """
    Формирует текстовое представление этапа со всеми сессиями.

    :param race: Словарь с данными этапа из SCHEDULE_2026
    :param tz:   IANA-идентификатор часового пояса пользователя
    """
    lines = [
        f"{race['flag']} <b>{race['name']}</b>",
        f"🏟 Трасса: {race['circuit']}",
        f"📍 Страна: {race['country']}",
        "",
        "📋 <b>Расписание сессий:</b>",
    ]

    for session_key, session_label in SESSION_NAMES.items():
        dt = race["sessions"].get(session_key)
        if dt is not None:
            time_str = format_dt(dt, tz)
            lines.append(f"  {session_label}\n    📆 {time_str}")

    lines.append(f"\n⏱ Время указано для пояса: <code>{tz}</code>")
    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "next_race")
async def cb_next_race(callback: CallbackQuery, db: Database) -> None:
    """Показывает ближайший Гран-при с расписанием сессий."""
    user_id = callback.from_user.id
    tz = db.get_user_timezone(user_id)

    race = get_next_race(SCHEDULE_2026)

    if race is None:
        text = (
            "🏁 Сезон 2026 завершён!\n\n"
            "Следите за новостями о сезоне 2027 🏎"
        )
        await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()
        return

    # Определяем номер оставшихся гонок для контекста
    remaining = sum(1 for r in SCHEDULE_2026
                    if r["sessions"]["race"] >= race["sessions"]["race"])

    text = (
        f"🔜 <b>Следующий Гран-при</b> (этап {race['round']} из 24)\n"
        f"Осталось гонок в сезоне: {remaining}\n\n"
    ) + _build_race_detail(race, tz)

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()
    logger.info("Пользователь %d запросил следующую гонку (этап %d)",
                user_id, race["round"])


@router.callback_query(lambda c: c.data == "calendar")
async def cb_calendar(callback: CallbackQuery) -> None:
    """Выводит список всех этапов сезона 2026."""
    text = "📅 <b>Календарь Формулы 1 — Сезон 2026</b>\n\nВыберите этап:"
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=calendar_kb(SCHEDULE_2026),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("race_"))
async def cb_race_detail(callback: CallbackQuery, db: Database) -> None:
    """Показывает детали конкретного этапа по его номеру."""
    try:
        round_num = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("Неверный номер этапа", show_alert=True)
        return

    # Ищем этап в расписании
    race = next((r for r in SCHEDULE_2026 if r["round"] == round_num), None)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    tz = db.get_user_timezone(user_id)

    text = _build_race_detail(race, tz)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()
    logger.info("Пользователь %d просмотрел этап %d", user_id, round_num)
