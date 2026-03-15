"""
Обработчики настроек пользователя:
  - просмотр и изменение часового пояса
  - геолокация для автоопределения пояса
  - управление уведомлениями
"""

import logging
from timezonefinder import TimezoneFinder

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import Database
from keyboards import (
    settings_kb,
    timezone_kb,
    share_location_kb,
    back_to_menu_kb,
    remove_kb,
)
from utils import is_valid_timezone

logger = logging.getLogger(__name__)

router = Router(name="settings")

# Экземпляр поиска по координатам (ленивая инициализация при первом запросе)
_tf: TimezoneFinder | None = None


def _get_tf() -> TimezoneFinder:
    global _tf
    if _tf is None:
        _tf = TimezoneFinder()
    return _tf


# ── FSM-состояния ─────────────────────────────────────────────────────────────

class SettingsStates(StatesGroup):
    waiting_for_tz_input    = State()  # ожидаем ввод часового пояса вручную
    waiting_for_location    = State()  # ожидаем геолокацию


# ── Главная страница настроек ─────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "settings")
async def cb_settings(callback: CallbackQuery, db: Database) -> None:
    """Открывает страницу настроек."""
    user_id = callback.from_user.id
    tz = db.get_user_timezone(user_id)
    notif = db.get_notification_settings(user_id)

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"🌍 Часовой пояс: <code>{tz}</code>\n\n"
        "🔔 Уведомления (за 1 час до старта):\n"
        f"  • Квалификация: {'✅ вкл.' if notif['notify_qual'] else '❌ выкл.'}\n"
        f"  • Гонка:        {'✅ вкл.' if notif['notify_race'] else '❌ выкл.'}"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=settings_kb(notif["notify_qual"], notif["notify_race"]),
    )
    await callback.answer()


# ── Выбор часового пояса ──────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "change_tz")
async def cb_change_tz(callback: CallbackQuery) -> None:
    """Предлагает выбрать часовой пояс из списка или указать вручную."""
    text = (
        "🌍 <b>Выбор часового пояса</b>\n\n"
        "Выберите свой регион или введите IANA-идентификатор вручную.\n"
        "Например: <code>Europe/Moscow</code>, <code>Asia/Almaty</code>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=timezone_kb(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("tz_") and not c.data == "tz_manual")
async def cb_tz_selected(callback: CallbackQuery, db: Database) -> None:
    """Сохраняет выбранный из списка часовой пояс."""
    tz = callback.data[3:]  # убираем префикс 'tz_'

    if not is_valid_timezone(tz):
        await callback.answer("❌ Неверный часовой пояс", show_alert=True)
        return

    user_id = callback.from_user.id
    db.set_user_timezone(user_id, tz)

    notif = db.get_notification_settings(user_id)
    await callback.message.edit_text(
        f"✅ Часовой пояс установлен: <code>{tz}</code>",
        parse_mode="HTML",
        reply_markup=settings_kb(notif["notify_qual"], notif["notify_race"]),
    )
    await callback.answer(f"Часовой пояс: {tz}")


@router.callback_query(lambda c: c.data == "tz_manual")
async def cb_tz_manual(callback: CallbackQuery, state: FSMContext) -> None:
    """Переходит в режим ручного ввода часового пояса."""
    await state.set_state(SettingsStates.waiting_for_tz_input)
    await callback.message.answer(
        "✏️ Введите IANA-идентификатор часового пояса.\n"
        "Например: <code>Europe/Moscow</code> или <code>Asia/Yekaterinburg</code>\n\n"
        "Полный список: <a href='https://en.wikipedia.org/wiki/List_of_tz_database_time_zones'>"
        "Wikipedia</a>",
        parse_mode="HTML",
        reply_markup=share_location_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_for_tz_input, F.text)
async def msg_tz_text_input(message: Message, state: FSMContext, db: Database) -> None:
    """Обрабатывает текстовый ввод часового пояса."""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Отменено.",
            reply_markup=remove_kb(),
        )
        return

    tz = message.text.strip()
    if not is_valid_timezone(tz):
        await message.answer(
            f"❌ Часовой пояс <code>{tz}</code> не найден.\n"
            "Проверьте написание и попробуйте снова.",
            parse_mode="HTML",
        )
        return

    db.set_user_timezone(message.from_user.id, tz)
    await state.clear()

    notif = db.get_notification_settings(message.from_user.id)
    await message.answer(
        f"✅ Часовой пояс установлен: <code>{tz}</code>",
        parse_mode="HTML",
        reply_markup=remove_kb(),
    )
    # После снятия Reply-клавиатуры возвращаем меню настроек
    await message.answer(
        "⚙️ Вернулись в настройки:",
        reply_markup=settings_kb(notif["notify_qual"], notif["notify_race"]),
    )


@router.message(SettingsStates.waiting_for_tz_input, F.location)
async def msg_location_input(message: Message, state: FSMContext, db: Database) -> None:
    """Определяет часовой пояс по геолокации пользователя."""
    lat = message.location.latitude
    lon = message.location.longitude

    tz = _get_tf().timezone_at(lat=lat, lng=lon)
    if tz is None:
        await message.answer(
            "❌ Не удалось определить часовой пояс по вашим координатам.\n"
            "Попробуйте ввести его вручную.",
            reply_markup=remove_kb(),
        )
        return

    db.set_user_timezone(message.from_user.id, tz)
    await state.clear()

    notif = db.get_notification_settings(message.from_user.id)
    await message.answer(
        f"✅ Часовой пояс определён автоматически: <code>{tz}</code>",
        parse_mode="HTML",
        reply_markup=remove_kb(),
    )
    await message.answer(
        "⚙️ Вернулись в настройки:",
        reply_markup=settings_kb(notif["notify_qual"], notif["notify_race"]),
    )
    logger.info("Пользователь %d: часовой пояс по геолокации = %s",
                message.from_user.id, tz)


# ── Уведомления ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data in ("toggle_notify_qual", "toggle_notify_race"))
async def cb_toggle_notify(callback: CallbackQuery, db: Database) -> None:
    """Переключает состояние уведомлений (вкл/выкл)."""
    user_id = callback.from_user.id
    kind = "qual" if callback.data == "toggle_notify_qual" else "race"

    notif = db.get_notification_settings(user_id)
    new_value = not notif[f"notify_{kind}"]
    db.set_notification(user_id, kind, new_value)

    # Перечитываем актуальные настройки для обновления клавиатуры
    notif = db.get_notification_settings(user_id)
    tz = db.get_user_timezone(user_id)

    status = "включено ✅" if new_value else "выключено ❌"
    label = "квалификации" if kind == "qual" else "гонки"
    await callback.answer(f"Уведомление перед {label}: {status}")

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"🌍 Часовой пояс: <code>{tz}</code>\n\n"
        "🔔 Уведомления (за 1 час до старта):\n"
        f"  • Квалификация: {'✅ вкл.' if notif['notify_qual'] else '❌ выкл.'}\n"
        f"  • Гонка:        {'✅ вкл.' if notif['notify_race'] else '❌ выкл.'}"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=settings_kb(notif["notify_qual"], notif["notify_race"]),
    )
