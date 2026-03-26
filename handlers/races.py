"""
Race-related handlers:
  - next race
  - full season calendar
  - single race details
  - finished race summaries
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone

from aiogram import Router
from aiogram.types import CallbackQuery

from bot_config.schedule import SCHEDULE_2026, SESSION_NAMES
from bot_config.track_history import TRACK_HISTORY
from database import Database
from keyboards import back_to_menu_kb, calendar_kb
from utils import format_dt, get_next_race, now_utc
from utils.api_client import ApiClient
from utils.openf1 import (
    build_pit_summary_lines,
    clean_session_label,
    load_race_insights,
    load_weekend_weather,
    summarize_race_control,
    summarize_weather,
)

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

PODIUM_ICONS = {1: "🥇", 2: "🥈", 3: "🥉"}


def is_race_finished(race: dict) -> bool:
    race_utc = race["sessions"]["race"].replace(tzinfo=timezone.utc)
    return now_utc() > race_utc


async def fetch_quali_result(api: ApiClient, round_num: int) -> dict | None:
    return await api.fetch_json(QUALI_RESULTS_URL.format(round=round_num), ttl=RESULTS_TTL)


async def fetch_race_result(api: ApiClient, round_num: int) -> dict | None:
    return await api.fetch_json(RACE_RESULTS_URL.format(round=round_num), ttl=RESULTS_TTL)


def _get_race(round_num: int) -> dict | None:
    return next((item for item in SCHEDULE_2026 if item["round"] == round_num), None)


def _race_menu_kb(round_num: int, *, finished: bool):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()

    if finished:
        builder.row(InlineKeyboardButton(text="🏁 Итоги гонки", callback_data=f"race_info_{round_num}"))
        builder.row(InlineKeyboardButton(text="📊 Подробности этапа", callback_data=f"openf1_card_{round_num}"))
        builder.row(InlineKeyboardButton(text="📚 История трассы", callback_data=f"track_history_{round_num}"))
    else:
        builder.row(InlineKeyboardButton(text="📺 Где смотреть", callback_data=f"watch_{round_num}"))
        builder.row(InlineKeyboardButton(text="📚 История трассы", callback_data=f"track_history_{round_num}"))

    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _subpage_kb(round_num: int):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀ Назад к этапу", callback_data=f"race_{round_num}"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


async def _replace_with_text(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    disable_web_page_preview: bool = False,
) -> None:
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        return

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


async def _show_race_page(
    callback: CallbackQuery,
    *,
    text: str,
    reply_markup,
    track_photo: str | None,
    round_num: int,
) -> None:
    if track_photo:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=track_photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return
        except Exception as exc:
            logger.warning(
                "Failed to send track photo for round %d: %s. Fallback to text.",
                round_num,
                exc,
            )

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)


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
        label_clean = clean_session_label(session_key)
        padding = " " * max(1, session_width - len(label_clean))
        lines.append(f"<code>{label_clean}{padding}{time_str}</code>")

    lines.append(f"\n<i>Часовой пояс: {timezone_name}</i>")
    return "\n".join(lines)


def _build_result_lines(race_data: dict, qualifying_data: dict | None) -> list[str]:
    results = race_data["MRData"]["RaceTable"]["Races"][0]["Results"]
    lines = ["<b>Подиум:</b>"]

    fastest_lap_driver = None
    fastest_lap_time = None

    for result in results:
        position = int(result.get("position", 99))
        driver = f"{result['Driver']['givenName']} {result['Driver']['familyName']}"
        team = result["Constructor"]["name"]
        status = result.get("status", "—")

        if position <= 3:
            icon = PODIUM_ICONS[position]
            time_value = result.get("Time", {}).get("time", status)
            lines.append(f"{icon} <b>{driver}</b> — {team}")
            lines.append(f"   {time_value}")

        fastest_lap = result.get("FastestLap", {})
        if fastest_lap.get("rank") == "1":
            fastest_lap_driver = driver
            fastest_lap_time = fastest_lap.get("Time", {}).get("time", "—")

    pole_driver = None
    pole_time = None
    if qualifying_data:
        try:
            qualifying_results = qualifying_data["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"]
            pole = next((item for item in qualifying_results if item["position"] == "1"), None)
            if pole:
                pole_driver = f"{pole['Driver']['givenName']} {pole['Driver']['familyName']}"
                pole_time = pole.get("Q3") or pole.get("Q2") or pole.get("Q1", "—")
        except (KeyError, IndexError):
            pass

    if pole_driver:
        lines.extend(["", f"⚡ <b>Поул:</b> {pole_driver} — {pole_time}"])

    if fastest_lap_driver and fastest_lap_time:
        lines.append(f"🔥 <b>Быстрый круг:</b> {fastest_lap_driver} — {fastest_lap_time}")

    return lines


def _build_track_history_text(race: dict) -> str:
    history = TRACK_HISTORY.get(race["round"])
    if not history:
        return (
            f"📚 <b>История трассы — {race['name']}</b>\n\n"
            "Для этой трассы историческая карточка пока не заполнена."
        )

    lines = [
        f"📚 <b>История трассы — {race['name']}</b>",
        f"<i>{race['circuit']} · {race['country']}</i>",
        "",
        str(history["summary"]),
        "",
        "<b>Коротко:</b>",
    ]
    lines.extend(f"• {fact}" for fact in history.get("facts", []))

    source = history.get("source")
    if source:
        lines.extend(["", f"<a href='{source}'>Официальный источник</a>"])
    return "\n".join(lines)


def _build_openf1_card_text(
    race: dict,
    race_data: dict,
    qualifying_data: dict | None,
    insights: dict,
    weekend_weather: dict[str, list[dict]],
) -> str:
    def wrap_block(block_lines: list[str]) -> str:
        content = "\n".join(line for line in block_lines if line is not None).strip()
        return f"<blockquote>{content}</blockquote>" if content else ""

    def build_podium_block() -> str:
        try:
            results = race_data["MRData"]["RaceTable"]["Races"][0]["Results"]
        except (KeyError, IndexError, TypeError):
            return ""

        rows: list[str] = []
        medal_map = {1: "🥇", 2: "🥈", 3: "🥉"}

        for result in results:
            try:
                position = int(result.get("position", 99))
            except (TypeError, ValueError):
                continue
            if position not in medal_map:
                continue

            driver = f"{result['Driver']['givenName']} {result['Driver']['familyName']}"
            team = result["Constructor"]["name"]
            time_value = result.get("Time", {}).get("time") or result.get("status", "—")
            rows.extend([f"{medal_map[position]} <b>{driver}</b>", team, time_value, ""])

        if rows and rows[-1] == "":
            rows.pop()
        return wrap_block(rows)

    def build_highlights_block() -> str:
        lines: list[str] = []

        pole_driver = None
        pole_time = None
        if qualifying_data:
            try:
                qualifying_results = qualifying_data["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"]
                pole = next((item for item in qualifying_results if item["position"] == "1"), None)
                if pole:
                    pole_driver = f"{pole['Driver']['givenName']} {pole['Driver']['familyName']}"
                    pole_time = pole.get("Q3") or pole.get("Q2") or pole.get("Q1", "—")
            except (KeyError, IndexError, TypeError):
                pass

        fastest_lap_driver = None
        fastest_lap_time = None
        try:
            results = race_data["MRData"]["RaceTable"]["Races"][0]["Results"]
        except (KeyError, IndexError, TypeError):
            results = []

        for result in results:
            fastest_lap = result.get("FastestLap", {})
            if fastest_lap.get("rank") == "1":
                fastest_lap_driver = (
                    f"{result['Driver']['givenName']} {result['Driver']['familyName']}"
                )
                fastest_lap_time = fastest_lap.get("Time", {}).get("time", "—")
                break

        if pole_driver:
            lines.append(f"⚡ <b>Поул</b>: {pole_driver}")
            lines.append(f"Время: {pole_time}")
        if fastest_lap_driver:
            if lines:
                lines.append("")
            lines.append(f"🔥 <b>Быстрый круг</b>: {fastest_lap_driver}")
            lines.append(f"Время: {fastest_lap_time}")

        return wrap_block(lines)

    def build_weather_block() -> str:
        rows: list[str] = []
        for session_key, weather_rows in weekend_weather.items():
            summary = summarize_weather(weather_rows)
            if summary is None:
                continue
            if rows:
                rows.append("")
            rows.append(f"<b>{clean_session_label(session_key)}</b>")
            rows.append(f"Воздух {summary['air']} • трасса {summary['track']}")
            rows.append(f"Влажность {summary['humidity']} • ветер до {summary['wind']}")
            rows.append("Дождь фиксировался" if summary["rain"] else "Сухо")
        return wrap_block(rows)

    def build_race_weather_block() -> str:
        summary = summarize_weather(insights.get("weather", []))
        if summary is None:
            return ""
        return wrap_block(
            [
                f"Воздух {summary['air']} • трасса {summary['track']}",
                f"Влажность {summary['humidity']} • ветер до {summary['wind']}",
                "Дождь фиксировался" if summary["rain"] else "Сухо",
            ]
        )

    def build_race_control_block() -> str:
        messages = insights.get("race_control", [])
        if not messages:
            return ""

        summary = summarize_race_control(messages)
        stats: list[str] = []
        if summary["safety_car"]:
            stats.append(f"SC: {summary['safety_car']}")
        if summary["virtual_safety_car"]:
            stats.append(f"VSC: {summary['virtual_safety_car']}")
        if summary["red_flags"]:
            stats.append(f"Красные флаги: {summary['red_flags']}")
        if summary["yellow_flags"]:
            stats.append(f"Жёлтые флаги: {summary['yellow_flags']}")
        if not stats:
            stats.append("Без SC/VSC и красных флагов")

        lines = [" • ".join(stats)]
        if summary["notes"]:
            lines.extend(["", "<b>Последнее заметное сообщение</b>", str(summary["notes"])])
        return wrap_block(lines)

    def build_pits_block() -> str:
        pit_lines = build_pit_summary_lines(insights.get("pit", []), insights.get("drivers", {}))
        if not pit_lines:
            return ""

        cleaned = [line.removeprefix("• ").strip() for line in pit_lines]
        formatted: list[str] = []
        for line in cleaned:
            parts = [part.strip() for part in line.split(" • ") if part.strip()]
            formatted.extend(parts)
        return wrap_block(formatted)

    def build_strategy_block() -> str:
        return ""

    lines = [
        f"📊 <b>Подробности этапа — {race['name']}</b>",
        f"<i>{race['circuit']} · {race['country']}</i>",
        "",
    ]

    podium_block = build_podium_block()
    if podium_block:
        lines.extend(["<b>Подиум</b>", podium_block])

    highlights_block = build_highlights_block()
    if highlights_block:
        lines.extend(["", "<b>Ключевые итоги</b>", highlights_block])

    weather_block = build_weather_block()
    if weather_block:
        lines.extend(["", "<b>Погода по сессиям</b>", weather_block])

    race_weather_block = build_race_weather_block()
    if race_weather_block:
        lines.extend(["", "<b>Погода в гонке</b>", race_weather_block])

    race_control_block = build_race_control_block()
    if race_control_block:
        lines.extend(["", "<b>Race Control</b>", race_control_block])

    pits_block = build_pits_block()
    if pits_block:
        lines.extend(["", "<b>Питы</b>", pits_block])

    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "next_race")
async def cb_next_race(callback: CallbackQuery, db: Database) -> None:
    user_id = callback.from_user.id
    timezone_name = db.get_user_timezone(user_id)
    race = get_next_race(SCHEDULE_2026)

    if race is None:
        text = "🏁 Сезон 2026 завершён!\n\nСледите за новостями о сезоне 2027 🏎"
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=back_to_menu_kb())
        else:
            await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()
        return

    remaining = sum(1 for item in SCHEDULE_2026 if item["sessions"]["race"] >= race["sessions"]["race"])
    text = (
        f"<b>Следующий Гран-при</b> · этап {race['round']} из {len(SCHEDULE_2026)}\n"
        f"<i>До конца сезона: {remaining} гонок</i>\n\n"
        f"{_build_race_detail(race, timezone_name)}"
    )
    kb = _race_menu_kb(race["round"], finished=is_race_finished(race))

    track_photo = TRACK_MAPS.get(race["round"])
    await _show_race_page(
        callback,
        text=text,
        reply_markup=kb,
        track_photo=track_photo,
        round_num=race["round"],
    )

    await callback.answer()


@router.callback_query(lambda c: c.data == "calendar")
async def cb_calendar(callback: CallbackQuery) -> None:
    text = "📅 <b>Календарь Формулы 1 — сезон 2026</b>\n\nВыберите этап:"
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=calendar_kb(SCHEDULE_2026))
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=calendar_kb(SCHEDULE_2026))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("race_") and c.data[5:].isdigit())
async def cb_race_detail(callback: CallbackQuery, db: Database) -> None:
    round_num = int(callback.data[5:])
    race = _get_race(round_num)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    timezone_name = db.get_user_timezone(callback.from_user.id)
    text = _build_race_detail(race, timezone_name)
    kb = _race_menu_kb(round_num, finished=is_race_finished(race))

    track_photo = TRACK_MAPS.get(round_num)
    await _show_race_page(
        callback,
        text=text,
        reply_markup=kb,
        track_photo=track_photo,
        round_num=round_num,
    )

    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("watch_"))
async def cb_where_to_watch(callback: CallbackQuery) -> None:
    try:
        round_num = int(callback.data.split("_", maxsplit=1)[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка")
        return

    race = _get_race(round_num)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    text = (
        f"📺 <b>Где смотреть — {race['name']}</b>\n"
        f"<i>{race['circuit']} · {race['country']}</i>\n\n"
        "Подборка русскоязычных трансляций:\n\n"
        f"• Алексей Попов / Наталья Фабричная — <a href='{WATCH_LINKS['popov']}'>ссылка</a>\n"
        f"• Станиславский — <a href='{WATCH_LINKS['stanislavsky']}'>ссылка</a>\n"
        f"• Simply Formula (Роман) — <a href='{WATCH_LINKS['simply']}'>ссылка</a>"
    )

    await _replace_with_text(
        callback,
        text,
        reply_markup=_subpage_kb(round_num),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("track_history_"))
async def cb_track_history(callback: CallbackQuery) -> None:
    try:
        round_num = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return

    race = _get_race(round_num)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    await _replace_with_text(
        callback,
        _build_track_history_text(race),
        reply_markup=_subpage_kb(round_num),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("race_info_"))
async def cb_race_info(callback: CallbackQuery, api: ApiClient) -> None:
    try:
        round_num = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return

    race = _get_race(round_num)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    await callback.answer("⏳ Собираю итоги гонки...")

    race_data, qualifying_data = await asyncio.gather(
        fetch_race_result(api, round_num),
        fetch_quali_result(api, round_num),
    )

    if race_data is None:
        await _replace_with_text(
            callback,
            (
                f"🏁 <b>Итоги гонки — {race['name']}</b>\n"
                f"<i>{race['circuit']} · {race['country']}</i>\n\n"
                "Результаты пока недоступны.\n"
                "Либо они ещё не опубликованы, либо сервис статистики временно не отвечает."
            ),
            reply_markup=_subpage_kb(round_num),
        )
        return

    try:
        _ = race_data["MRData"]["RaceTable"]["Races"][0]["Results"]
    except (KeyError, IndexError):
        await _replace_with_text(
            callback,
            (
                f"🏁 <b>Итоги гонки — {race['name']}</b>\n"
                f"<i>{race['circuit']} · {race['country']}</i>\n\n"
                "Результаты ещё не опубликованы.\n"
                "Обычно они появляются спустя некоторое время после финиша."
            ),
            reply_markup=_subpage_kb(round_num),
        )
        return

    lines = [
        f"🏁 <b>Итоги гонки — {race['name']}</b>",
        f"<i>{race['circuit']} · {race['country']}</i>",
        "",
    ]
    lines.extend(_build_result_lines(race_data, qualifying_data))
    await _replace_with_text(callback, "\n".join(lines), reply_markup=_subpage_kb(round_num))
    logger.info("Race results viewed for round %d", round_num)


@router.callback_query(lambda c: c.data.startswith("openf1_card_"))
async def cb_openf1_card(callback: CallbackQuery, api: ApiClient) -> None:
    try:
        round_num = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return

    race = _get_race(round_num)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    await callback.answer("⏳ Собираю подробности этапа...")

    race_data, qualifying_data, insights, weekend_weather = await asyncio.gather(
        fetch_race_result(api, round_num),
        fetch_quali_result(api, round_num),
        load_race_insights(api, race),
        load_weekend_weather(api, race),
    )

    try:
        race_results = race_data["MRData"]["RaceTable"]["Races"][0]["Results"] if race_data else []
    except (KeyError, IndexError, TypeError):
        race_results = []

    if not race_results or insights is None or not insights.get("session_result"):
        await _replace_with_text(
            callback,
            (
                f"📊 <b>Подробности этапа — {race['name']}</b>\n"
                f"<i>{race['circuit']} · {race['country']}</i>\n\n"
                "Подробные данные по этапу пока не готовы.\n"
                "Обычно они появляются чуть позже официальных результатов."
            ),
            reply_markup=_subpage_kb(round_num),
        )
        return

    await _replace_with_text(
        callback,
        _build_openf1_card_text(race, race_data, qualifying_data, insights, weekend_weather),
        reply_markup=_subpage_kb(round_num),
    )
