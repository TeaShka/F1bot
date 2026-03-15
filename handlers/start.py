"""
Обработчик команды /start и главного меню.
"""

import logging
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from database import Database
from keyboards import main_menu_kb

logger = logging.getLogger(__name__)

router = Router(name="start")

from aiogram import F

@router.message(F.photo)
async def get_photo_id(message: Message) -> None:
    file_id = message.photo[-1].file_id
    await message.answer(f"`{file_id}`", parse_mode="Markdown")
@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    """
    Приветствует пользователя при первом запуске.
    Регистрирует пользователя в базе данных.
    """
    user = message.from_user
    # Создаём/обновляем запись пользователя
    db.upsert_user(user.id, user.username)

    tz = db.get_user_timezone(user.id)
    logger.info("Пользователь %d (%s) запустил бота. Часовой пояс: %s",
                user.id, user.username, tz)

    text = (
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        "🏎 Я — бот расписания <b>Формулы 1 — Сезон 2026</b>.\n\n"
        "Я покажу тебе:\n"
        "  • дату и время следующей гонки\n"
        "  • полный календарь сезона\n"
        "  • расписание всех сессий в твоём часовом поясе\n\n"
        f"⏱ Текущий часовой пояс: <code>{tz}</code>\n"
        "Изменить его можно в разделе «Настройки времени»."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, db: Database) -> None:
    """Возвращает пользователя в главное меню по нажатию кнопки."""
    text = "🏠 <b>Главное меню</b>\n\nВыберите раздел:"
    kb = main_menu_kb()

    # Проверяем, есть ли фото в текущем сообщении
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        
    await callback.answer()