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

DRIVERS_LIST_TTL = 6 * 3600
DRIVER_SEASON_TTL = 10 * 60
DRIVER_CAREER_TTL = 6 * 3600
PROFILE_CACHE_TTL = 5 * 60

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


async def _get(api: ApiClient, url: str, *, ttl: int = DRIVERS_LIST_TTL) -> dict | None:
    return await api.fetch_json(url, ttl=ttl)


def _drivers_kb(drivers: list[dict]):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for driver in drivers:
        flag = NATIONALITY_FLAGS.get(driver.get("nationality", ""), "")
        name = f"{driver['givenName']} {driver['familyName']}"
        builder.button(text=f"{flag} {name}", callback_data=f"driver_{driver['driverId']}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _driver_back_kb():
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ К списку пилотов", callback_data="drivers_list"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


@router.callback_query(lambda c: c.data == "drivers_list")
async def cb_drivers_list(callback: CallbackQuery, api: ApiClient) -> None:
    await callback.answer("⏳ Загружаю...")
    data = await _get(api, DRIVERS_2026_URL, ttl=DRIVERS_LIST_TTL)

    if not data:
        text = "❌ Не удалось загрузить список пилотов."
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=_driver_back_kb())
        else:
            await callback.message.edit_text(text, reply_markup=_driver_back_kb())
        return

    try:
        drivers = data["MRData"]["DriverTable"]["Drivers"]
    except (KeyError, IndexError):
        text = "❌ Ошибка данных."
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text)
        else:
            await callback.message.edit_text(text)
        return

    text = "🏎 <b>Пилоты сезона 2026</b>\n\nВыберите пилота:"
    kb = _drivers_kb(drivers)

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data.startswith("driver_"))
async def cb_driver_profile(callback: CallbackQuery, api: ApiClient) -> None:
    driver_id = callback.data[7:]
    await callback.answer("⏳ Загружаю профиль...")

    cached = _profile_cache.get(driver_id)
    now = time.monotonic()
    if cached and now - cached[0] < PROFILE_CACHE_TTL:
        text, photo_id = cached[1]
        await _send_driver_profile(callback, text, photo_id)
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
            driver_info = next(
                (driver for driver in all_drivers if driver["driverId"] == driver_id),
                None,
            )
        except (KeyError, IndexError):
            driver_info = None

    if not driver_info:
        await callback.message.edit_text("❌ Пилот не найден.", reply_markup=_driver_back_kb())
        return

    text, photo_id = _build_driver_profile_text(
        driver_id,
        driver_info,
        season_data,
        wins_data,
        poles_data,
    )
    _profile_cache[driver_id] = (now, (text, photo_id))
    await _send_driver_profile(callback, text, photo_id)
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
    logger.info("driver_id=%s, bio=%s, photo=%s", driver_id, bool(bio), bio.get("photo") if bio else None)
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


async def _send_driver_profile(
    callback: CallbackQuery,
    text: str,
    photo_id: str | None,
) -> None:
    if photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=_driver_back_kb(),
        )
        return

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_driver_back_kb(),
    )
