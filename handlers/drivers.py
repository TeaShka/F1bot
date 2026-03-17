"""
Обработчик списка пилотов и профилей.
- Базовые данные: Jolpica API
- Характеристика стиля вождения и факты: Claude AI
"""

import logging
import asyncio
from utils.cache import fetch_with_cache
from aiogram import Router
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)
router = Router(name="drivers")

# API endpoints
DRIVERS_2026_URL   = "https://api.jolpi.ca/ergast/f1/2026/drivers.json"
DRIVER_SEASON_URL  = "https://api.jolpi.ca/ergast/f1/2026/drivers/{driver_id}/driverstandings.json"
DRIVER_WINS_URL    = "https://api.jolpi.ca/ergast/f1/drivers/{driver_id}/results/1.json?limit=1000"
DRIVER_POLES_URL   = "https://api.jolpi.ca/ergast/f1/drivers/{driver_id}/qualifying/1.json?limit=1000"
from .driver_bios import DRIVER_BIOS

NATIONALITY_FLAGS = {
    "British":       "🇬🇧", "Dutch":         "🇳🇱", "Monegasque":    "🇲🇨",
    "Australian":    "🇦🇺", "Spanish":       "🇪🇸", "Mexican":       "🇲🇽",
    "Canadian":      "🇨🇦", "Finnish":       "🇫🇮", "French":        "🇫🇷",
    "German":        "🇩🇪", "Italian":       "🇮🇹", "Japanese":      "🇯🇵",
    "Danish":        "🇩🇰", "Thai":          "🇹🇭", "American":      "🇺🇸",
    "Chinese":       "🇨🇳", "New Zealander": "🇳🇿", "Argentine":     "🇦🇷",
    "Brazilian":     "🇧🇷",
}


async def _get(url: str) -> dict | None:
    """GET запрос с кэшированием на 1 час."""
    return await fetch_with_cache(url)



def _drivers_kb(drivers: list[dict]):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for d in drivers:
        flag = NATIONALITY_FLAGS.get(d.get("nationality", ""), "")
        name = f"{d['givenName']} {d['familyName']}"
        builder.button(
            text=f"{flag} {name}",
            callback_data=f"driver_{d['driverId']}"
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _driver_back_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ К списку пилотов", callback_data="drivers_list"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню",     callback_data="main_menu"))
    return builder.as_markup()


@router.callback_query(lambda c: c.data == "drivers_list")
async def cb_drivers_list(callback: CallbackQuery) -> None:
    """Показывает список всех пилотов сезона 2026."""
    await callback.answer("⏳ Загружаю...")
    data = await _get(DRIVERS_2026_URL)

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
    
    # Проверяем, есть ли в сообщении фото
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data.startswith("driver_"))
async def cb_driver_profile(callback: CallbackQuery) -> None:
    """Показывает профиль пилота с AI-характеристикой."""
    driver_id = callback.data[7:]
    await callback.answer("⏳ Загружаю профиль...")

    # Загружаем все данные параллельно
    season_data, wins_data, poles_data, all_drivers_data = await asyncio.gather(
        _get(DRIVER_SEASON_URL.format(driver_id=driver_id)),
        _get(DRIVER_WINS_URL.format(driver_id=driver_id)),
        _get(DRIVER_POLES_URL.format(driver_id=driver_id)),
        _get(DRIVERS_2026_URL),
    )

    # Находим пилота в списке
    driver_info = None
    if all_drivers_data:
        try:
            all_drivers = all_drivers_data["MRData"]["DriverTable"]["Drivers"]
            driver_info = next((d for d in all_drivers if d["driverId"] == driver_id), None)
        except (KeyError, IndexError):
            pass

    if not driver_info:
        await callback.message.edit_text(
            "❌ Пилот не найден.",
            reply_markup=_driver_back_kb()
        )
        return

    # Базовые данные
    flag        = NATIONALITY_FLAGS.get(driver_info.get("nationality", ""), "")
    name        = f"{driver_info['givenName']} {driver_info['familyName']}"
    number      = driver_info.get("permanentNumber", "—")
    dob         = driver_info.get("dateOfBirth", "—")
    nationality = driver_info.get("nationality", "—")

    # Возраст
    age = "—"
    if dob and dob != "—":
        from datetime import date
        try:
            birth = date.fromisoformat(dob)
            today = date.today()
            age = today.year - birth.year - (
                (today.month, today.day) < (birth.month, birth.day)
            )
        except ValueError:
            pass

    # Данные сезона 2026
    team   = "—"
    pos    = "—"
    points = "—"
    season_wins = "0"

    if season_data:
        try:
            sl = season_data["MRData"]["StandingsTable"]["StandingsLists"]
            if sl:
                s = sl[0]["DriverStandings"][0]
                pos         = s["position"]
                points      = s["points"]
                season_wins = s["wins"]
                team        = s["Constructors"][0]["name"] if s["Constructors"] else "—"
        except (KeyError, IndexError):
            pass

    # Карьерная статистика
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

    # Формируем текст профиля
    lines = [
        f"{flag} <b>{name}</b>  #{number}",
        f"{nationality} · {age} лет · {dob}",
        "",
        f"<b>Сезон 2026:</b> {team}",
        f"Позиция: {pos} · Очки: {points} · Побед: {season_wins}",
        "",
        f"<b>Карьера:</b> {career_wins} побед · {career_poles} поулов",
    ]

    # Добавляем биографию из словаря
    bio = DRIVER_BIOS.get(driver_id)
    logger.info("driver_id=%s, bio=%s, photo=%s", driver_id, bool(bio), bio.get('photo') if bio else None)
    if bio:
        lines += [
            "",
            f"<b>Стиль вождения:</b> {bio['style']}",
            "",
            f"<b>Репутация:</b> {bio['reputation']}",
            "",
            f"💡 <b>Факт:</b> {bio['fact']}",
        ]

    text = "\n".join(lines)
    photo_id = bio.get("photo") if bio else None

    if photo_id:
        # Удаляем старое сообщение и отправляем фото с подписью
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=_driver_back_kb(),
        )
    else:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=_driver_back_kb(),
        )
    logger.info("Просмотр профиля: %s", driver_id)