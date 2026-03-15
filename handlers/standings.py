"""
Обработчик таблицы очков пилотов и конструкторов.
Данные берутся с бесплатного API: api.jolpi.ca (Jolpica F1)
Обновляется каждый понедельник после гонки.
"""

import logging
import aiohttp
import asyncio
from aiogram import Router
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)

router = Router(name="standings")

# URL для очков пилотов и конструкторов
DRIVER_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/2026/driverstandings.json"
CONSTRUCTOR_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/2026/constructorstandings.json"

# Медали для топ-3
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# Флаги национальностей пилотов
NATIONALITY_FLAGS = {
    "British":     "🇬🇧",
    "Dutch":       "🇳🇱",
    "Monegasque":  "🇲🇨",
    "Australian":  "🇦🇺",
    "Spanish":     "🇪🇸",
    "Mexican":     "🇲🇽",
    "Canadian":    "🇨🇦",
    "Finnish":     "🇫🇮",
    "French":      "🇫🇷",
    "German":      "🇩🇪",
    "Italian":     "🇮🇹",
    "Japanese":    "🇯🇵",
    "Danish":      "🇩🇰",
    "Thai":        "🇹🇭",
    "American":    "🇺🇸",
    "Chinese":     "🇨🇳",
    "New Zealander": "🇳🇿",
    "Argentine":   "🇦🇷",
    "Brazilian":   "🇧🇷",
}


