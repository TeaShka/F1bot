"""
Utilities for datetime handling and timezone-safe formatting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "UTC"

# Popular timezones for quick keyboard selection (display -> IANA id)
POPULAR_TIMEZONES: dict[str, str] = {
    "🇷🇺 Москва (UTC+3)": "Europe/Moscow",
    "🇷🇺 Екатеринбург (UTC+5)": "Asia/Yekaterinburg",
    "🇷🇺 Новосибирск (UTC+7)": "Asia/Novosibirsk",
    "🇷🇺 Красноярск (UTC+7)": "Asia/Krasnoyarsk",
    "🇷🇺 Иркутск (UTC+8)": "Asia/Irkutsk",
    "🇷🇺 Владивосток (UTC+10)": "Asia/Vladivostok",
    "🇺🇦 Киев (UTC+2/3)": "Europe/Kyiv",
    "🇧🇾 Минск (UTC+3)": "Europe/Minsk",
    "🇰🇿 Алматы (UTC+5)": "Asia/Almaty",
    "🇺🇿 Ташкент (UTC+5)": "Asia/Tashkent",
    "🌍 UTC": "UTC",
    "🇩🇪 Берлин (UTC+1/2)": "Europe/Berlin",
    "🇬🇧 Лондон (UTC+0/1)": "Europe/London",
    "🇺🇸 Нью-Йорк (UTC-5/-4)": "America/New_York",
    "🇺🇸 Лос-Анджелес (UTC-8/-7)": "America/Los_Angeles",
    "🇦🇪 Дубай (UTC+4)": "Asia/Dubai",
    "🇸🇬 Сингапур (UTC+8)": "Asia/Singapore",
    "🇯🇵 Токио (UTC+9)": "Asia/Tokyo",
    "🇦🇺 Сидней (UTC+10/11)": "Australia/Sydney",
}


def normalize_timezone(tz_name: str | None, fallback: str = DEFAULT_TIMEZONE) -> str:
    """Return a guaranteed valid timezone name."""
    if not tz_name:
        return fallback
    if tz_name == fallback:
        return fallback

    try:
        ZoneInfo(tz_name)
        return tz_name
    except (ZoneInfoNotFoundError, KeyError, ValueError, TypeError):
        logger.warning("Invalid timezone '%s', fallback to %s", tz_name, fallback)
        return fallback


def is_valid_timezone(tz_name: str) -> bool:
    """Check whether timezone is a valid IANA timezone id."""
    try:
        ZoneInfo(tz_name)
        return True
    except (ZoneInfoNotFoundError, KeyError, ValueError, TypeError):
        return False


def now_utc() -> datetime:
    """Return current UTC time as aware datetime."""
    return datetime.now(tz=timezone.utc)


def localize_dt(dt: datetime, tz_name: str | None) -> datetime:
    """
    Convert datetime (naive UTC or aware) to target timezone.
    Invalid timezone values are automatically replaced with UTC.
    """
    utc_aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    safe_tz = normalize_timezone(tz_name)

    if safe_tz == DEFAULT_TIMEZONE:
        return utc_aware.astimezone(timezone.utc)
    return utc_aware.astimezone(ZoneInfo(safe_tz))


def format_dt(dt: datetime, tz_name: str | None) -> str:
    """Format datetime for user-facing text."""
    local = localize_dt(dt, tz_name)
    tz_abbr = local.strftime("%Z") or "UTC"
    return local.strftime(f"%d %B, %a 🕐 %H:%M ({tz_abbr})")


def get_next_race(schedule: list[dict]) -> Optional[dict]:
    """
    Return the nearest race that has not started yet in UTC timeline.
    """
    now = now_utc()
    for race in schedule:
        race_start_utc = race["sessions"]["race"].replace(tzinfo=timezone.utc)
        if race_start_utc > now:
            return race
    return None
