"""
Race-related handlers:
  - next race
  - full season calendar
  - single race details
  - finished race summary
"""

import asyncio
import logging
from datetime import timezone

from aiogram import Router
from aiogram.types import CallbackQuery

from bot_config.schedule import SCHEDULE_2026, SESSION_NAMES
from database import Database
from keyboards import back_to_menu_kb, calendar_kb
from utils import format_dt, get_next_race, now_utc
from utils.api_client import ApiClient

logger = logging.getLogger(__name__)
router = Router(name="races")

RACE_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/2026/{round}/results.json"
QUALI_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/2026/{round}/qualifying.json"
RESULTS_TTL = 900

TRACK_MAPS = {
    1: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackmelbournedetailed.webp",
    2: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackshanghaidetailed.webp",
    3: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026tracksuzukadetailed.webp",
    4: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackmiamidetailed.webp",
    5: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackmontrealdetailed.webp",
    6: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackmontecarlodetailed.webp",
    7: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackcatalunyadetailed.webp",
    8: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackspielbergdetailed.webp",
    9: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026tracksilverstonedetailed.webp",
    10: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackspafrancorchampsdetailed.webp",
    11: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackhungaroringdetailed.webp",
    12: "https://media.formula1.com/image/upload/c_fit,h_704/q_auto/v1740000000/common/f1/2026/track/2026trackzandvoortdetailed.webp",
}

WATCH_LINKS = {
    "popov": "https://vk.com/gasnutognif1",
    "stanislavsky": "https://vk.com/stanizlavskylive",
    "simply": "https://vk.com/simply_plus",
}


def is_race_finished(race: dict) -> bool:
    race_utc = race["sessions"]["race"].replace(tzinfo=timezone.utc)
    return now_utc() > race_utc


async def fetch_quali_result(api: ApiClient, round_num: int) -> dict | None:
    return await api.fetch_json(QUALI_RESULTS_URL.format(round=round_num), ttl=RESULTS_TTL)


async def fetch_race_result(api: ApiClient, round_num: int) -> dict | None:
    return await api.fetch_json(RACE_RESULTS_URL.format(round=round_num), ttl=RESULTS_TTL)


def _build_race_detail(race: dict, timezone_name: str) -> str:
    finished = is_race_finished(race)
    name_line = (
        f"{race['flag']} <b><s>{race['name']}</s></b> ✅"
        if finished
        else f"{race['flag']} <b>{race['name']}</b>"
    )

    lines = [
        name_line,
        f"<i>{race['circuit']} · {race['country']}</i>",
        "",
        "<b>Расписание сессий:</b>",
    ]

    session_width = 22
    for session_key, session_label in SESSION_NAMES.items():
        session_dt = race["sessions"].get(session_key)
        if session_dt is None:
            continue

        time_str = format_dt(session_dt, timezone_name)
        label_clean = session_label.replace("⚡ ", "").replace("🏁 ", "")
        padding = " " * max(1, session_width - len(label_clean))
        lines.append(f"<code>{label_clean}{padding}{time_str}</code>")

    lines.append(f"\n<i>Часовой пояс: {timezone_name}</i>")
    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "next_race")
async def cb_next_race(callback: CallbackQuery, db: Database) -> None:
    user_id = callback.from_user.id
    timezone_name = db.get_user_timezone(user_id)
    race = get_next_race(SCHEDULE_2026)

    if race is None:
        text = "🏃 Сезон 2026 завершён!\n\nСледите за новостями о сезоне 2027 🏎"
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=back_to_menu_kb())
        else:
            await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()
        return

    remaining = sum(1 for item in SCHEDULE_2026 if item["sessions"]["race"] >= race["sessions"]["race"])
    text = (
        f"<b>Следующий Гран-при</b>  ·  этап {race['round']} из {len(SCHEDULE_2026)}\n"
        f"<i>До конца сезона: {remaining} гонок</i>\n\n"
        f"{_build_race_detail(race, timezone_name)}"
    )

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📺 Где смотреть?", callback_data=f"watch_{race['round']}"))
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"))
    kb = builder.as_markup()

    track_photo = TRACK_MAPS.get(race["round"])
    if track_photo:
        await callback.message.delete()
        await callback.message.answer_photo(photo=track_photo, caption=text, parse_mode="HTML", reply_markup=kb)
    elif callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

    await callback.answer()


