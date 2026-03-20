"""
Helpers for the free historical OpenF1 API.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlencode

from bot_config.schedule import SESSION_NAMES

from .api_client import ApiClient

OPENF1_BASE_URL = "https://api.openf1.org/v1"
OPENF1_SESSION_NAMES = {
    "fp1": "Practice 1",
    "fp2": "Practice 2",
    "fp3": "Practice 3",
    "sprint_qualifying": "Sprint Qualifying",
    "sprint": "Sprint",
    "qualifying": "Qualifying",
    "race": "Race",
}
SESSION_ORDER = tuple(OPENF1_SESSION_NAMES)
MEETINGS_TTL = 12 * 3600
SESSIONS_TTL = 6 * 3600
SESSION_DATA_TTL = 30 * 60


def _build_url(endpoint: str, **params: object) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{OPENF1_BASE_URL}/{endpoint}"
    return f"{OPENF1_BASE_URL}/{endpoint}?{urlencode(clean_params)}"


def _as_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def clean_session_label(session_key: str) -> str:
    return SESSION_NAMES[session_key].replace("⚡ ", "").replace("🏁 ", "")


def _format_range(values: list[float]) -> str:
    if not values:
        return "—"
    lo = min(values)
    hi = max(values)
    if abs(lo - hi) < 0.2:
        return f"{lo:.1f}°"
    return f"{lo:.1f}–{hi:.1f}°"


def driver_name(driver_number: int, drivers_map: dict[int, dict]) -> str:
    driver = drivers_map.get(int(driver_number))
    if not driver:
        return f"#{driver_number}"

    for key in ("broadcast_name", "full_name", "last_name", "name_acronym"):
        value = driver.get(key)
        if value:
            return str(value)
    return f"#{driver_number}"


async def get_grand_prix_meetings(api: ApiClient, year: int) -> list[dict]:
    meetings = _as_list(await api.fetch_json(_build_url("meetings", year=year), ttl=MEETINGS_TTL))
    grand_prix_meetings = [
        meeting
        for meeting in meetings
        if "grand prix" in str(meeting.get("meeting_name", "")).lower()
    ]
    return sorted(grand_prix_meetings, key=lambda item: str(item.get("date_start", "")))


async def get_meeting_for_round(api: ApiClient, year: int, round_number: int) -> dict | None:
    meetings = await get_grand_prix_meetings(api, year)
    if 1 <= round_number <= len(meetings):
        return meetings[round_number - 1]
    return None


async def get_sessions_for_meeting(api: ApiClient, meeting_key: int) -> list[dict]:
    return _as_list(
        await api.fetch_json(
            _build_url("sessions", meeting_key=meeting_key),
            ttl=SESSIONS_TTL,
        )
    )


async def get_sessions_map_for_race(api: ApiClient, race: dict) -> tuple[dict | None, dict[str, dict]]:
    meeting = await get_meeting_for_round(api, 2026, int(race["round"]))
    if meeting is None:
        return None, {}

    sessions = await get_sessions_for_meeting(api, int(meeting["meeting_key"]))
    sessions_map: dict[str, dict] = {}
    for local_key, openf1_name in OPENF1_SESSION_NAMES.items():
        session = next(
            (item for item in sessions if item.get("session_name") == openf1_name),
            None,
        )
        if session is not None:
            sessions_map[local_key] = session

    return meeting, sessions_map


async def get_drivers_map(api: ApiClient, session_key: int) -> dict[int, dict]:
    payload = await api.fetch_json(
        _build_url("drivers", session_key=session_key),
        ttl=SESSION_DATA_TTL,
    )
    drivers_map: dict[int, dict] = {}
    for item in _as_list(payload):
        number = item.get("driver_number")
        if number is None:
            continue
        try:
            drivers_map[int(number)] = item
        except (TypeError, ValueError):
            continue
    return drivers_map


async def get_session_result(api: ApiClient, session_key: int, *, allow_stale: bool = True) -> list[dict]:
    return _as_list(
        await api.fetch_json(
            _build_url("session_result", session_key=session_key),
            ttl=SESSION_DATA_TTL,
            allow_stale=allow_stale,
        )
    )


async def get_weather(api: ApiClient, session_key: int, *, allow_stale: bool = True) -> list[dict]:
    return _as_list(
        await api.fetch_json(
            _build_url("weather", session_key=session_key),
            ttl=SESSION_DATA_TTL,
            allow_stale=allow_stale,
        )
    )


async def get_race_control(api: ApiClient, session_key: int, *, allow_stale: bool = True) -> list[dict]:
    return _as_list(
        await api.fetch_json(
            _build_url("race_control", session_key=session_key),
            ttl=SESSION_DATA_TTL,
            allow_stale=allow_stale,
        )
    )


async def get_pit(api: ApiClient, session_key: int, *, allow_stale: bool = True) -> list[dict]:
    return _as_list(
        await api.fetch_json(
            _build_url("pit", session_key=session_key),
            ttl=SESSION_DATA_TTL,
            allow_stale=allow_stale,
        )
    )


async def get_stints(api: ApiClient, session_key: int, *, allow_stale: bool = True) -> list[dict]:
    return _as_list(
        await api.fetch_json(
            _build_url("stints", session_key=session_key),
            ttl=SESSION_DATA_TTL,
            allow_stale=allow_stale,
        )
    )


async def load_race_insights(
    api: ApiClient,
    race: dict,
    *,
    allow_stale: bool = True,
) -> dict | None:
    meeting, sessions_map = await get_sessions_map_for_race(api, race)
    race_session = sessions_map.get("race")
    if meeting is None or race_session is None:
        return None

    race_session_key = int(race_session["session_key"])
    drivers_map, session_result, weather, race_control, pit, stints = await asyncio.gather(
        get_drivers_map(api, race_session_key),
        get_session_result(api, race_session_key, allow_stale=allow_stale),
        get_weather(api, race_session_key, allow_stale=allow_stale),
        get_race_control(api, race_session_key, allow_stale=allow_stale),
        get_pit(api, race_session_key, allow_stale=allow_stale),
        get_stints(api, race_session_key, allow_stale=allow_stale),
    )

    qualifying_session = sessions_map.get("qualifying")
    qualifying_result: list[dict] = []
    if qualifying_session is not None:
        qualifying_result = await get_session_result(
            api,
            int(qualifying_session["session_key"]),
            allow_stale=allow_stale,
        )

    return {
        "meeting": meeting,
        "sessions": sessions_map,
        "race_session": race_session,
        "qualifying_session": qualifying_session,
        "drivers": drivers_map,
        "session_result": session_result,
        "qualifying_result": qualifying_result,
        "weather": weather,
        "race_control": race_control,
        "pit": pit,
        "stints": stints,
    }


async def load_weekend_weather(
    api: ApiClient,
    race: dict,
    *,
    allow_stale: bool = True,
) -> dict[str, list[dict]]:
    _, sessions_map = await get_sessions_map_for_race(api, race)
    weather_by_session: dict[str, list[dict]] = {}
    for session_key in SESSION_ORDER:
        session = sessions_map.get(session_key)
        if session is None:
            continue
        weather_by_session[session_key] = await get_weather(
            api,
            int(session["session_key"]),
            allow_stale=allow_stale,
        )
    return weather_by_session


def summarize_weather(weather_rows: list[dict]) -> dict | None:
    if not weather_rows:
        return None

    air = [float(item["air_temperature"]) for item in weather_rows if item.get("air_temperature") is not None]
    track = [float(item["track_temperature"]) for item in weather_rows if item.get("track_temperature") is not None]
    humidity = [float(item["humidity"]) for item in weather_rows if item.get("humidity") is not None]
    wind = [float(item["wind_speed"]) for item in weather_rows if item.get("wind_speed") is not None]
    rainfall = [float(item["rainfall"]) for item in weather_rows if item.get("rainfall") is not None]

    return {
        "air": _format_range(air),
        "track": _format_range(track),
        "humidity": f"{sum(humidity) / len(humidity):.0f}%" if humidity else "—",
        "wind": f"{max(wind):.1f} м/с" if wind else "—",
        "rain": any(value > 0 for value in rainfall),
    }


def format_weather_summary(summary: dict | None) -> str:
    if summary is None:
        return ""

    rain_text = "дождь фиксировался" if summary["rain"] else "сухо"
    return (
        f"воздух {summary['air']} • трасса {summary['track']} • "
        f"влажность {summary['humidity']} • ветер до {summary['wind']} • {rain_text}"
    )


def build_weekend_weather_lines(weather_by_session: dict[str, list[dict]]) -> list[str]:
    lines: list[str] = []
    for session_key in SESSION_ORDER:
        summary = summarize_weather(weather_by_session.get(session_key, []))
        if summary is None:
            continue
        lines.append(f"• {clean_session_label(session_key)}: {format_weather_summary(summary)}")
    return lines


def summarize_race_control(messages: list[dict]) -> dict[str, int | str | None]:
    summary = {
        "safety_car": 0,
        "virtual_safety_car": 0,
        "red_flags": 0,
        "yellow_flags": 0,
        "notes": None,
    }
    noteworthy: list[str] = []

    for item in messages:
        message = str(item.get("message", "")).strip()
        message_upper = message.upper()
        flag = str(item.get("flag", "")).upper()

        if "VIRTUAL SAFETY CAR DEPLOYED" in message_upper:
            summary["virtual_safety_car"] += 1
        elif "SAFETY CAR DEPLOYED" in message_upper and "VIRTUAL" not in message_upper:
            summary["safety_car"] += 1

        if flag == "RED" or "RED FLAG" in message_upper:
            summary["red_flags"] += 1
        if "YELLOW" in flag:
            summary["yellow_flags"] += 1

        if message and "CHEQUERED" not in message_upper and "CLEAR" not in message_upper:
            noteworthy.append(message)

    if noteworthy:
        summary["notes"] = noteworthy[-1]
    return summary


def build_race_control_lines(messages: list[dict]) -> list[str]:
    if not messages:
        return []

    summary = summarize_race_control(messages)
    parts: list[str] = []
    if summary["safety_car"]:
        parts.append(f"SC: {summary['safety_car']}")
    if summary["virtual_safety_car"]:
        parts.append(f"VSC: {summary['virtual_safety_car']}")
    if summary["red_flags"]:
        parts.append(f"красные флаги: {summary['red_flags']}")
    if summary["yellow_flags"]:
        parts.append(f"жёлтые флаги: {summary['yellow_flags']}")

    if not parts:
        parts.append("без SC/VSC и красных флагов")

    lines = [f"• {' • '.join(parts)}"]
    if summary["notes"]:
        lines.append(f"• Последнее заметное сообщение: {summary['notes']}")
    return lines


def pick_fastest_pit(pits: list[dict]) -> dict | None:
    valid = [
        item
        for item in pits
        if item.get("stop_duration") is not None and item.get("driver_number") is not None
    ]
    if not valid:
        return None
    return min(valid, key=lambda item: float(item["stop_duration"]))


def build_strategy_lines(
    session_result: list[dict],
    stints: list[dict],
    drivers_map: dict[int, dict],
) -> list[str]:
    if not session_result or not stints:
        return []

    stints_by_driver: dict[int, list[dict]] = defaultdict(list)
    for item in stints:
        number = item.get("driver_number")
        if number is None:
            continue
        try:
            stints_by_driver[int(number)].append(item)
        except (TypeError, ValueError):
            continue

    top_finishers = sorted(
        (item for item in session_result if item.get("position") is not None),
        key=lambda item: int(item["position"]),
    )[:3]
    lines: list[str] = []

    for result in top_finishers:
        number = int(result["driver_number"])
        driver = driver_name(number, drivers_map)
        driver_stints = sorted(
            stints_by_driver.get(number, []),
            key=lambda item: int(item.get("stint_number", 99)),
        )
        compounds = [str(item.get("compound", "")).title() for item in driver_stints if item.get("compound")]
        if not compounds:
            continue
        lines.append(f"• {driver}: {' -> '.join(compounds)}")

    return lines


def build_complete_strategy_lines(
    session_result: list[dict],
    stints: list[dict],
    drivers_map: dict[int, dict],
) -> list[str]:
    if not session_result or not stints:
        return []

    stints_by_driver: dict[int, list[dict]] = defaultdict(list)
    for item in stints:
        number = item.get("driver_number")
        if number is None:
            continue
        try:
            stints_by_driver[int(number)].append(item)
        except (TypeError, ValueError):
            continue

    top_finishers = sorted(
        (item for item in session_result if item.get("position") is not None),
        key=lambda item: int(item["position"]),
    )[:3]
    lines: list[str] = []

    for result in top_finishers:
        number = int(result["driver_number"])
        driver = driver_name(number, drivers_map)
        driver_stints = sorted(
            stints_by_driver.get(number, []),
            key=lambda item: int(item.get("stint_number", 99)),
        )

        normalized_stints: list[dict] = []
        seen_stint_numbers: set[int] = set()
        for item in driver_stints:
            try:
                stint_number = int(item.get("stint_number", 0))
            except (TypeError, ValueError):
                continue
            if stint_number <= 0 or stint_number in seen_stint_numbers:
                continue
            seen_stint_numbers.add(stint_number)
            normalized_stints.append(item)

        stint_numbers = [int(item["stint_number"]) for item in normalized_stints]
        expected_numbers = list(range(1, len(stint_numbers) + 1))
        if not stint_numbers or stint_numbers != expected_numbers:
            continue

        compounds = [
            str(item.get("compound", "")).title()
            for item in normalized_stints
            if item.get("compound")
        ]
        if not compounds:
            continue

        lines.append(f"- {driver}: {' -> '.join(compounds)}")

    return lines


def build_pit_summary_lines(pits: list[dict], drivers_map: dict[int, dict]) -> list[str]:
    fastest = pick_fastest_pit(pits)
    if fastest is None:
        return []

    driver = driver_name(int(fastest["driver_number"]), drivers_map)
    duration = float(fastest["stop_duration"])
    total_stops = Counter(
        int(item["driver_number"])
        for item in pits
        if item.get("driver_number") is not None
    )
    busiest_number, busiest_count = total_stops.most_common(1)[0] if total_stops else (None, 0)
    busiest_text = ""
    if busiest_number is not None and busiest_count:
        busiest_text = f" • больше всего остановок: {driver_name(busiest_number, drivers_map)} ({busiest_count})"
    return [f"• Быстрейший пит-стоп: {driver} — {duration:.2f} c{busiest_text}"]
