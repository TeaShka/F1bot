"""
Notification scheduler for race sessions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from bot_config.schedule import SCHEDULE_2026, SESSION_NAMES
from database import Database
from utils.time_utils import format_dt, now_utc

logger = logging.getLogger(__name__)

SEASON = 2026
MAX_IDLE_SLEEP_SECONDS = 3600
LATE_GRACE_SECONDS = 75
NOTIFICATION_MINUTES = (60, 15)

SESSION_KIND_MAP = {
    "fp1": "practice",
    "fp2": "practice",
    "fp3": "practice",
    "sprint_qualifying": "sprint",
    "sprint": "sprint",
    "qualifying": "qual",
    "race": "race",
}


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    season: int
    round_number: int
    race_name: str
    session_key: str
    session_dt: datetime
    due_at: datetime
    kind: str
    minutes_left: int


def _build_notification_events() -> list[NotificationEvent]:
    events: list[NotificationEvent] = []
    for race in SCHEDULE_2026:
        for session_key, kind in SESSION_KIND_MAP.items():
            session_dt = race["sessions"].get(session_key)
            if session_dt is None:
                continue

            session_utc = session_dt.replace(tzinfo=timezone.utc)
            for minutes_left in NOTIFICATION_MINUTES:
                events.append(
                    NotificationEvent(
                        season=SEASON,
                        round_number=race["round"],
                        race_name=race["name"],
                        session_key=session_key,
                        session_dt=session_dt,
                        due_at=session_utc - timedelta(minutes=minutes_left),
                        kind=kind,
                        minutes_left=minutes_left,
                    )
                )
    return sorted(events, key=lambda event: event.due_at)


NOTIFICATION_EVENTS = _build_notification_events()


async def notification_scheduler(bot: Bot, db: Database) -> None:
    """
    Sleeps until the next due notification instead of scanning the full
    calendar every minute.
    """
    logger.info("Notification scheduler is running")

    while True:
        now = now_utc()
        due_events = [
            event
            for event in NOTIFICATION_EVENTS
            if _is_due(event, now) and not _is_sent(db, event)
        ]

        if due_events:
            for event in due_events:
                db.mark_notification_sent(
                    event.season,
                    event.round_number,
                    event.session_key,
                    event.minutes_left,
                )
                await _broadcast(bot, db, event)
            await asyncio.sleep(1)
            continue

        next_due = _get_next_due_time(db, now)
        if next_due is None:
            await asyncio.sleep(MAX_IDLE_SLEEP_SECONDS)
            continue

        sleep_seconds = max(
            1,
            min((next_due - now).total_seconds(), MAX_IDLE_SLEEP_SECONDS),
        )
        await asyncio.sleep(sleep_seconds)


def _is_due(event: NotificationEvent, now: datetime) -> bool:
    delta_seconds = (now - event.due_at).total_seconds()
    return 0 <= delta_seconds <= LATE_GRACE_SECONDS


def _is_sent(db: Database, event: NotificationEvent) -> bool:
    return db.has_sent_notification(
        event.season,
        event.round_number,
        event.session_key,
        event.minutes_left,
    )


def _get_next_due_time(db: Database, now: datetime) -> datetime | None:
    for event in NOTIFICATION_EVENTS:
        if event.due_at <= now:
            continue
        if _is_sent(db, event):
            continue
        return event.due_at
    return None


async def _broadcast(bot: Bot, db: Database, event: NotificationEvent) -> None:
    subscribers = db.get_subscribers_by_time(event.kind, event.minutes_left)
    if not subscribers:
        return

    session_label = SESSION_NAMES[event.session_key]
    logger.info(
        "Sending notification (%d min): %s, %s -> %d subscribers",
        event.minutes_left,
        event.race_name,
        session_label,
        len(subscribers),
    )

    for subscriber in subscribers:
        user_id = subscriber["user_id"]
        timezone_name = subscriber["timezone"]
        time_str = format_dt(event.session_dt, timezone_name)
        text = (
            f"⏰ <b>Через {event.minutes_left} минут</b> — {event.race_name}\n"
            f"{session_label} · {time_str}"
        )

        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.warning(
                "Failed to send notification to user %d: %s",
                user_id,
                exc,
            )
