"""
Notification scheduler for race sessions and result digests.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from bot_config.schedule import SCHEDULE_2026, SESSION_NAMES
from database import Database
from utils.api_client import ApiClient
from utils.openf1 import load_race_insights
from utils.result_digest import (
    QUALI_RESULTS_URL,
    RACE_RESULTS_URL,
    build_qualifying_digest_text,
    build_race_digest_text,
    has_qualifying_results,
    has_race_results,
)
from utils.time_utils import format_dt, now_utc

logger = logging.getLogger(__name__)

SEASON = 2026
MAX_IDLE_SLEEP_SECONDS = 3600
LATE_GRACE_SECONDS = 75
NOTIFICATION_MINUTES = (60, 15)
RESULT_POLL_INTERVAL_SECONDS = 300
OPENF1_RACE_DIGEST_FALLBACK_AFTER = timedelta(hours=12)
RESULT_AVAILABLE_DELAY = {
    "qualifying": timedelta(minutes=75),
    "race": timedelta(hours=2, minutes=10),
}

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


@dataclass(frozen=True, slots=True)
class ResultDigestEvent:
    season: int
    round_number: int
    race: dict
    session_key: str
    available_after: datetime


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


def _build_result_digest_events() -> list[ResultDigestEvent]:
    events: list[ResultDigestEvent] = []
    for race in SCHEDULE_2026:
        for session_key in ("qualifying", "race"):
            session_dt = race["sessions"].get(session_key)
            if session_dt is None:
                continue

            session_utc = session_dt.replace(tzinfo=timezone.utc)
            events.append(
                ResultDigestEvent(
                    season=SEASON,
                    round_number=race["round"],
                    race=race,
                    session_key=session_key,
                    available_after=session_utc + RESULT_AVAILABLE_DELAY[session_key],
                )
            )
    return sorted(events, key=lambda event: event.available_after)


NOTIFICATION_EVENTS = _build_notification_events()
RESULT_DIGEST_EVENTS = _build_result_digest_events()
_result_retry_at: dict[tuple[int, int, str], datetime] = {}


async def notification_scheduler(bot: Bot, db: Database, api: ApiClient) -> None:
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

        sent_digest = await _process_result_digests(bot, db, api, now)
        if sent_digest:
            await asyncio.sleep(1)
            continue

        next_due = _get_next_wakeup(db, now)
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


def _result_event_key(event: ResultDigestEvent) -> tuple[int, int, str]:
    return (event.season, event.round_number, event.session_key)


def _result_marker_session_key(event: ResultDigestEvent) -> str:
    return f"{event.session_key}_digest"


def _is_result_sent(db: Database, event: ResultDigestEvent) -> bool:
    return db.has_sent_notification(
        event.season,
        event.round_number,
        _result_marker_session_key(event),
        0,
    )


def _get_next_result_check_time(db: Database, now: datetime) -> datetime | None:
    candidates: list[datetime] = []
    for event in RESULT_DIGEST_EVENTS:
        if _is_result_sent(db, event):
            continue

        retry_at = _result_retry_at.get(_result_event_key(event))
        next_check = event.available_after if retry_at is None else retry_at
        if next_check <= now:
            return now
        candidates.append(next_check)

    return min(candidates) if candidates else None


def _get_next_wakeup(db: Database, now: datetime) -> datetime | None:
    candidates = [
        value
        for value in (
            _get_next_due_time(db, now),
            _get_next_result_check_time(db, now),
        )
        if value is not None
    ]
    return min(candidates) if candidates else None


async def _process_result_digests(
    bot: Bot,
    db: Database,
    api: ApiClient,
    now: datetime,
) -> bool:
    sent_any = False
    for event in RESULT_DIGEST_EVENTS:
        if _is_result_sent(db, event):
            continue
        if now < event.available_after:
            continue

        retry_at = _result_retry_at.get(_result_event_key(event))
        if retry_at is not None and now < retry_at:
            continue

        payload = await _load_digest_payload(api, event, now)
        if payload is None:
            _result_retry_at[_result_event_key(event)] = now + timedelta(seconds=RESULT_POLL_INTERVAL_SECONDS)
            continue

        db.mark_notification_sent(
            event.season,
            event.round_number,
            _result_marker_session_key(event),
            0,
        )
        _result_retry_at.pop(_result_event_key(event), None)
        await _broadcast_result_digest(bot, db, event, payload)
        sent_any = True

    return sent_any


async def _load_digest_payload(
    api: ApiClient,
    event: ResultDigestEvent,
    now: datetime,
) -> dict | None:
    if event.session_key == "qualifying":
        qualifying_data = await api.fetch_json(
            QUALI_RESULTS_URL.format(round=event.round_number),
            ttl=60,
            allow_stale=False,
        )
        if not has_qualifying_results(qualifying_data):
            return None
        return {"qualifying_data": qualifying_data}

    race_data = await api.fetch_json(
        RACE_RESULTS_URL.format(round=event.round_number),
        ttl=60,
        allow_stale=False,
    )
    if not has_race_results(race_data):
        return None

    qualifying_data = await api.fetch_json(
        QUALI_RESULTS_URL.format(round=event.round_number),
        ttl=3600,
        allow_stale=True,
    )
    openf1_insights = await load_race_insights(api, event.race, allow_stale=False)
    if openf1_insights is None or not openf1_insights.get("session_result"):
        if now < event.available_after + OPENF1_RACE_DIGEST_FALLBACK_AFTER:
            return None
        openf1_insights = None

    return {
        "race_data": race_data,
        "qualifying_data": qualifying_data,
        "openf1_insights": openf1_insights,
    }


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


async def _broadcast_result_digest(
    bot: Bot,
    db: Database,
    event: ResultDigestEvent,
    payload: dict,
) -> None:
    subscribers = db.get_subscribers("results")
    if not subscribers:
        return

    logger.info(
        "Sending result digest: round=%d, session=%s -> %d subscribers",
        event.round_number,
        event.session_key,
        len(subscribers),
    )

    for subscriber in subscribers:
        timezone_name = subscriber["timezone"]
        if event.session_key == "qualifying":
            text = build_qualifying_digest_text(
                event.race,
                payload["qualifying_data"],
                timezone_name,
            )
        else:
            text = build_race_digest_text(
                event.race,
                payload["race_data"],
                payload.get("qualifying_data"),
                payload.get("openf1_insights"),
            )

        try:
            await bot.send_message(subscriber["user_id"], text, parse_mode="HTML")
        except Exception as exc:
            logger.warning(
                "Failed to send result digest to user %d: %s",
                subscriber["user_id"],
                exc,
            )
