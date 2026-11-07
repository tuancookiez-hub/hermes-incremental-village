"""Durable state in Hermes plugin storage (<hermes home>/plugin-data/hermes-village/data.db).

The agent half (tools, slash command) and the Desktop backend routes may run in
different processes, so every read-modify-write happens inside one
``BEGIN IMMEDIATE`` transaction on the shared SQLite file.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Callable, Iterator

PLUGIN_ID = "hermes-village"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS world (id INTEGER PRIMARY KEY CHECK (id = 1), body TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS spend (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL NOT NULL, local_date TEXT NOT NULL, game_day INTEGER NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, estimated INTEGER NOT NULL,
  provider TEXT, model TEXT, outcome TEXT NOT NULL
);
"""


def _default_connect() -> sqlite3.Connection:
    from plugins.plugin_storage import plugin_db  # public Hermes plugin storage helper
    return plugin_db(PLUGIN_ID)


class Store:
    def __init__(self, connect: Callable[[], sqlite3.Connection] = _default_connect):
        self._connect = connect
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = self._connect()
            conn.isolation_level = None  # explicit transactions only
            conn.executescript(_SCHEMA)
            self._conn = conn
        return self._conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        # One connection is shared by every worker thread, and SQLite transactions
        # cannot overlap on a connection, so each one waits its turn here.
        with self._lock:
            db = self._db()
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            else:
                db.execute("COMMIT")

    # -- world
    @staticmethod
    def load_world(db: sqlite3.Connection) -> dict | None:
        row = db.execute("SELECT body FROM world WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def save_world(db: sqlite3.Connection, world: dict) -> None:
        db.execute("INSERT INTO world (id, body, updated_at) VALUES (1, ?, ?) "
                   "ON CONFLICT(id) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
                   (json.dumps(world, separators=(",", ":")), time.time()))

    # -- settings
    @staticmethod
    def get_setting(db: sqlite3.Connection, key: str, default: Any) -> Any:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def set_setting(db: sqlite3.Connection, key: str, value: Any) -> None:
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))

    # -- spend ledger
    @staticmethod
    def record_spend(db: sqlite3.Connection, *, game_day: int, input_tokens: int, output_tokens: int,
                     estimated: bool, provider: str | None, model: str | None, outcome: str) -> None:
        db.execute("INSERT INTO spend (at, local_date, game_day, input_tokens, output_tokens, estimated, "
                   "provider, model, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (time.time(), date.today().isoformat(), game_day, int(input_tokens), int(output_tokens),
                    int(estimated), provider, model, outcome))

    @staticmethod
    def spend_today(db: sqlite3.Connection) -> tuple[int, int]:
        row = db.execute("SELECT COALESCE(SUM(input_tokens + output_tokens), 0), COUNT(*) FROM spend "
                         "WHERE local_date = ?", (date.today().isoformat(),)).fetchone()
        return int(row[0]), int(row[1])

    @staticmethod
    def last_spend(db: sqlite3.Connection) -> dict | None:
        row = db.execute("SELECT input_tokens, output_tokens, estimated, provider, model, game_day, outcome "
                         "FROM spend ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"input_tokens": row[0], "output_tokens": row[1], "estimated": bool(row[2]),
                "provider": row[3], "model": row[4], "day": row[5], "outcome": row[6]}
