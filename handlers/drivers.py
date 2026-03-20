"""
Drivers list and profile handlers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date

from aiogram import Router
from aiogram.types import CallbackQuery

from utils.api_client import ApiClient

from .driver_bios import DRIVER_BIOS

logger = logging.getLogger(__name__)
router = Router(name="drivers")

DRIVERS_2026_URL = "https://api.jolpi.ca/ergast/f1/2026/drivers.json"
DRIVER_SEASON_URL = "https://api.jolpi.ca/ergast/f1/2026/drivers/{driver_id}/driverstandings.json"
DRIVER_WINS_URL = "https://api.jolpi.ca/ergast/f1/drivers/{driver_id}/results/1.json?limit=1000"
DRIVER_POLES_URL = "https://api.jolpi.ca/ergast/f1/drivers/{driver_id}/qualifying/1.json?limit=1000"
DRIVER_RESULTS_BY_YEAR_URL = "https://api.jolpi.ca/ergast/f1/{year}/drivers/{driver_id}/results.json?limit=100"
DRIVER_QUALIFYING_BY_YEAR_URL = "https://api.jolpi.ca/ergast/f1/{year}/drivers/{driver_id}/qualifying.json?limit=100"

DRIVERS_LIST_TTL = 6 * 3600
DRIVER_SEASON_TTL = 10 * 60
DRIVER_CAREER_TTL = 6 * 3600
PROFILE_CACHE_TTL = 5 * 60
HISTORY_CACHE_TTL = 30 * 60
HISTORY_YEARS = (2023, 2024, 2025, 2026)

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

_profile_cache: dict[str, tuple[float, tuple[str, str | None]]] = {}
_history_cache: dict[str, tuple[float, str]] = {}


async def _get(api: ApiClient, url: str, *, ttl: int = DRIVERS_LIST_TTL) -> dict | None:
    payload = await api.fetch_json(url, ttl=ttl)
    return payload if isinstance(payload, dict) else None


def _drivers_kb(drivers: list[dict]):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for driver in drivers:
        flag = NATIONALITY_FLAGS.get(driver.get("nationality", ""), "")
        name = f"{driver['givenName']} {driver['familyName']}"
        builder.button(text=f"{flag} {name}".strip(), callback_data=f"driver_{driver['driverId']}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _driver_profile_kb(driver_id: str):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📈 Статистика с 2023", callback_data=f"history_driver_{driver_id}"))
    builder.row(InlineKeyboardButton(text="◀ К списку пилотов", callback_data="drivers_list"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _driver_history_kb(driver_id: str):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀ К профилю пилота", callback_data=f"driver_{driver_id}"))
    builder.row(InlineKeyboardButton(text="◀ К списку пилотов", callback_data="drivers_list"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _driver_back_kb():
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀ К списку пилотов", callback_data="drivers_list"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


@router.callback_query(lambda c: c.data == "drivers_list")
async def cb_drivers_list(callback: CallbackQuery, api: ApiClient) -> None:
    await callback.answer("⏳ Загружаю...")
    data = await _get(api, DRIVERS_2026_URL, ttl=DRIVERS_LIST_TTL)

    if not data:
        text = "Не удалось загрузить список пилотов.\nПопробуйте ещё раз чуть позже."
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=_driver_back_kb())
        else:
            await callback.message.edit_text(text, reply_markup=_driver_back_kb())
        return

    try:
        drivers = data["MRData"]["DriverTable"]["Drivers"]
    except (KeyError, IndexError):
        text = "Не удалось прочитать данные о пилотах."
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text)
        else:
            await callback.message.edit_text(text)
        return

    text = "🏁 <b>Пилоты сезона 2026</b>\n\nВыберите пилота:"
    kb = _drivers_kb(drivers)

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data.startswith("history_driver_"))
async def cb_driver_history(callback: CallbackQuery, api: ApiClient) -> None:
    driver_id = callback.data.removeprefix("history_driver_")
    await callback.answer("⏳ Собираю историю...")

    now = time.monotonic()
    cached = _history_cache.get(driver_id)
    if cached and now - cached[0] < HISTORY_CACHE_TTL:
        await _replace_driver_text(callback, cached[1], _driver_history_kb(driver_id))
        return

    tasks = [
        _get(api, DRIVERS_2026_URL, ttl=DRIVERS_LIST_TTL),
        *(
            _get(api, DRIVER_RESULTS_BY_YEAR_URL.format(year=year, driver_id=driver_id), ttl=HISTORY_CACHE_TTL)
            for year in HISTORY_YEARS
        ),
        *(
            _get(api, DRIVER_QUALIFYING_BY_YEAR_URL.format(year=year, driver_id=driver_id), ttl=HISTORY_CACHE_TTL)
            for year in HISTORY_YEARS
        ),
    ]
    responses = await asyncio.gather(*tasks)

    all_drivers_data = responses[0]
    results_payloads = responses[1 : 1 + len(HISTORY_YEARS)]
    qualifying_payloads = responses[1 + len(HISTORY_YEARS) :]

    driver_info = None
    if all_drivers_data:
        try:
            all_drivers = all_drivers_data["MRData"]["DriverTable"]["Drivers"]
            driver_info = next((driver for driver in all_drivers if driver["driverId"] == driver_id), None)
        except (KeyError, IndexError):
            driver_info = None

    if driver_info is None:
        await _replace_driver_text(callback, "Пилот не найден.", _driver_back_kb())
        return

    text = _build_driver_history_text(driver_info, results_payloads, qualifying_payloads)
    _history_cache[driver_id] = (now, text)
    await _replace_driver_text(callback, text, _driver_history_kb(driver_id))


@router.callback_query(
    lambda c: c.data.startswith("driver_") and c.data != "driver_standings"
)
async def cb_driver_profile(callback: CallbackQuery, api: ApiClient) -> None:
    driver_id = callback.data[7:]
    await callback.answer("⏳ Загружаю профиль...")

    cached = _profile_cache.get(driver_id)
    now = time.monotonic()
    if cached and now - cached[0] < PROFILE_CACHE_TTL:
        text, photo_id = cached[1]
        await _send_driver_profile(callback, driver_id, text, photo_id)
        return

    season_data, wins_data, poles_data, all_drivers_data = await asyncio.gather(
        _get(api, DRIVER_SEASON_URL.format(driver_id=driver_id), ttl=DRIVER_SEASON_TTL),
        _get(api, DRIVER_WINS_URL.format(driver_id=driver_id), ttl=DRIVER_CAREER_TTL),
        _get(api, DRIVER_POLES_URL.format(driver_id=driver_id), ttl=DRIVER_CAREER_TTL),
        _get(api, DRIVERS_2026_URL, ttl=DRIVERS_LIST_TTL),
    )

    driver_info = None
    if all_drivers_data:
        try:
            all_drivers = all_drivers_data["MRData"]["DriverTable"]["Drivers"]
            driver_info = next((driver for driver in all_drivers if driver["driverId"] == driver_id), None)
        except (KeyError, IndexError):
            driver_info = None

    if not driver_info:
        await _replace_driver_text(callback, "Пилот не найден.", _driver_back_kb())
        return

    text, photo_id = _build_driver_profile_text(
        driver_id,
        driver_info,
        season_data,
        wins_data,
        poles_data,
    )
    _profile_cache[driver_id] = (now, (text, photo_id))
    await _send_driver_profile(callback, driver_id, text, photo_id)
    logger.info("Driver profile viewed: %s", driver_id)


def _build_driver_profile_text(
    driver_id: str,
    driver_info: dict,
    season_data: dict | None,
    wins_data: dict | None,
    poles_data: dict | None,
) -> tuple[str, str | None]:
    flag = NATIONALITY_FLAGS.get(driver_info.get("nationality", ""), "")
    name = f"{driver_info['givenName']} {driver_info['familyName']}"
    number = driver_info.get("permanentNumber", "—")
    dob = driver_info.get("dateOfBirth", "—")
    nationality = driver_info.get("nationality", "—")

    age = "—"
    if dob and dob != "—":
        try:
            birth = date.fromisoformat(dob)
            today = date.today()
            age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        except ValueError:
            pass

    team = "—"
    position = "—"
    points = "—"
    season_wins = "0"
    if season_data:
        try:
            standings_lists = season_data["MRData"]["StandingsTable"]["StandingsLists"]
            if standings_lists:
                standing = standings_lists[0]["DriverStandings"][0]
                position = standing["position"]
                points = standing["points"]
                season_wins = standing["wins"]
                team = standing["Constructors"][0]["name"] if standing["Constructors"] else "—"
        except (KeyError, IndexError):
            pass

    career_wins = 0
    if wins_data:
        try:
            career_wins = int(wins_data["MRData"]["total"])
        except (KeyError, ValueError):
            pass

    career_poles = 0
    if poles_data:
        try:
            career_poles = int(poles_data["MRData"]["total"])
        except (KeyError, ValueError):
            pass

    lines = [
        f"{flag} <b>{name}</b>  #{number}",
        f"{nationality} · {age} лет · {dob}",
        "",
        f"<b>Сезон 2026:</b> {team}",
        f"Позиция: {position} · Очки: {points} · Победы: {season_wins}",
        "",
        f"<b>Карьера:</b> {career_wins} побед · {career_poles} поулов",
    ]

    bio = DRIVER_BIOS.get(driver_id)
    if bio:
        lines.extend(
            [
                "",
                f"<b>Стиль вождения:</b> {bio['style']}",
                "",
                f"<b>Репутация:</b> {bio['reputation']}",
                "",
                f"💡 <b>Факт:</b> {bio['fact']}",
            ]
        )

    return "\n".join(lines), bio.get("photo") if bio else None


def _build_driver_history_text(
    driver_info: dict,
    results_payloads: list[dict | None],
    qualifying_payloads: list[dict | None],
) -> str:
    flag = NATIONALITY_FLAGS.get(driver_info.get("nationality", ""), "")
    name = f"{driver_info['givenName']} {driver_info['familyName']}"

    total_starts = 0
    total_wins = 0
    total_podiums = 0
    total_poles = 0
    total_points = 0.0
    last_finishes: list[tuple[int, int, str, str]] = []
    circuit_success: dict[str, dict[str, int]] = {}
    season_blocks: list[list[str]] = []

    for year, results_data, qualifying_data in zip(HISTORY_YEARS, results_payloads, qualifying_payloads):
        race_results = _extract_race_results(results_data)
        qualifying_results = _extract_qualifying_results(qualifying_data)

        starts = len(race_results)
        wins = sum(1 for item in race_results if item.get("position") == "1")
        podiums = sum(1 for item in race_results if item.get("position") in {"1", "2", "3"})
        points = sum(float(item.get("points", 0) or 0) for item in race_results)
        best_finish = min((int(item["position"]) for item in race_results if item.get("position")), default=None)
        poles = sum(1 for item in qualifying_results if item.get("position") == "1")

        if starts:
            total_starts += starts
            total_wins += wins
            total_podiums += podiums
            total_poles += poles
            total_points += points

            best_text = f"P{best_finish}" if best_finish is not None else "—"
            season_blocks.append(
                [
                    f"<b>{year}</b>",
                    f"• Старты: {starts} · Очки: {points:.0f}",
                    f"• Победы: {wins} · Подиумы: {podiums} · Поулы: {poles}",
                    f"• Лучший финиш: {best_text}",
                ]
            )

            for item in race_results:
                round_number = int(item.get("round", 0) or 0)
                race_name = item.get("raceName", "Гран-при")
                position = item.get("position", "—")
                last_finishes.append((year, round_number, race_name, position))

                circuit_stats = circuit_success.setdefault(race_name, {"wins": 0, "podiums": 0})
                if position == "1":
                    circuit_stats["wins"] += 1
                if position in {"1", "2", "3"}:
                    circuit_stats["podiums"] += 1

    lines = [
        f"📈 {flag} <b>Статистика с 2023 — {name}</b>",
        "",
    ]

    if not season_blocks:
        lines.append("Данные по гонкам с 2023 года пока не найдены.")
        return "\n".join(lines)

    lines.append("<b>По сезонам:</b>")
    for block in season_blocks:
        lines.extend(block)
        lines.append("")

    lines.extend(
        [
            "<b>Итого с 2023:</b>",
            f"• Старты: {total_starts} · Очки: {total_points:.0f}",
            f"• Победы: {total_wins} · Подиумы: {total_podiums} · Поулы: {total_poles}",
        ]
    )

    recent = sorted(last_finishes, key=lambda item: (item[0], item[1]), reverse=True)[:5]
    if recent:
        lines.extend(["", "<b>Последние финиши:</b>"])
        for _, _, race_name, position in recent:
            lines.append(f"• {_compact_race_name(race_name)} — P{position}")

    best_tracks = _build_best_tracks_lines(circuit_success)
    if best_tracks:
        lines.extend(["", "<b>Лучшие трассы по данным с 2023:</b>"])
        lines.extend(best_tracks)

    return "\n".join(lines)


def _build_best_tracks_lines(circuit_success: dict[str, dict[str, int]]) -> list[str]:
    if not circuit_success:
        return []

    wins_rank = sorted(
        ((name, stats["wins"]) for name, stats in circuit_success.items() if stats["wins"] > 0),
        key=lambda item: (-item[1], item[0]),
    )
    if wins_rank:
        top = wins_rank[:3]
        return [f"• {_compact_race_name(name)} — {wins} побед" for name, wins in top]

    podium_rank = sorted(
        ((name, stats["podiums"]) for name, stats in circuit_success.items() if stats["podiums"] > 0),
        key=lambda item: (-item[1], item[0]),
    )
    top = podium_rank[:3]
    return [f"• {_compact_race_name(name)} — {podiums} подиума" for name, podiums in top]


def _compact_race_name(name: str) -> str:
    compact = name.replace("Grand Prix", "GP").replace("City GP", "GP")
    compact = " ".join(compact.split())
    return compact


def _extract_race_results(data: dict | None) -> list[dict]:
    try:
        races = data["MRData"]["RaceTable"]["Races"]
    except (KeyError, TypeError):
        return []

    items: list[dict] = []
    for race in races:
        results = race.get("Results") or []
        if not results:
            continue
        item = dict(results[0])
        item["raceName"] = race.get("raceName", "Гран-при")
        item["round"] = race.get("round")
        items.append(item)
    return items


def _extract_qualifying_results(data: dict | None) -> list[dict]:
    try:
        races = data["MRData"]["RaceTable"]["Races"]
    except (KeyError, TypeError):
        return []

    items: list[dict] = []
    for race in races:
        results = race.get("QualifyingResults") or []
        if not results:
            continue
        item = dict(results[0])
        item["raceName"] = race.get("raceName", "Гран-при")
        item["round"] = race.get("round")
        items.append(item)
    return items


async def _replace_driver_text(callback: CallbackQuery, text: str, reply_markup) -> None:
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        return

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)


async def _send_driver_profile(
    callback: CallbackQuery,
    driver_id: str,
    text: str,
    photo_id: str | None,
) -> None:
    if photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=_driver_profile_kb(driver_id),
        )
        return

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_driver_profile_kb(driver_id),
    )