async def fetch_standings(url: str) -> dict | None:
    """Делает GET-запрос к Jolpica API и возвращает JSON."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("API вернул статус %d для %s", resp.status, url)
                return None
    except asyncio.TimeoutError:
        logger.error("Таймаут запроса к API: %s", url)
        return None
    except Exception as exc:
        logger.error("Ошибка запроса к API: %s", exc)
        return None


def parse_driver_standings(data: dict) -> list[dict]:
    """Парсит ответ API в список словарей с данными пилотов."""
    try:
        standings_list = (
            data["MRData"]["StandingsTable"]
            ["StandingsLists"][0]["DriverStandings"]
        )
        result = []
        for entry in standings_list:
            result.append({
                "position": int(entry["position"]),
                "points":   entry["points"],
                "wins":     entry["wins"],
                "name":     f"{entry['Driver']['givenName']} {entry['Driver']['familyName']}",
                "nationality": entry["Driver"].get("nationality", ""),
                "team":     entry["Constructors"][0]["name"] if entry["Constructors"] else "—",
            })
        return result
    except (KeyError, IndexError) as exc:
        logger.error("Ошибка парсинга очков пилотов: %s", exc)
        return []


def parse_constructor_standings(data: dict) -> list[dict]:
    """Парсит ответ API в список словарей с данными команд."""
    try:
        standings_list = (
            data["MRData"]["StandingsTable"]
            ["StandingsLists"][0]["ConstructorStandings"]
        )
        result = []
        for entry in standings_list:
            result.append({
                "position": int(entry["position"]),
                "points":   entry["points"],
                "wins":     entry["wins"],
                "name":     entry["Constructor"]["name"],
            })
        return result
    except (KeyError, IndexError) as exc:
        logger.error("Ошибка парсинга очков конструкторов: %s", exc)
        return []


def format_driver_standings(standings: list[dict], after_round: int) -> str:
    """Форматирует таблицу очков пилотов для отображения в боте."""
    if not standings:
        return "❌ Данные недоступны. Попробуй позже."

    lines = [
        f"🏆 <b>Личный зачёт — Сезон 2026</b>",
        f"<i>После этапа {after_round}</i>\n",
    ]

    for d in standings:
        pos = d["position"]
        medal = MEDALS.get(pos, f"{pos}.")
        flag = NATIONALITY_FLAGS.get(d["nationality"], "🏳️")
        wins = f" ({d['wins']} побед)" if int(d["wins"]) > 0 else ""
        lines.append(
            f"{medal} {flag} <b>{d['name']}</b>\n"
            f"    {d['points']} очков{wins} — {d['team']}"
        )

    return "\n".join(lines)


def format_constructor_standings(standings: list[dict], after_round: int) -> str:
    """Форматирует таблицу очков конструкторов."""
    if not standings:
        return "❌ Данные недоступны. Попробуй позже."

    lines = [
        f"🏗 <b>Кубок конструкторов — Сезон 2026</b>",
        f"<i>После этапа {after_round}</i>\n",
    ]

    team_icons = {
        "McLaren":       "🟠",
        "Ferrari":       "🔴",
        "Red Bull":      "🔵",
        "Mercedes":      "⚫",
        "Aston Martin":  "🟢",
        "Alpine":        "💙",
        "Williams":      "🔷",
        "Racing Bulls":  "🟤",
        "Haas":          "⬜",
        "Audi":          "⚪",
        "Cadillac":      "🇺🇸",
    }

    for c in standings:
        pos = c["position"]
        medal = MEDALS.get(pos, f"{pos}.")
        icon = next((v for k, v in team_icons.items() if k in c["name"]), "🏎")
        wins = f" ({c['wins']} побед)" if int(c["wins"]) > 0 else ""
        lines.append(
            f"{medal} {icon} <b>{c['name']}</b>\n"
            f"    {c['points']} очков{wins}"
        )

    return "\n".join(lines)


# ── Обработчики callback ───────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "driver_standings")
async def cb_driver_standings(callback: CallbackQuery) -> None:
    """Показывает таблицу очков пилотов."""
    await callback.answer("⏳ Загружаю данные...")

    data = await fetch_standings(DRIVER_STANDINGS_URL)

    if data is None:
        await callback.message.edit_text(
            "❌ Не удалось получить данные с сервера.\n"
            "API Jolpica временно недоступен, попробуй через несколько минут.",
            reply_markup=_standings_back_kb(),
        )
        return

    standings = parse_driver_standings(data)

    # Определяем номер последнего этапа из ответа API
    try:
        after_round = int(
            data["MRData"]["StandingsTable"]["StandingsLists"][0]["round"]
        )
    except (KeyError, IndexError, ValueError):
        after_round = "?"

    text = format_driver_standings(standings, after_round)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_standings_back_kb(),
    )


@router.callback_query(lambda c: c.data == "constructor_standings")
async def cb_constructor_standings(callback: CallbackQuery) -> None:
    """Показывает таблицу очков конструкторов."""
    await callback.answer("⏳ Загружаю данные...")

    data = await fetch_standings(CONSTRUCTOR_STANDINGS_URL)

    if data is None:
        await callback.message.edit_text(
            "❌ Не удалось получить данные с сервера.\n"
            "API Jolpica временно недоступен, попробуй через несколько минут.",
            reply_markup=_standings_back_kb(),
        )
        return

    standings = parse_constructor_standings(data)

    try:
        after_round = int(
            data["MRData"]["StandingsTable"]["StandingsLists"][0]["round"]
        )
    except (KeyError, IndexError, ValueError):
        after_round = "?"

    text = format_constructor_standings(standings, after_round)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_standings_back_kb(),
    )


def _standings_back_kb():
    """Клавиатура под таблицей очков: переключение + назад."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Личный зачёт",   callback_data="driver_standings"),
        InlineKeyboardButton(text="🏗 Конструкторы",    callback_data="constructor_standings"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В главное меню",  callback_data="main_menu"),
    )
    return builder.as_markup()


@router.callback_query(lambda c: c.data == "standings_menu")
async def cb_standings_menu(callback: CallbackQuery) -> None:
    """Показывает меню выбора таблицы очков."""
    from keyboards import standings_menu_kb
    await callback.message.edit_text(
        "🏆 <b>Таблица очков — Сезон 2026</b>\n\nВыберите зачёт:",
        parse_mode="HTML",
        reply_markup=standings_menu_kb(),
    )
    await callback.answer()