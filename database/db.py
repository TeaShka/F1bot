"""
SQLite access layer for the bot.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from threading import RLock
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

ALLOWED_NOTIFICATION_KINDS = {"qual", "race", "sprint", "practice", "results"}


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = RLock()
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row

        self._configure_connection()
        self._init_db()
        self._upgrade_db()
        self._create_indexes()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _configure_connection(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.commit()

    def _run(self, query: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(query, params)
            self._conn.commit()

    def _fetchone(self, query: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(query, params).fetchone()

    def _fetchall(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(query, params).fetchall()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    notify_qual INTEGER NOT NULL DEFAULT 0,
                    notify_race INTEGER NOT NULL DEFAULT 0,
                    notify_sprint INTEGER NOT NULL DEFAULT 0,
                    notify_practice INTEGER NOT NULL DEFAULT 0,
                    notify_results INTEGER NOT NULL DEFAULT 0,
                    notify_time INTEGER NOT NULL DEFAULT 60,
                    last_seen TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_notifications (
                    season INTEGER NOT NULL,
                    round INTEGER NOT NULL,
                    session_key TEXT NOT NULL,
                    target_minutes INTEGER NOT NULL,
                    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (season, round, session_key, target_minutes)
                )
                """
            )
            self._conn.commit()
        logger.info("Database initialized: %s", self.db_path)

    def _upgrade_db(self) -> None:
        columns_to_add = [
            ("notify_time", "INTEGER NOT NULL DEFAULT 60"),
            ("last_seen", "TEXT"),
            ("notify_sprint", "INTEGER NOT NULL DEFAULT 0"),
            ("notify_practice", "INTEGER NOT NULL DEFAULT 0"),
            ("notify_results", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for column_name, column_def in columns_to_add:
            try:
                self._run(f"ALTER TABLE users ADD COLUMN {column_name} {column_def}")
                logger.info("Database upgraded with column %s", column_name)
            except sqlite3.OperationalError:
                pass

    def _create_indexes(self) -> None:
        statements = [
            "CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen)",
            "CREATE INDEX IF NOT EXISTS idx_users_notify_qual_time ON users(notify_qual, notify_time)",
            "CREATE INDEX IF NOT EXISTS idx_users_notify_race_time ON users(notify_race, notify_time)",
            "CREATE INDEX IF NOT EXISTS idx_users_notify_sprint_time ON users(notify_sprint, notify_time)",
            "CREATE INDEX IF NOT EXISTS idx_users_notify_practice_time ON users(notify_practice, notify_time)",
            "CREATE INDEX IF NOT EXISTS idx_users_notify_results ON users(notify_results)",
            "CREATE INDEX IF NOT EXISTS idx_sent_notifications_sent_at ON sent_notifications(sent_at)",
        ]
        with self._lock:
            for statement in statements:
                self._conn.execute(statement)
            self._conn.commit()

    def upsert_user(self, user_id: int, username: Optional[str] = None) -> None:
        self._run(
            """
            INSERT INTO users (user_id, username)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
            """,
            (user_id, username),
        )

    def update_last_seen(self, user_id: int) -> None:
        last_seen = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._run(
            """
            INSERT INTO users (user_id, last_seen)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (user_id, last_seen),
        )

    def get_user_timezone(self, user_id: int) -> str:
        row = self._fetchone(
            "SELECT timezone FROM users WHERE user_id = ?",
            (user_id,),
        )
        tz_name = row["timezone"] if row else "UTC"
        return self._sanitize_timezone(user_id, tz_name)

    @staticmethod
    def _is_supported_timezone(tz_name: str) -> bool:
        if tz_name == "UTC":
            return True
        try:
            ZoneInfo(tz_name)
            return True
        except (ZoneInfoNotFoundError, KeyError, ValueError, TypeError):
            return False

    def _sanitize_timezone(self, user_id: int, tz_name: str) -> str:
        if self._is_supported_timezone(tz_name):
            return tz_name

        logger.warning(
            "Invalid timezone '%s' for user %d. Fallback to UTC.",
            tz_name,
            user_id,
        )
        self.set_user_timezone(user_id, "UTC")
        return "UTC"

    def set_user_timezone(self, user_id: int, timezone_name: str) -> None:
        self._run(
            """
            INSERT INTO users (user_id, timezone)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone
            """,
            (user_id, timezone_name),
        )
        logger.info("User %d timezone set to %s", user_id, timezone_name)

    def get_all_user_ids(self) -> list[int]:
        rows = self._fetchall("SELECT user_id FROM users")
        return [row["user_id"] for row in rows]

    def get_stats(self) -> dict:
        total = self._fetchone("SELECT COUNT(*) AS cnt FROM users")
        dau = self._fetchone(
            """
            SELECT COUNT(*) AS cnt FROM users
            WHERE last_seen >= datetime('now', '-1 day')
            """
        )
        wau = self._fetchone(
            """
            SELECT COUNT(*) AS cnt FROM users
            WHERE last_seen >= datetime('now', '-7 days')
            """
        )
        return {
            "total": total["cnt"] if total else 0,
            "dau": dau["cnt"] if dau else 0,
            "wau": wau["cnt"] if wau else 0,
        }

    def get_notification_settings(self, user_id: int) -> dict:
        row = self._fetchone(
            """
            SELECT notify_qual, notify_race, notify_sprint, notify_practice, notify_results, notify_time
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        )
        if row:
            return {
                "notify_qual": bool(row["notify_qual"]),
                "notify_race": bool(row["notify_race"]),
                "notify_sprint": bool(row["notify_sprint"]),
                "notify_practice": bool(row["notify_practice"]),
                "notify_results": bool(row["notify_results"]),
                "notify_time": row["notify_time"],
            }
        return {
            "notify_qual": False,
            "notify_race": False,
            "notify_sprint": False,
            "notify_practice": False,
            "notify_results": False,
            "notify_time": 60,
        }

    def set_notification(self, user_id: int, kind: str, value: bool) -> None:
        if kind not in ALLOWED_NOTIFICATION_KINDS:
            raise ValueError(f"Unsupported notification kind: {kind}")

        self._run(
            f"UPDATE users SET notify_{kind} = ? WHERE user_id = ?",
            (int(value), user_id),
        )

    def get_notify_time(self, user_id: int) -> int:
        row = self._fetchone(
            "SELECT notify_time FROM users WHERE user_id = ?",
            (user_id,),
        )
        return row["notify_time"] if row else 60

    def set_notify_time(self, user_id: int, minutes: int) -> None:
        self._run(
            "UPDATE users SET notify_time = ? WHERE user_id = ?",
            (minutes, user_id),
        )

    def get_subscribers(self, kind: str) -> list[dict]:
        if kind not in ALLOWED_NOTIFICATION_KINDS:
            raise ValueError(f"Unsupported notification kind: {kind}")

        rows = self._fetchall(
            f"SELECT user_id, timezone FROM users WHERE notify_{kind} = 1"
        )
        return [
            {
                "user_id": row["user_id"],
                "timezone": self._sanitize_timezone(row["user_id"], row["timezone"]),
            }
            for row in rows
        ]

    def get_subscribers_by_time(self, kind: str, minutes: int) -> list[dict]:
        if kind not in ALLOWED_NOTIFICATION_KINDS:
            raise ValueError(f"Unsupported notification kind: {kind}")

        rows = self._fetchall(
            f"""
            SELECT user_id, timezone
            FROM users
            WHERE notify_{kind} = 1 AND notify_time = ?
            """,
            (minutes,),
        )
        return [
            {
                "user_id": row["user_id"],
                "timezone": self._sanitize_timezone(row["user_id"], row["timezone"]),
            }
            for row in rows
        ]

    def has_sent_notification(
        self,
        season: int,
        round_number: int,
        session_key: str,
        target_minutes: int,
    ) -> bool:
        row = self._fetchone(
            """
            SELECT 1
            FROM sent_notifications
            WHERE season = ? AND round = ? AND session_key = ? AND target_minutes = ?
            """,
            (season, round_number, session_key, target_minutes),
        )
        return row is not None

    def mark_notification_sent(
        self,
        season: int,
        round_number: int,
        session_key: str,
        target_minutes: int,
    ) -> None:
        self._run(
            """
            INSERT OR IGNORE INTO sent_notifications (season, round, session_key, target_minutes)
            VALUES (?, ?, ?, ?)
            """,
            (season, round_number, session_key, target_minutes),
        )
