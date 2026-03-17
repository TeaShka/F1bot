"""
Модуль работы с базой данных SQLite.
"""

import sqlite3
import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class Database:

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()
        self._upgrade_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT,
                    timezone    TEXT    NOT NULL DEFAULT 'UTC',
                    notify_qual INTEGER NOT NULL DEFAULT 0,
                    notify_race INTEGER NOT NULL DEFAULT 0,
                    notify_time INTEGER NOT NULL DEFAULT 60,
                    last_seen   TEXT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
        logger.info("База данных инициализирована: %s", self.db_path)

    def _upgrade_db(self) -> None:
        """Добавляет новые колонки в существующую таблицу без потери данных."""
        columns_to_add = [
            ("notify_time", "INTEGER NOT NULL DEFAULT 60"),
            ("last_seen",   "TEXT"),
        ]
        with self._get_connection() as conn:
            for col_name, col_def in columns_to_add:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                    conn.commit()
                    logger.info("БД обновлена: добавлена колонка %s", col_name)
                except sqlite3.OperationalError:
                    pass  # колонка уже существует

    # ── Пользователи ──────────────────────────────────────────────────────────

    def upsert_user(self, user_id: int, username: Optional[str] = None) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO users (user_id, username)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
            """, (user_id, username))
            conn.commit()

    def update_last_seen(self, user_id: int) -> None:
        """Обновляет время последней активности пользователя."""
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET last_seen = ? WHERE user_id = ?",
                (now, user_id)
            )
            conn.commit()

    def get_user_timezone(self, user_id: int) -> str:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT timezone FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["timezone"] if row else "UTC"

    def set_user_timezone(self, user_id: int, timezone: str) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO users (user_id, timezone)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone
            """, (user_id, timezone))
            conn.commit()
        logger.info("Пользователь %d: установлен часовой пояс %s", user_id, timezone)

    def get_all_user_ids(self) -> list[int]:
        """Возвращает ID всех пользователей для рассылки."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [row["user_id"] for row in rows]

    def get_stats(self) -> dict:
        """Возвращает статистику пользователей."""
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
            dau = conn.execute("""
                SELECT COUNT(*) as cnt FROM users
                WHERE last_seen >= datetime('now', '-1 day')
            """).fetchone()["cnt"]
            wau = conn.execute("""
                SELECT COUNT(*) as cnt FROM users
                WHERE last_seen >= datetime('now', '-7 days')
            """).fetchone()["cnt"]
        return {"total": total, "dau": dau, "wau": wau}

    # ── Уведомления ───────────────────────────────────────────────────────────

    def get_notification_settings(self, user_id: int) -> dict:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT notify_qual, notify_race, notify_time FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        if row:
            return {
                "notify_qual": bool(row["notify_qual"]),
                "notify_race": bool(row["notify_race"]),
                "notify_time": row["notify_time"] if "notify_time" in row.keys() else 60,
            }
        return {"notify_qual": False, "notify_race": False, "notify_time": 60}

    def set_notification(self, user_id: int, kind: str, value: bool) -> None:
        column = f"notify_{kind}"
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE users SET {column} = ? WHERE user_id = ?",
                (int(value), user_id)
            )
            conn.commit()

    def get_notify_time(self, user_id: int) -> int:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT notify_time FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["notify_time"] if row and "notify_time" in row.keys() else 60

    def set_notify_time(self, user_id: int, minutes: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET notify_time = ? WHERE user_id = ?",
                (minutes, user_id)
            )
            conn.commit()

    def get_subscribers(self, kind: str) -> list[dict]:
        column = f"notify_{kind}"
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT user_id, timezone FROM users WHERE {column} = 1"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_subscribers_by_time(self, kind: str, minutes: int) -> list[dict]:
        column = f"notify_{kind}"
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT user_id, timezone FROM users WHERE {column} = 1 AND notify_time = ?",
                (minutes,)
            ).fetchall()
        return [dict(row) for row in rows]