"""
Обработчики, связанные с гонками:
  - следующая гонка
  - полный календарь сезона
  - детали конкретного этапа
  - информация о завершённой гонке (результаты с API)
"""

import logging
from datetime import timezone
from aiogram import Router
from aiogram.types import CallbackQuery
import aiohttp
import asyncio

from bot_config.schedule import SCHEDULE_2026, SESSION_NAMES
from database import Database
from keyboards import back_to_menu_kb, calendar_kb
from utils import get_next_race, format_dt, now_utc

logger = logging.getLogger(__name__)

router = Router(name="races")

RACE_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/2026/{round}/results.json"
QUALI_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/2026/{round}/qualifying.json"


def is_race_finished(race: dict) -> bool:
    """Проверяет завершилась ли гонка."""
    race_utc = race["sessions"]["race"].replace(tzinfo=timezone.utc)
    return now_utc() > race_utc


async def fetch_quali_result(round_num: int) -> dict | None:
    """Загружает результаты квалификации с Jolpica API."""
    url = QUALI_RESULTS_URL.format(round=round_num)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as exc:
        logger.error("Ошибка загрузки квалификации %d: %s", round_num, exc)
        return None


async def fetch_race_result(round_num: int) -> dict | None:
    """Загружает результаты гонки с Jolpica API."""
    url = RACE_RESULTS_URL.format(round=round_num)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as exc:
        logger.error("Ошибка загрузки результатов гонки %d: %s", round_num, exc)
        return None


def _build_race_detail(race: dict, tz: str) -> str:
    """Формирует текстовое представление этапа со всеми сессиями."""
    finished = is_race_finished(race)
    if finished:
        name_line = f"{race['flag']} <b><s>{race['name']}</s></b> ✅"
    else:
        name_line = f"{race['flag']} <b>{race['name']}</b>"

    lines = [
        name_line,
        f"Трасса: {race['circuit']}, {race['country']}",
        "",
        "<b>Расписание сессий:</b>",
    ]

    for session_key, session_label in SESSION_NAMES.items():
        dt = race["sessions"].get(session_key)
        if dt is not None:
            time_str = format_dt(dt, tz)
            lines.append(f"  {session_label}  {time_str}")

    lines.append(f"\nЧасовой пояс: <code>{tz}</code>")
    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "next_race")
