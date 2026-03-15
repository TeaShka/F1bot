"""
Модуль работы с базой данных SQLite.
Хранит ID пользователей, их часовые пояса и настройки уведомлений.
"""

import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с SQLite базой данных."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Создаёт и возвращает соединение с БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # возвращаем строки как dict-подобные объекты
        return conn

    def _init_db(self) -> None:
        """Инициализирует схему базы данных при первом запуске."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT,
                    timezone    TEXT    NOT NULL DEFAULT 'UTC',
                    notify_qual INTEGER NOT NULL DEFAULT 0,  -- уведомление перед квалификацией
                    notify_race INTEGER NOT NULL DEFAULT 0,  -- уведомление перед гонкой
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
        logger.info("База данных инициализирована: %s", self.db_path)

    # ── Пользователи ──────────────────────────────────────────────────────────

    def upsert_user(self, user_id: int, username: Optional[str] = None) -> None:
        """Создаёт запись пользователя или обновляет username, если она уже есть."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO users (user_id, username)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
            """, (user_id, username))
            conn.commit()

    def get_user_timezone(self, user_id: int) -> str:
        """Возвращает часовой пояс пользователя (по умолчанию UTC)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT timezone FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["timezone"] if row else "UTC"

    def set_user_timezone(self, user_id: int, timezone: str) -> None:
        """Сохраняет часовой пояс пользователя."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO users (user_id, timezone)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone
            """, (user_id, timezone))
            conn.commit()
        logger.info("Пользователь %d: установлен часовой пояс %s", user_id, timezone)

    # ── Уведомления ───────────────────────────────────────────────────────────

    def get_notification_settings(self, user_id: int) -> dict:
        """Возвращает настройки уведомлений пользователя."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT notify_qual, notify_race FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        if row:
            return {"notify_qual": bool(row["notify_qual"]),
                    "notify_race": bool(row["notify_race"])}
        return {"notify_qual": False, "notify_race": False}

    def set_notification(self, user_id: int, kind: str, value: bool) -> None:
        """
        Включает/выключает уведомление для пользователя.

        :param kind: 'qual' или 'race'
        :param value: True = включить, False = выключить
        """
        column = f"notify_{kind}"
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE users SET {column} = ? WHERE user_id = ?",
                (int(value), user_id)
            )
            conn.commit()

    def get_subscribers(self, kind: str) -> list[dict]:
        """
        Возвращает список пользователей, подписанных на уведомления.

        :param kind: 'qual' или 'race'
        """
        column = f"notify_{kind}"
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT user_id, timezone FROM users WHERE {column} = 1"
            ).fetchall()
        return [dict(row) for row in rows]
