from __future__ import annotations

import sqlite3
import threading

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)",
    """CREATE TABLE IF NOT EXISTS styles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        prompt TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        position INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS languages (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT, created_at TEXT)",
    """CREATE TABLE IF NOT EXISTS history (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        style_label TEXT,
        language_code TEXT,
        inputs TEXT,
        output TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS history_user ON history (user_id, updated_at)",
    """CREATE TABLE IF NOT EXISTS usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,
        style_id INTEGER,
        model TEXT,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cost_eur REAL NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS usage_day ON usage (day)",
]


class _Result:
    """Rows fetched while the lock was held, so nothing touches the shared connection afterwards."""

    def __init__(self, rows, lastrowid, rowcount):
        self._rows, self.lastrowid, self.rowcount = list(rows), lastrowid, rowcount

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class LockedConnection:
    """One sqlite connection shared by worker threads: every statement runs under an RLock.

    An explicit transaction keeps the lock from BEGIN until COMMIT/ROLLBACK, so it stays atomic
    and other threads cannot interleave statements into it.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn, self._lock, self._in_tx = conn, threading.RLock(), False

    def execute(self, sql, params=()):
        word = sql.lstrip()[:8].upper()
        begin, end = word.startswith("BEGIN"), word.startswith(("COMMIT", "ROLLBACK"))
        self._lock.acquire()
        keep = False
        try:
            cur = self._conn.execute(sql, params)
            result = _Result(cur.fetchall() if cur.description else [], cur.lastrowid, cur.rowcount)
            if begin:
                self._in_tx, keep = True, True  # lock stays held until COMMIT/ROLLBACK
            return result
        finally:
            if end and self._in_tx:  # we hold the lock from BEGIN: drop that hold too
                self._in_tx = False
                self._lock.release()
            if not keep:
                self._lock.release()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def connect(path: str) -> LockedConnection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in SCHEMA:
        conn.execute(stmt)
    return LockedConnection(conn)
