"""
Bot keyboards.
"""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from utils.time_utils import POPULAR_TIMEZONES


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏎 Следующая гонка", callback_data="next_race"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Календарь сезона", callback_data="calendar"),
    )
    builder.row(
        InlineKeyboardButton(text="🏆 Чемпионат", callback_data="standings_menu"),
    )
    builder.row(
        InlineKeyboardButton(text="🏁 Пилоты сезона", callback_data="drivers_list"),
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
    )
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    return builder.as_markup()


def calendar_kb(rounds: list[dict]) -> InlineKeyboardMarkup:
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)
    builder = InlineKeyboardBuilder()

    for race in rounds:
        race_utc = race["sessions"]["race"].replace(tzinfo=timezone.utc)
        finished = now > race_utc
        name = race["name"].replace("Гран-при ", "")
        prefix = "✅" if finished else race["flag"]
        label = f"{prefix} Эт.{race['round']} {name}"
        builder.button(text=label, callback_data=f"race_{race['round']}")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def settings_kb(
    notify_qual: bool,
    notify_race: bool,
    notify_sprint: bool,
    notify_practice: bool,
    notify_results: bool,
    notify_time: int = 60,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🌍 Часовой пояс",
            callback_data="change_tz",
        )
    )

    qual_icon = "✅" if notify_qual else "❌"
    race_icon = "✅" if notify_race else "❌"
    sprint_icon = "✅" if notify_sprint else "❌"
    practice_icon = "✅" if notify_practice else "❌"
    results_icon = "✅" if notify_results else "❌"
    time_label = "1 час" if notify_time == 60 else "15 мин"

    builder.row(
        InlineKeyboardButton(
            text=f"{qual_icon} Квалификация",
            callback_data="toggle_notify_qual",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{race_icon} Гонка",
            callback_data="toggle_notify_race",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{sprint_icon} Спринты",
            callback_data="toggle_notify_sprint",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{practice_icon} Практики",
            callback_data="toggle_notify_practice",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{results_icon} Итоги этапа",
            callback_data="toggle_notify_results",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"⏰ За сколько: {time_label}",
            callback_data="toggle_notify_time",
        )
    )
    builder.row(
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
    )
    return builder.as_markup()


def timezone_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, tz_id in POPULAR_TIMEZONES.items():
        builder.button(text=label, callback_data=f"tz_{tz_id}")
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="tz_manual"),
    )
    builder.row(
        InlineKeyboardButton(text="◀ Назад", callback_data="settings"),
    )
    return builder.as_markup()


def share_location_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(
        text="📍 Отправить геолокацию",
        request_location=True,
    )
    builder.button(text="❌ Отмена")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def standings_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Пилоты", callback_data="driver_standings"),
    )
    builder.row(
        InlineKeyboardButton(text="🏗 Конструкторы", callback_data="constructor_standings"),
    )
    builder.row(
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()