async def cb_next_race(callback: CallbackQuery, db: Database) -> None:
    """Показывает ближайший Гран-при с расписанием сессий."""
    user_id = callback.from_user.id
    tz = db.get_user_timezone(user_id)
    race = get_next_race(SCHEDULE_2026)

    if race is None:
        text = "🏁 Сезон 2026 завершён!\n\nСледите за новостями о сезоне 2027 🏎"
        await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
        await callback.answer()
        return

    remaining = sum(1 for r in SCHEDULE_2026
                    if r["sessions"]["race"] >= race["sessions"]["race"])

    text = (
        f"🔜 <b>Следующий Гран-при</b> (этап {race['round']} из {len(SCHEDULE_2026)})\n"
        f"Осталось гонок в сезоне: {remaining}\n\n"
    ) + _build_race_detail(race, tz)

    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=back_to_menu_kb()
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "calendar")
async def cb_calendar(callback: CallbackQuery) -> None:
    """Выводит список всех этапов сезона 2026."""
    text = "📅 <b>Календарь Формулы 1 — Сезон 2026</b>\n\nВыберите этап:"
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=calendar_kb(SCHEDULE_2026),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("race_") and not c.data.startswith("race_info_"))
async def cb_race_detail(callback: CallbackQuery, db: Database) -> None:
    """Показывает детали конкретного этапа по его номеру."""
    try:
        round_num = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("Неверный номер этапа", show_alert=True)
        return

    race = next((r for r in SCHEDULE_2026 if r["round"] == round_num), None)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    tz = db.get_user_timezone(user_id)
    text = _build_race_detail(race, tz)

    # Если гонка завершена — добавляем кнопку "Информация о гонке"
    if is_race_finished(race):
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="🏆 Информация о гонке",
                callback_data=f"race_info_{round_num}"
            )
        )
        builder.row(
            InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")
        )
        kb = builder.as_markup()
    else:
        kb = back_to_menu_kb()

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("race_info_"))
async def cb_race_info(callback: CallbackQuery) -> None:
    """Показывает результаты завершённой гонки."""
    try:
        round_num = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка", show_alert=True)
        return

    race = next((r for r in SCHEDULE_2026 if r["round"] == round_num), None)
    if race is None:
        await callback.answer("Этап не найден", show_alert=True)
        return

    await callback.answer("⏳ Загружаю результаты...")

    data, quali_data = await asyncio.gather(
        fetch_race_result(round_num),
        fetch_quali_result(round_num),
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="◀️ Назад к этапу", callback_data=f"race_{round_num}")
    )
    builder.row(
        InlineKeyboardButton(text="🏠 Главное меню",   callback_data="main_menu")
    )
    kb = builder.as_markup()

    if data is None:
        await callback.message.edit_text(
            f"{race['flag']} <b>{race['name']}</b>\n\n"
            "❌ Результаты ещё не опубликованы или API недоступен.\n"
            "Попробуй через несколько часов после финиша.",
            parse_mode="HTML", reply_markup=kb
        )
        return

    try:
        results = data["MRData"]["RaceTable"]["Races"][0]["Results"]
    except (KeyError, IndexError):
        await callback.message.edit_text(
            f"{race['flag']} <b>{race['name']}</b>\n\n"
            "❌ Результаты ещё не опубликованы.\n"
            "Данные появляются через несколько часов после финиша.",
            parse_mode="HTML", reply_markup=kb
        )
        return

    # Топ-3
    podium_icons = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [
        f"{race['flag']} <b>{race['name']}</b>",
        f"{race['circuit']}",
        "",
        "<b>Подиум:</b>",
    ]

    winner_time = None
    fastest_lap_driver = None
    fastest_lap_time = None

    for r in results:
        pos = int(r.get("position", 99))
        driver = f"{r['Driver']['givenName']} {r['Driver']['familyName']}"
        team = r["Constructor"]["name"]
        status = r.get("status", "")

        if pos <= 3:
            icon = podium_icons[pos]
            time_val = r.get("Time", {}).get("time", status)
            if pos == 1:
                winner_time = time_val
                lines.append(f"{icon} <b>{driver}</b> — {team}")
                lines.append(f"    ⏱ {time_val}")
            else:
                lines.append(f"{icon} <b>{driver}</b> — {team}")
                lines.append(f"    {time_val}")

        # Быстрый круг
        fl = r.get("FastestLap", {})
        if fl.get("rank") == "1":
            fastest_lap_driver = driver
            fastest_lap_time = fl.get("Time", {}).get("time", "—")

    # Поул-позиция из данных квалификации
    pole_driver = None
    pole_time = None
    if quali_data:
        try:
            q_results = quali_data["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"]
            pole = next((q for q in q_results if q["position"] == "1"), None)
            if pole:
                pole_driver = f"{pole['Driver']['givenName']} {pole['Driver']['familyName']}"
                pole_time = pole.get("Q3") or pole.get("Q2") or pole.get("Q1", "—")
        except (KeyError, IndexError):
            pass

    if pole_driver:
        lines += [
            "",
            f"⚡ <b>Поул-позиция:</b> {pole_driver} — {pole_time}",
        ]

    if fastest_lap_driver and fastest_lap_time:
        lines += [
            f"🔥 <b>Быстрый круг:</b> {fastest_lap_driver} — {fastest_lap_time}",
        ]

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb
    )
    logger.info("Пользователь запросил результаты этапа %d", round_num)