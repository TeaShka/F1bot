"""
User settings handlers.
"""

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


def _settings_text(tz: str, notif: dict, n_time: int) -> str:
    before_start_labels = [
        ("Квалификация", notif["notify_qual"]),
        ("Гонка", notif["notify_race"]),
        ("Спринты", notif["notify_sprint"]),
        ("Практики", notif["notify_practice"]),
    ]
    results_labels = [
        ("Итоги этапа", notif["notify_results"]),
    ]

    return (
        "⚙️ <b>Настройки</b>\n\n"
        "🌍 <b>Часовой пояс</b>\n"
        f"<code>{tz}</code>\n\n"
        "🔔 <b>До старта сессии</b>\n"
        f"За сколько: <b>{n_time} мин</b> до старта\n\n"
        f"{_build_status_lines(before_start_labels)}\n\n"
        "📰 <b>После публикации</b>\n"
        f"{_build_status_lines(results_labels)}"
    )


def _settings_markup(notif: dict, n_time: int):
    return settings_kb(
        notif["notify_qual"],
        notif["notify_race"],
        notif["notify_sprint"],
        notif["notify_practice"],
        notif["notify_results"],
        n_time,
    )


class SettingsStates(StatesGroup):
    waiting_for_tz_input = State()
    waiting_for_location = State()


@router.callback_query(lambda c: c.data == "settings")
async def cb_settings(callback: CallbackQuery, db: Database) -> None:
    user_id = callback.from_user.id
    tz = db.get_user_timezone(user_id)
    notif = db.get_notification_settings(user_id)
    n_time = notif.get("notify_time", 60)

    text = _settings_text(tz, notif, n_time)
    kb = _settings_markup(notif, n_time)

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

    await callback.answer()


@router.callback_query(lambda c: c.data == "change_tz")
async def cb_change_tz(callback: CallbackQuery) -> None:
    text = (
        "🌌 <b>Выбор часового пояса</b>\n\n"
        "Выбери из популярных или нажми «Ввести вручную».\n"
        "Также можешь отправить свою геолокацию, и бот определит пояс автоматически."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=timezone_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("tz_") and c.data != "tz_manual")
async def cb_set_popular_tz(callback: CallbackQuery, db: Database) -> None:
    tz_id = callback.data.replace("tz_", "", 1)
    db.set_user_timezone(callback.from_user.id, tz_id)
    await callback.answer(f"Часовой пояс изменён на {tz_id}")
    await cb_settings(callback, db)


@router.callback_query(lambda c: c.data == "tz_manual")
async def cb_tz_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_for_tz_input)
    text = (
        "✏️ Введи название часового пояса в формате IANA.\n\n"
        "<i>Примеры: Europe/Moscow, Asia/Yekaterinburg, America/New_York</i>\n\n"
        "Либо отправь геолокацию с телефона по кнопке ниже."
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=share_location_kb())
    await callback.answer()


@router.message(SettingsStates.waiting_for_tz_input, F.text)
async def process_manual_tz(message: Message, state: FSMContext, db: Database) -> None:
    tz_input = message.text.strip()

    if tz_input == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Ввод отменён. Возвращаемся в настройки.",
            reply_markup=remove_kb(),
        )
        fake_cb = CallbackQuery(
            id="fake",
            from_user=message.from_user,
            chat_instance="fake",
            message=await message.answer("Загрузка настроек..."),
        )
        await cb_settings(fake_cb, db)
        return

    if is_valid_timezone(tz_input):
        db.set_user_timezone(message.from_user.id, tz_input)
        await state.clear()
        await message.answer(
            f"✅ Часовой пояс успешно изменён на <code>{tz_input}</code>",
            parse_mode="HTML",
            reply_markup=remove_kb(),
        )
        fake_cb = CallbackQuery(
            id="fake",
            from_user=message.from_user,
            chat_instance="fake",
            message=await message.answer("Обновление меню..."),
        )
        await cb_settings(fake_cb, db)
        return

    await message.answer(
        "❌ Неверный формат. Попробуй ещё раз или нажми «Отмена».\n"
        "Пример: <code>Europe/Moscow</code>",
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
        await message.answer(
            f"📍 По координатам определён пояс: <code>{tz_name}</code>\n"
            "Настройка сохранена.",
            parse_mode="HTML",
            reply_markup=remove_kb(),
        )
        fake_cb = CallbackQuery(
            id="fake",
            from_user=message.from_user,
            chat_instance="fake",
            message=await message.answer("Возврат в настройки..."),
        )
        await cb_settings(fake_cb, db)
        logger.info("User %d timezone from location: %s", message.from_user.id, tz_name)
        return

    await message.answer(
        "❌ Не удалось определить часовой пояс. Попробуй ввести вручную."
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
        "qual": "квалификацией",
        "race": "гонкой",
        "sprint": "спринтами",
        "practice": "практиками",
        "results": "итогами этапа",
    }

    kind = kind_map[callback.data]
    notif = db.get_notification_settings(user_id)
    new_value = not notif[f"notify_{kind}"]
    db.set_notification(user_id, kind, new_value)

    notif = db.get_notification_settings(user_id)
    tz = db.get_user_timezone(user_id)
    n_time = notif.get("notify_time", 60)

    status = "включено ✅" if new_value else "выключено ❌"
    await callback.answer(f"Уведомление перед {label_map[kind]}: {status}")

    await callback.message.edit_text(
        _settings_text(tz, notif, n_time),
        parse_mode="HTML",
        reply_markup=_settings_markup(notif, n_time),
    )


@router.callback_query(lambda c: c.data == "toggle_notify_time")
async def cb_toggle_notify_time(callback: CallbackQuery, db: Database) -> None:
    user_id = callback.from_user.id
    current_time = db.get_notify_time(user_id)
    new_time = 15 if current_time == 60 else 60
    db.set_notify_time(user_id, new_time)

    await cb_settings(callback, db)
    await callback.answer(f"Время изменено на {new_time} минут")