@router.callback_query(lambda c: c.data == "calendar")
async def cb_calendar(callback: CallbackQuery) -> None:
    text = "📅 <b>Календарь Формулы 1 - Сезон 2026</b>\n\nВыберите этап:"
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=calendar_kb(SCHEDULE_2026))
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=calendar_kb(SCHEDULE_2026))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("race_") and not c.data.startswith("race_info_"))
async def cb_race_detail(callback: CallbackQuery, db: Database) -> None:
    try:
        round_num = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("Неверный номер этапа", show_alert=True)
        return

    race = next((item for item in SCHEDULE_2026 if item["round"] == round_num), None)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    timezone_name = db.get_user_timezone(callback.from_user.id)
    text = _build_race_detail(race, timezone_name)

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📺 Где смотреть?", callback_data=f"watch_{round_num}"))
    if is_race_finished(race):
        builder.row(
            InlineKeyboardButton(
                text="🏆 Информация о гонке",
                callback_data=f"race_info_{round_num}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"))
    kb = builder.as_markup()

    track_photo = TRACK_MAPS.get(round_num)
    if track_photo:
        await callback.message.delete()
        await callback.message.answer_photo(photo=track_photo, caption=text, parse_mode="HTML", reply_markup=kb)
    elif callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("watch_"))
async def cb_where_to_watch(callback: CallbackQuery) -> None:
    try:
        round_num = callback.data.split("_")[1]
    except IndexError:
        await callback.answer("Ошибка")
        return

    text = (
        "📺 <b>Где смотреть трансляции Формулы 1:</b>\n\n"
        f"• Алексей Попов/Наталья Фабричная - <a href='{WATCH_LINKS['popov']}'>Ссылка</a>\n"
        f"• Станиславский - <a href='{WATCH_LINKS['stanislavsky']}'>Ссылка</a>\n"
        f"• Simply Formula (Роман) - <a href='{WATCH_LINKS['simply']}'>Ссылка</a>"
    )

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад к этапу", callback_data=f"race_{round_num}"))
    kb = builder.as_markup()

    if callback.message.photo:
        await callback.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("race_info_"))
async def cb_race_info(callback: CallbackQuery, api: ApiClient) -> None:
    try:
        round_num = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return

    race = next((item for item in SCHEDULE_2026 if item["round"] == round_num), None)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    await callback.answer("⏳ Загружаю результаты...")

    data, quali_data = await asyncio.gather(
        fetch_race_result(api, round_num),
        fetch_quali_result(api, round_num),
    )

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад к этапу", callback_data=f"race_{round_num}"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    kb = builder.as_markup()

    if data is None:
        error_text = (
            f"{race['flag']} <b>{race['name']}</b>\n\n"
            "❌ Результаты ещё не опубликованы или API недоступен.\n"
            "Попробуй через несколько часов после финиша."
        )
        if callback.message.photo:
            await callback.message.edit_caption(caption=error_text, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.edit_text(error_text, parse_mode="HTML", reply_markup=kb)
        return

    try:
        results = data["MRData"]["RaceTable"]["Races"][0]["Results"]
    except (KeyError, IndexError):
        error_text = (
            f"{race['flag']} <b>{race['name']}</b>\n\n"
            "❌ Результаты ещё не опубликованы.\n"
            "Данные появляются через несколько часов после финиша."
        )
        if callback.message.photo:
            await callback.message.edit_caption(caption=error_text, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.edit_text(error_text, parse_mode="HTML", reply_markup=kb)
        return

    podium_icons = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [
        f"{race['flag']} <b>{race['name']}</b>",
        race["circuit"],
        "",
        "<b>Подиум:</b>",
    ]

    fastest_lap_driver = None
    fastest_lap_time = None

    for result in results:
        position = int(result.get("position", 99))
        driver = f"{result['Driver']['givenName']} {result['Driver']['familyName']}"
        team = result["Constructor"]["name"]
        status = result.get("status", "")

        if position <= 3:
            icon = podium_icons[position]
            time_value = result.get("Time", {}).get("time", status)
            lines.append(f"{icon} <b>{driver}</b> - {team}")
            if position == 1:
                lines.append(f"    ⏱ {time_value}")
            else:
                lines.append(f"    {time_value}")

        fastest_lap = result.get("FastestLap", {})
        if fastest_lap.get("rank") == "1":
            fastest_lap_driver = driver
            fastest_lap_time = fastest_lap.get("Time", {}).get("time", "—")

    pole_driver = None
    pole_time = None
    if quali_data:
        try:
            qualifying_results = quali_data["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"]
            pole = next((item for item in qualifying_results if item["position"] == "1"), None)
            if pole:
                pole_driver = f"{pole['Driver']['givenName']} {pole['Driver']['familyName']}"
                pole_time = pole.get("Q3") or pole.get("Q2") or pole.get("Q1", "—")
        except (KeyError, IndexError):
            pass

    if pole_driver:
        lines.extend(["", f"⚡ <b>Поул-позиция:</b> {pole_driver} - {pole_time}"])

    if fastest_lap_driver and fastest_lap_time:
        lines.append(f"🔥 <b>Быстрый круг:</b> {fastest_lap_driver} - {fastest_lap_time}")

    final_text = "\n".join(lines)
    if callback.message.photo:
        await callback.message.edit_caption(caption=final_text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(final_text, parse_mode="HTML", reply_markup=kb)

    logger.info("Race results viewed for round %d", round_num)
