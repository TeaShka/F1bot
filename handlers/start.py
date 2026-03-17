"""
Обработчик команды /start и главного меню.
"""

import logging
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from database import Database
from keyboards import main_menu_kb

# Вставь сюда file_id своей картинки (получи через @getidsbot)
WELCOME_PHOTO = "https://i.pinimg.com/736x/d6/a1/48/d6a1482c0f038dfbca2194581932ecc1.jpg"  # например: "AgACAgIAAxkBAAI..."

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    user = message.from_user
    db.upsert_user(user.id, user.username)
    tz = db.get_user_timezone(user.id)
    logger.info("Пользователь %d (%s) запустил бота. Часовой пояс: %s",
                user.id, user.username, tz)

    text = (
        f"Привет, <b>{user.first_name}</b>\n\n"
        "<b>ГазуРейсинг F1 🏎</b>\n"
        "<i>Сделан обычным фанатом Формулы 1 для таких же фанатов</i>\n\n"
        "Здесь ты найдёшь всё что нужно перед гонкой: расписание сессий "
        "в твоём часовом поясе, таблицу очков после каждого этапа, "
        "профили пилотов и результаты завершённых гонок.\n\n"
        "<b>Что умеет бот:</b>\n"
        "  · Следующая гонка — дата, трасса, расписание всех сессий\n"
        "  · Календарь — все этапы сезона с отметкой завершённых\n"
        "  · Таблица очков — личный зачёт и кубок конструкторов\n"
        "  · Пилоты — профили, карьерная статистика, стиль вождения\n"
        "  · Уведомления — напомню за 1 час или 15 минут до старта\n\n"
        f"Часовой пояс: <code>{tz}</code>\n"
        "<i>Сменить можно в разделе Настройки</i>"
    )
    if WELCOME_PHOTO:
        await message.answer_photo(
            photo=WELCOME_PHOTO,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, db: Database) -> None:
    text = "🏠 <b>Главное меню</b>\n\nВыберите раздел:"
    kb = main_menu_kb()
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.message(Command("next"))
async def cmd_next(message: Message, db: Database) -> None:
    """Команда /next — следующая гонка."""
    from aiogram.types import CallbackQuery
    from handlers.races import cb_next_race
    # Эмулируем нажатие кнопки через отдельный вызов
    from bot_config.schedule import SCHEDULE_2026
    from keyboards import back_to_menu_kb
    from utils import get_next_race, format_dt
    from datetime import timezone

    tz = db.get_user_timezone(message.from_user.id)
    race = get_next_race(SCHEDULE_2026)

    if race is None:
        await message.answer("🏁 Сезон 2026 завершён!")
        return

    from handlers.races import _build_race_detail, is_race_finished, TRACK_MAPS
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    text = (
        f"🔜 <b>Следующий Гран-при</b> (этап {race['round']} из {len(SCHEDULE_2026)})\n\n"
    ) + _build_race_detail(race, tz)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📺 Где смотреть?", callback_data=f"watch_{race['round']}"))
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"))
    kb = builder.as_markup()

    track_photo = TRACK_MAPS.get(race['round'])
    if track_photo:
        await message.answer_photo(photo=track_photo, caption=text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("calendar"))
async def cmd_calendar(message: Message) -> None:
    """Команда /calendar — календарь сезона."""
    from bot_config.schedule import SCHEDULE_2026
    from keyboards import calendar_kb
    await message.answer(
        "📅 <b>Календарь Формулы 1 — Сезон 2026</b>\n\nВыберите этап:",
        parse_mode="HTML",
        reply_markup=calendar_kb(SCHEDULE_2026),
    )


@router.message(Command("standings"))
async def cmd_standings(message: Message) -> None:
    """Команда /standings — таблица очков."""
    from keyboards import standings_menu_kb
    await message.answer(
        "🏆 <b>Таблица очков — Сезон 2026</b>\n\nВыберите зачёт:",
        parse_mode="HTML",
        reply_markup=standings_menu_kb(),
    )


@router.message(Command("pilots"))
async def cmd_pilots(message: Message) -> None:
    """Команда /pilots — список пилотов."""
    from handlers.drivers import _get, DRIVERS_2026_URL, _drivers_kb
    data = await _get(DRIVERS_2026_URL)
    if not data:
        await message.answer("❌ Не удалось загрузить список пилотов.")
        return
    try:
        drivers = data["MRData"]["DriverTable"]["Drivers"]
    except (KeyError, IndexError):
        await message.answer("❌ Ошибка данных.")
        return
    await message.answer(
        "🏎 <b>Пилоты сезона 2026</b>\n\nВыберите пилота:",
        parse_mode="HTML",
        reply_markup=_drivers_kb(drivers),
    )