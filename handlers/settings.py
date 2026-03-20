"""
User settings handlers.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from timezonefinder import TimezoneFinder

from database import Database
from keyboards import remove_kb, settings_kb, share_location_kb, timezone_kb
from utils import is_valid_timezone

logger = logging.getLogger(__name__)
router = Router(name="settings")

_tf: TimezoneFinder | None = None


def _get_tf() -> TimezoneFinder:
    global _tf
    if _tf is None:
        _tf = TimezoneFinder()
    return _tf


def _build_status_lines(labels: list[tuple[str, bool]], *, width: int = 14) -> str:
    lines: list[str] = []
    for label, enabled in labels:
        status = "ВКЛ" if enabled else "ВЫКЛ"
        padding = " " * max(1, width - len(label))
        lines.append(f"<code>{label}{padding}{status}</code>")
    return "\n".join(lines)


def _settings_text(tz: str, notif: dict, n_time: int, banner: str | None = None) -> str:
    before_start_labels = [
        ("Квалификация", notif["notify_qual"]),
        ("Гонка", notif["notify_race"]),
        ("Спринты", notif["notify_sprint"]),
        ("Практики", notif["notify_practice"]),
    ]
    results_labels = [
        ("Итоги этапа", notif["notify_results"]),
    ]

    parts = []
    if banner:
        parts.extend([banner, ""])

    parts.extend(
        [
            "⚙️ <b>Настройки</b>",
            "",
            "🌍 <b>Часовой пояс</b>",
            f"<code>{tz}</code>",
            "",
            "🔔 <b>До старта сессии</b>",
            f"За сколько: <b>{n_time} мин</b> до начала",
            "",
            _build_status_lines(before_start_labels),
            "",
            "📰 <b>После публикации</b>",
            _build_status_lines(results_labels),
        ]
    )
    return "\n".join(parts)


def _settings_markup(notif: dict, n_time: int):
    return settings_kb(
        notif["notify_qual"],
        notif["notify_race"],
        notif["notify_sprint"],
        notif["notify_practice"],
        notif["notify_results"],
        n_time,
    )


async def _send_settings_screen(
    target: CallbackQuery | Message,
    db: Database,
    *,
    banner: str | None = None,
    remove_reply_keyboard: bool = False,
) -> None:
    if isinstance(target, CallbackQuery):
        user_id = target.from_user.id
        tz = db.get_user_timezone(user_id)
        notif = db.get_notification_settings(user_id)
        n_time = notif.get("notify_time", 60)
        text = _settings_text(tz, notif, n_time, banner=banner)
        markup = _settings_markup(notif, n_time)

        if target.message.photo:
            await target.message.delete()
            await target.message.answer(text, parse_mode="HTML", reply_markup=markup)
        else:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        return

    user_id = target.from_user.id
    tz = db.get_user_timezone(user_id)
    notif = db.get_notification_settings(user_id)
    n_time = notif.get("notify_time", 60)

    if remove_reply_keyboard:
        cleanup = await target.answer("✅ Готово", reply_markup=remove_kb())
        try:
            await cleanup.delete()
        except Exception:
            pass

    await target.answer(
        _settings_text(tz, notif, n_time, banner=banner),
        parse_mode="HTML",
        reply_markup=_settings_markup(notif, n_time),
    )


class SettingsStates(StatesGroup):
    waiting_for_tz_input = State()
    waiting_for_location = State()


@router.callback_query(lambda c: c.data == "settings")
async def cb_settings(callback: CallbackQuery, db: Database) -> None:
    await _send_settings_screen(callback, db)
    await callback.answer()


@router.callback_query(lambda c: c.data == "change_tz")
async def cb_change_tz(callback: CallbackQuery) -> None:
    text = (
        "🌍 <b>Часовой пояс</b>\n\n"
        "Выберите вариант из списка ниже.\n"
        "Если нужного нет, нажмите <b>«Ввести вручную»</b> или отправьте геолокацию."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=timezone_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("tz_") and c.data != "tz_manual")
async def cb_set_popular_tz(callback: CallbackQuery, db: Database) -> None:
    tz_id = callback.data.replace("tz_", "", 1)
    db.set_user_timezone(callback.from_user.id, tz_id)
    await _send_settings_screen(callback, db, banner=f"✅ Часовой пояс обновлён: <code>{tz_id}</code>")
    await callback.answer("Часовой пояс обновлён")


@router.callback_query(lambda c: c.data == "tz_manual")
async def cb_tz_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_for_tz_input)
    text = (
        "✏️ <b>Часовой пояс вручную</b>\n\n"
        "Введите часовой пояс в формате IANA.\n"
        "<i>Например: Europe/Moscow, Asia/Yekaterinburg, America/New_York</i>\n\n"
        "Или отправьте геолокацию по кнопке ниже."
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=share_location_kb())
    await callback.answer()


@router.message(SettingsStates.waiting_for_tz_input, F.text)
async def process_manual_tz(message: Message, state: FSMContext, db: Database) -> None:
    tz_input = message.text.strip()

    if tz_input == "❌ Отмена":
        await state.clear()
        await _send_settings_screen(
            message,
            db,
            banner="ℹ️ Изменения не вносились.",
            remove_reply_keyboard=True,
        )
        return

    if is_valid_timezone(tz_input):
        db.set_user_timezone(message.from_user.id, tz_input)
        await state.clear()
        await _send_settings_screen(
            message,
            db,
            banner=f"✅ Часовой пояс обновлён: <code>{tz_input}</code>",
            remove_reply_keyboard=True,
        )
        return

    await message.answer(
        "❌ Не удалось распознать часовой пояс.\n"
        "Попробуйте ещё раз в формате <code>Europe/Moscow</code> или нажмите <b>«Отмена»</b>.",
        parse_mode="HTML",
    )


@router.message(SettingsStates.waiting_for_tz_input, F.location)
async def process_location(message: Message, state: FSMContext, db: Database) -> None:
    lat = message.location.latitude
    lng = message.location.longitude

    tf = _get_tf()
    tz_name = tf.timezone_at(lng=lng, lat=lat)

    if tz_name:
        db.set_user_timezone(message.from_user.id, tz_name)
        await state.clear()
        await _send_settings_screen(
            message,
            db,
            banner=f"📍 Часовой пояс определён автоматически: <code>{tz_name}</code>",
            remove_reply_keyboard=True,
        )
        logger.info("User %d timezone from location: %s", message.from_user.id, tz_name)
        return

    await message.answer(
        "❌ Не удалось определить часовой пояс по геолокации.\n"
        "Попробуйте отправить точку ещё раз или введите пояс вручную."
    )


@router.callback_query(
    lambda c: c.data in (
        "toggle_notify_qual",
        "toggle_notify_race",
        "toggle_notify_sprint",
        "toggle_notify_practice",
        "toggle_notify_results",
    )
)
async def cb_toggle_notify(callback: CallbackQuery, db: Database) -> None:
    user_id = callback.from_user.id
    kind_map = {
        "toggle_notify_qual": "qual",
        "toggle_notify_race": "race",
        "toggle_notify_sprint": "sprint",
        "toggle_notify_practice": "practice",
        "toggle_notify_results": "results",
    }
    label_map = {
        "qual": "Квалификация",
        "race": "Гонка",
        "sprint": "Спринты",
        "practice": "Практики",
        "results": "Итоги этапа",
    }

    kind = kind_map[callback.data]
    notif = db.get_notification_settings(user_id)
    new_value = not notif[f"notify_{kind}"]
    db.set_notification(user_id, kind, new_value)

    banner = f"{'✅' if new_value else '❌'} {label_map[kind]}: {'включено' if new_value else 'выключено'}"
    await _send_settings_screen(callback, db, banner=banner)
    await callback.answer(f"{label_map[kind]}: {'вкл' if new_value else 'выкл'}")


@router.callback_query(lambda c: c.data == "toggle_notify_time")
async def cb_toggle_notify_time(callback: CallbackQuery, db: Database) -> None:
    user_id = callback.from_user.id
    current_time = db.get_notify_time(user_id)
    new_time = 15 if current_time == 60 else 60
    db.set_notify_time(user_id, new_time)

    await _send_settings_screen(
        callback,
        db,
        banner=f"⏰ Напоминание теперь приходит за <b>{new_time} мин</b> до старта.",
    )
    await callback.answer(f"Теперь за {new_time} мин")
