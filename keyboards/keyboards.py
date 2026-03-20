"""
Модуль клавиатур.
Все Inline- и Reply-клавиатуры бота собраны здесь.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from utils.time_utils import POPULAR_TIMEZONES


def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏎 Следующая гонка", callback_data="next_race"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Календарь 2026", callback_data="calendar"),
    )
    builder.row(
        InlineKeyboardButton(text="🏆 Таблица очков", callback_data="standings_menu"),
    )
    builder.row(
        InlineKeyboardButton(text="🏎 Пилоты 2026", callback_data="drivers_list"),
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
    Завершённые гонки отмечаются ✅.
    """
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)
    builder = InlineKeyboardBuilder()

    for race in rounds:
        race_utc = race["sessions"]["race"].replace(tzinfo=timezone.utc)
        finished = now > race_utc
        if finished:
            name = race["name"].replace("Гран-при ", "")
            label = f"✅ {name}"
        else:
            label = f"{race['flag']} Эт.{race['round']} {race['name']}"
        builder.button(text=label, callback_data=f"race_{race['round']}")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"))
    return builder.as_markup()


def settings_kb(
    notify_qual: bool,
    notify_race: bool,
    notify_sprint: bool,
    notify_practice: bool,
    notify_time: int = 60,
) -> InlineKeyboardMarkup:
    """Клавиатура настроек: смена часового пояса и уведомления."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🌌 Изменить часовой пояс", callback_data="change_tz"
        )
    )

    qual_icon = "✅" if notify_qual else "❌"
    race_icon = "✅" if notify_race else "❌"
    sprint_icon = "✅" if notify_sprint else "❌"
    practice_icon = "✅" if notify_practice else "❌"
    time_label = "1 час" if notify_time == 60 else "15 мин"

    builder.row(
        InlineKeyboardButton(
            text=f"{qual_icon} Уведомление: квалификация",
            callback_data="toggle_notify_qual",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{race_icon} Уведомление: гонка",
            callback_data="toggle_notify_race",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{sprint_icon} Уведомление: спринты",
            callback_data="toggle_notify_sprint",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{practice_icon} Уведомление: практики",
            callback_data="toggle_notify_practice",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"⏰ Напомнить за: {time_label}",
            callback_data="toggle_notify_time",
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
        InlineKeyboardButton(text="◀️ Назад", callback_data="settings"),
    )
    return builder.as_markup()


def share_location_kb() -> ReplyKeyboardMarkup:
    """Reply-клавиатура для отправки геолокации."""
    builder = ReplyKeyboardBuilder()
    builder.button(
        text="📍 Отправить геолокацию",
        request_location=True,
    )
    builder.button(text="❌ Отмена")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def remove_kb() -> ReplyKeyboardRemove:
    """Убирает Reply-клавиатуру."""
    return ReplyKeyboardRemove()


def standings_menu_kb() -> InlineKeyboardMarkup:
    """Меню выбора таблицы очков."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Личный зачёт", callback_data="driver_standings"),
    )
    builder.row(
        InlineKeyboardButton(text="🏗 Конструкторы", callback_data="constructor_standings"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()
