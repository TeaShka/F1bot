"""
SQLite-backed FSM storage for aiogram.
"""

from __future__ import annotations

import json
import sqlite3
from threading import RLock
from typing import Any

from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey


class SQLiteStorage(BaseStorage):
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

    def _configure_connection(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.commit()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fsm_storage (
                    bot_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL DEFAULT 0,
                    business_connection_id TEXT NOT NULL DEFAULT '',
                    destiny TEXT NOT NULL DEFAULT 'default',
                    state TEXT,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (
                        bot_id,
                        chat_id,
                        user_id,
                        thread_id,
                        business_connection_id,
                        destiny
                    )
                )
                """
            )
            self._conn.commit()

    async def close(self) -> None:
        with self._lock:
            self._conn.close()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_value = self._resolve_state(state)
        _, current_data = self._read_record(key)
        if state_value is None and not current_data:
            self._delete_record(key)
            return
        self._write_record(key, state_value, current_data)

    async def get_state(self, key: StorageKey) -> str | None:
        state_value, _ = self._read_record(key)
        return state_value

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        normalized = dict(data or {})
        current_state, _ = self._read_record(key)
        if current_state is None and not normalized:
            self._delete_record(key)
            return
        self._write_record(key, current_state, normalized)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        _, data = self._read_record(key)
        return data

    async def update_data(self, key: StorageKey, data: dict[str, Any]) -> dict[str, Any]:
        current = await self.get_data(key)
        current.update(data)
        await self.set_data(key, current)
        return current

    def _resolve_state(self, state: StateType = None) -> str | None:
        if state is None:
            return None
        if hasattr(state, "state"):
            return state.state
        return str(state)

    def _key_parts(self, key: StorageKey) -> tuple[int, int, int, int, str, str]:
        return (
            int(getattr(key, "bot_id", 0) or 0),
            int(getattr(key, "chat_id", 0) or 0),
            int(getattr(key, "user_id", 0) or 0),
            int(getattr(key, "thread_id", 0) or 0),
            str(getattr(key, "business_connection_id", "") or ""),
            str(getattr(key, "destiny", "default") or "default"),
        )

    def _read_record(self, key: StorageKey) -> tuple[str | None, dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT state, data
                FROM fsm_storage
                WHERE bot_id = ?
                  AND chat_id = ?
                  AND user_id = ?
                  AND thread_id = ?
                  AND business_connection_id = ?
                  AND destiny = ?
                """,
                self._key_parts(key),
            ).fetchone()

        if row is None:
            return None, {}

        return row["state"], self._loads(row["data"])

    def _write_record(
        self,
        key: StorageKey,
        state: str | None,
        data: dict[str, Any],
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO fsm_storage (
                    bot_id,
                    chat_id,
                    user_id,
                    thread_id,
                    business_connection_id,
                    destiny,
                    state,
                    data,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(
                    bot_id,
                    chat_id,
                    user_id,
                    thread_id,
                    business_connection_id,
                    destiny
                ) DO UPDATE SET
                    state = excluded.state,
                    data = excluded.data,
                    updated_at = datetime('now')
                """,
                (
                    *self._key_parts(key),
                    state,
                    self._dumps(data),
                ),
            )
            self._conn.commit()

    def _delete_record(self, key: StorageKey) -> None:
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM fsm_storage
                WHERE bot_id = ?
                  AND chat_id = ?
                  AND user_id = ?
                  AND thread_id = ?
                  AND business_connection_id = ?
                  AND destiny = ?
                """,
                self._key_parts(key),
            )
            self._conn.commit()

    def _loads(self, payload: str) -> dict[str, Any]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _dumps(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
