"""
Модуль клавиатур.
Все Inline- и Reply-клавиатуры бота собраны здесь.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from utils.time_utils import POPULAR_TIMEZONES


def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏎 Следующая гонка",  callback_data="next_race"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Календарь 2026",   callback_data="calendar"),
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки времени", callback_data="settings"),
    )
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ В главное меню", callback_data="main_menu")
    return builder.as_markup()


def calendar_kb(rounds: list[dict]) -> InlineKeyboardMarkup:
    """
    Клавиатура для листания этапов календаря.
    Каждая кнопка — отдельный этап.
    """
    builder = InlineKeyboardBuilder()
    for race in rounds:
        label = f"{race['flag']} Эт.{race['round']} {race['name']}"
        builder.button(
            text=label,
            callback_data=f"race_{race['round']}"
        )
    builder.adjust(1)  # по одной кнопке в строку
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"))
    return builder.as_markup()


def settings_kb(notify_qual: bool, notify_race: bool) -> InlineKeyboardMarkup:
    """Клавиатура настроек: смена часового пояса и уведомления."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🌍 Изменить часовой пояс", callback_data="change_tz"
        )
    )
    # Кнопки уведомлений с отображением текущего состояния
    qual_icon = "✅" if notify_qual else "❌"
    race_icon = "✅" if notify_race else "❌"
    builder.row(
        InlineKeyboardButton(
            text=f"{qual_icon} Уведомление: квалификация",
            callback_data="toggle_notify_qual"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{race_icon} Уведомление: гонка",
            callback_data="toggle_notify_race"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")
    )
    return builder.as_markup()


def timezone_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора часового пояса из популярных."""
    builder = InlineKeyboardBuilder()
    for label, tz_id in POPULAR_TIMEZONES.items():
        builder.button(text=label, callback_data=f"tz_{tz_id}")
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="tz_manual"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад",          callback_data="settings"),
    )
    return builder.as_markup()


def share_location_kb() -> ReplyKeyboardMarkup:
    """Reply-клавиатура для отправки геолокации (автоопределение пояса)."""
    builder = ReplyKeyboardBuilder()
    builder.button(
        text="📍 Отправить геолокацию",
        request_location=True
    )
    builder.button(text="❌ Отмена")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def remove_kb() -> ReplyKeyboardRemove:
    """Убирает Reply-клавиатуру."""
    return ReplyKeyboardRemove()
