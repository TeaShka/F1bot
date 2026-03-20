"""
Standings handlers for drivers and constructors.
"""

import logging

from aiogram import Router
from aiogram.types import CallbackQuery

from utils.api_client import ApiClient

logger = logging.getLogger(__name__)
router = Router(name="standings")

DRIVER_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/2026/driverstandings.json"
CONSTRUCTOR_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/2026/constructorstandings.json"
STANDINGS_TTL = 300

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

NATIONALITY_FLAGS = {
    "British": "🇬🇧",
    "Dutch": "🇳🇱",
    "Monegasque": "🇲🇨",
    "Australian": "🇦🇺",
    "Spanish": "🇪🇸",
    "Mexican": "🇲🇽",
    "Canadian": "🇨🇦",
    "Finnish": "🇫🇮",
    "French": "🇫🇷",
    "German": "🇩🇪",
    "Italian": "🇮🇹",
    "Japanese": "🇯🇵",
    "Danish": "🇩🇰",
    "Thai": "🇹🇭",
    "American": "🇺🇸",
    "Chinese": "🇨🇳",
    "New Zealander": "🇳🇿",
    "Argentine": "🇦🇷",
    "Brazilian": "🇧🇷",
}


async def fetch_standings(api: ApiClient, url: str) -> dict | None:
    return await api.fetch_json(url, ttl=STANDINGS_TTL)


def parse_driver_standings(data: dict) -> list[dict]:
    try:
        standings_list = (
            data["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
        )
        result = []
        for entry in standings_list:
            result.append(
                {
                    "position": int(entry["position"]),
                    "points": entry["points"],
                    "wins": entry["wins"],
                    "name": f"{entry['Driver']['givenName']} {entry['Driver']['familyName']}",
                    "nationality": entry["Driver"].get("nationality", ""),
                    "team": entry["Constructors"][0]["name"] if entry["Constructors"] else "—",
                }
            )
        return result
    except (KeyError, IndexError) as exc:
        logger.error("Driver standings parsing failed: %s", exc)
        return []


def parse_constructor_standings(data: dict) -> list[dict]:
    try:
        standings_list = (
            data["MRData"]["StandingsTable"]["StandingsLists"][0]["ConstructorStandings"]
        )
        result = []
        for entry in standings_list:
            result.append(
                {
                    "position": int(entry["position"]),
                    "points": entry["points"],
                    "wins": entry["wins"],
                    "name": entry["Constructor"]["name"],
                }
            )
        return result
    except (KeyError, IndexError) as exc:
        logger.error("Constructor standings parsing failed: %s", exc)
        return []


def format_driver_standings(standings: list[dict], after_round: int) -> str:
    if not standings:
        return "❌ Данные недоступны. Попробуй позже."

    lines = [
        "<b>Личный зачёт — Сезон 2026</b>",
        f"<i>После этапа {after_round}</i>",
        "",
    ]

    for driver in standings:
        position = driver["position"]
        medal = MEDALS.get(position, f"{position}.")
        flag = NATIONALITY_FLAGS.get(driver["nationality"], "")
        wins = f" · {driver['wins']} побед" if int(driver["wins"]) > 0 else ""
        team_short = (
            driver["team"]
            .replace(" F1 Team", "")
            .replace(" Racing", "")
            .replace("Scuderia ", "")
        )
        lines.append(
            f"{medal} {flag} <b>{driver['name']}</b>"
            f"  <i>{team_short}</i>"
            f"  {driver['points']} оч.{wins}"
        )

    return "\n".join(lines)


def format_constructor_standings(standings: list[dict], after_round: int) -> str:
    if not standings:
        return "❌ Данные недоступны. Попробуй позже."

    lines = [
        "<b>Кубок конструкторов — Сезон 2026</b>",
        f"<i>После этапа {after_round}</i>",
        "",
    ]

    for constructor in standings:
        position = constructor["position"]
        medal = MEDALS.get(position, f"{position}.")
        wins = f" · {constructor['wins']} побед" if int(constructor["wins"]) > 0 else ""
        name_short = (
            constructor["name"]
            .replace(" F1 Team", "")
            .replace(" Racing", "")
            .replace("Scuderia ", "")
        )
        lines.append(f"{medal} <b>{name_short}</b>  {constructor['points']} оч.{wins}")

    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "driver_standings")
async def cb_driver_standings(callback: CallbackQuery, api: ApiClient) -> None:
    await callback.answer("⏳ Загружаю данные...")

    data = await fetch_standings(api, DRIVER_STANDINGS_URL)
    if data is None:
        await callback.message.edit_text(
            "❌ Не удалось получить данные с сервера.\n"
            "API Jolpica временно недоступен, попробуй через несколько минут.",
            reply_markup=_standings_back_kb(),
        )
        return

    standings = parse_driver_standings(data)
    try:
        after_round = int(data["MRData"]["StandingsTable"]["StandingsLists"][0]["round"])
    except (KeyError, IndexError, ValueError):
        after_round = "?"

    await callback.message.edit_text(
        format_driver_standings(standings, after_round),
        parse_mode="HTML",
        reply_markup=_standings_back_kb(),
    )


@router.callback_query(lambda c: c.data == "constructor_standings")
async def cb_constructor_standings(callback: CallbackQuery, api: ApiClient) -> None:
    await callback.answer("⏳ Загружаю данные...")

    data = await fetch_standings(api, CONSTRUCTOR_STANDINGS_URL)
    if data is None:
        await callback.message.edit_text(
            "❌ Не удалось получить данные с сервера.\n"
            "API Jolpica временно недоступен, попробуй через несколько минут.",
            reply_markup=_standings_back_kb(),
        )
        return

    standings = parse_constructor_standings(data)
    try:
        after_round = int(data["MRData"]["StandingsTable"]["StandingsLists"][0]["round"])
    except (KeyError, IndexError, ValueError):
        after_round = "?"

    await callback.message.edit_text(
        format_constructor_standings(standings, after_round),
        parse_mode="HTML",
        reply_markup=_standings_back_kb(),
    )


def _standings_back_kb():
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Личный зачёт", callback_data="driver_standings"),
        InlineKeyboardButton(text="🏗 Конструкторы", callback_data="constructor_standings"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()


@router.callback_query(lambda c: c.data == "standings_menu")
async def cb_standings_menu(callback: CallbackQuery) -> None:
    from keyboards import standings_menu_kb

    await callback.message.edit_text(
        "🏆 <b>Таблица очков — Сезон 2026</b>\n\nВыберите зачёт:",
        parse_mode="HTML",
        reply_markup=standings_menu_kb(),
    )
    await callback.answer()
