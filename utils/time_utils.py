"""
Утилиты для работы со временем и часовыми поясами.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional

# Популярные часовые пояса для быстрого выбора (отображение → IANA-идентификатор)
POPULAR_TIMEZONES: dict[str, str] = {
    "🇷🇺 Москва (UTC+3)":          "Europe/Moscow",
    "🇷🇺 Екатеринбург (UTC+5)":    "Asia/Yekaterinburg",
    "🇷🇺 Новосибирск (UTC+7)":     "Asia/Novosibirsk",
    "🇷🇺 Красноярск (UTC+7)":      "Asia/Krasnoyarsk",
    "🇷🇺 Иркутск (UTC+8)":         "Asia/Irkutsk",
    "🇷🇺 Владивосток (UTC+10)":    "Asia/Vladivostok",
    "🇺🇦 Киев (UTC+2/3)":          "Europe/Kyiv",
    "🇧🇾 Минск (UTC+3)":           "Europe/Minsk",
    "🇰🇿 Алматы (UTC+5)":          "Asia/Almaty",
    "🇺🇿 Ташкент (UTC+5)":         "Asia/Tashkent",
    "🌍 UTC":                       "UTC",
    "🇩🇪 Берлин (UTC+1/2)":        "Europe/Berlin",
    "🇬🇧 Лондон (UTC+0/1)":        "Europe/London",
    "🇺🇸 Нью-Йорк (UTC-5/-4)":    "America/New_York",
    "🇺🇸 Лос-Анджелес (UTC-8/-7)": "America/Los_Angeles",
    "🇦🇪 Дубай (UTC+4)":           "Asia/Dubai",
    "🇸🇬 Сингапур (UTC+8)":        "Asia/Singapore",
    "🇯🇵 Токио (UTC+9)":           "Asia/Tokyo",
    "🇦🇺 Сидней (UTC+10/11)":      "Australia/Sydney",
}


def is_valid_timezone(tz_name: str) -> bool:
    """Проверяет, является ли строка корректным IANA-идентификатором."""
    try:
        ZoneInfo(tz_name)
        return True
    except (ZoneInfoNotFoundError, KeyError):
        return False


def now_utc() -> datetime:
    """Возвращает текущее UTC-время как aware datetime."""
    return datetime.now(tz=timezone.utc)


def localize_dt(dt: datetime, tz_name: str) -> datetime:
    """
    Конвертирует naive UTC-datetime в указанный часовой пояс.

    :param dt:      Naive datetime в UTC
    :param tz_name: IANA-идентификатор часового пояса
    :return:        Aware datetime в нужном поясе
    """
    utc_aware = dt.replace(tzinfo=timezone.utc)
    return utc_aware.astimezone(ZoneInfo(tz_name))


def format_dt(dt: datetime, tz_name: str) -> str:
    """
    Форматирует datetime для отображения пользователю.

    Пример вывода: «13 марта, чт 🕐 03:30 (MSK)»
    """
    local = localize_dt(dt, tz_name)
    # Короткое имя пояса (MSK, CET, EST…)
    tz_abbr = local.strftime("%Z")
    return local.strftime(f"%d %B, %a 🕐 %H:%M ({tz_abbr})")


def get_next_race(schedule: list[dict]) -> Optional[dict]:
    """
    Возвращает ближайший Гран-при относительно текущего момента UTC.
    «Ближайший» — тот, чья гонка ещё не завершилась.
    """
    now = now_utc()
    for race in schedule:
        race_start_utc = race["sessions"]["race"].replace(tzinfo=timezone.utc)
        if race_start_utc > now:
            return race
    return None  # сезон завершён
