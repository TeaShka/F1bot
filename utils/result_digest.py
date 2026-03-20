"""
Helpers for result-release digests.
"""

from __future__ import annotations

from bot_config.schedule import SESSION_NAMES
from utils.openf1 import (
    build_pit_summary_lines,
    build_race_control_lines,
    format_weather_summary,
    summarize_weather,
)
from utils.time_utils import format_dt

QUALI_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/2026/{round}/qualifying.json"
RACE_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/2026/{round}/results.json"

PODIUM_ICONS = {1: "🥇", 2: "🥈", 3: "🥉"}


def has_qualifying_results(data: dict | None) -> bool:
    try:
        return bool(data["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"])
    except (KeyError, IndexError, TypeError):
        return False


def has_race_results(data: dict | None) -> bool:
    try:
        return bool(data["MRData"]["RaceTable"]["Races"][0]["Results"])
    except (KeyError, IndexError, TypeError):
        return False


def build_qualifying_digest_text(
    race: dict,
    qualifying_data: dict,
    timezone_name: str | None = None,
) -> str:
    qualifying_results = qualifying_data["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"]
    lines = [
        f"⚡ <b>Результаты квалификации — {race['name']}</b>",
        f"<i>{race['circuit']} · {race['country']}</i>",
        "",
        "<b>Топ-3:</b>",
    ]

    for item in qualifying_results[:3]:
        position = int(item.get("position", 0))
        icon = PODIUM_ICONS.get(position, f"{position}.")
        driver = _driver_name(item["Driver"])
        best_time = item.get("Q3") or item.get("Q2") or item.get("Q1", "—")
        lines.append(f"{icon} <b>{driver}</b> — {best_time}")

    if timezone_name:
        race_time = format_dt(race["sessions"]["race"], timezone_name)
        lines.extend(
            [
                "",
                f"🏁 <b>{SESSION_NAMES['race']}:</b> {race_time}",
            ]
        )

    return "\n".join(lines)


def build_race_digest_text(
    race: dict,
    race_data: dict,
    qualifying_data: dict | None = None,
    openf1_insights: dict | None = None,
) -> str:
    results = race_data["MRData"]["RaceTable"]["Races"][0]["Results"]
    lines = [
        f"🏁 <b>Итоги — {race['name']}</b>",
        f"<i>{race['circuit']} · {race['country']}</i>",
        "",
        "<b>Подиум:</b>",
    ]

    fastest_lap_driver = None
    fastest_lap_time = None

    for item in results:
        position = int(item.get("position", 99))
        if position <= 3:
            icon = PODIUM_ICONS.get(position, f"{position}.")
            driver = _driver_name(item["Driver"])
            team = item["Constructor"]["name"]
            time_or_status = item.get("Time", {}).get("time") or item.get("status", "—")
            lines.append(f"{icon} <b>{driver}</b> — {team}")
            lines.append(f"   {time_or_status}")

        fastest_lap = item.get("FastestLap", {})
        if fastest_lap.get("rank") == "1":
            fastest_lap_driver = _driver_name(item["Driver"])
            fastest_lap_time = fastest_lap.get("Time", {}).get("time", "—")

    pole_driver = None
    pole_time = None
    if qualifying_data and has_qualifying_results(qualifying_data):
        qualifying_results = qualifying_data["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"]
        pole = next((item for item in qualifying_results if item.get("position") == "1"), None)
        if pole:
            pole_driver = _driver_name(pole["Driver"])
            pole_time = pole.get("Q3") or pole.get("Q2") or pole.get("Q1", "—")

    if pole_driver:
        lines.extend(["", f"⚡ <b>Поул:</b> {pole_driver} — {pole_time}"])

    if fastest_lap_driver and fastest_lap_time:
        lines.append(f"🔥 <b>Быстрый круг:</b> {fastest_lap_driver} — {fastest_lap_time}")

    if openf1_insights:
        lines.extend(_build_openf1_digest_block(openf1_insights))

    return "\n".join(lines)


def _build_openf1_digest_block(openf1_insights: dict) -> list[str]:
    details: list[str] = []

    weather_summary = summarize_weather(openf1_insights.get("weather", []))
    if weather_summary is not None:
        details.append(f"• Погода: {format_weather_summary(weather_summary)}")

    details.extend(build_race_control_lines(openf1_insights.get("race_control", [])))
    details.extend(
        build_pit_summary_lines(
            openf1_insights.get("pit", []),
            openf1_insights.get("drivers", {}),
        )
    )

    if not details:
        return []
    return ["", "<b>OpenF1:</b>", *details]


def build_sample_qualifying_digest_text(race: dict) -> str:
    return "\n".join(
        [
            f"⚡ <b>Результаты квалификации — {race['name']}</b>",
            f"<i>{race['circuit']} · {race['country']}</i>",
            "",
            "<b>Топ-3:</b>",
            "🥇 <b>Lando Norris</b> — 1:27.441",
            "🥈 <b>Charles Leclerc</b> — 1:27.503",
            "🥉 <b>Oscar Piastri</b> — 1:27.548",
        ]
    )


def build_sample_race_digest_text(race: dict) -> str:
    return "\n".join(
        [
            f"🏁 <b>Итоги — {race['name']}</b>",
            f"<i>{race['circuit']} · {race['country']}</i>",
            "",
            "<b>Подиум:</b>",
            "🥇 <b>Lando Norris</b> — McLaren",
            "   1:31:22.184",
            "🥈 <b>Charles Leclerc</b> — Ferrari",
            "   +3.412",
            "🥉 <b>Oscar Piastri</b> — McLaren",
            "   +7.904",
            "",
            "⚡ <b>Поул:</b> Lando Norris — 1:27.441",
            "🔥 <b>Быстрый круг:</b> Max Verstappen — 1:30.204",
        ]
    )


def build_sample_extended_race_digest_text(race: dict) -> str:
    return "\n".join(
        [
            build_sample_race_digest_text(race),
            "",
            "<b>OpenF1:</b>",
            "• Погода: воздух 28.1–31.4° • трасса 40.8–47.2° • влажность 61% • ветер до 5.8 м/с • сухо",
            "• SC: 1 • VSC: 1 • жёлтые флаги: 3",
            "• Последнее заметное сообщение: CAR 81 UNDER INVESTIGATION FOR PIT EXIT INCIDENT",
            "• Быстрейший пит-стоп: Oscar Piastri — 2.18 c • больше всего остановок: Lewis Hamilton (3)",
        ]
    )

def _driver_name(driver: dict) -> str:
    return f"{driver['givenName']} {driver['familyName']}"
