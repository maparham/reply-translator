from __future__ import annotations

import json
import math
import sqlite3

from .crypto import Crypto


class Settings:
    def __init__(self, conn: sqlite3.Connection, crypto: Crypto):
        self._conn = conn
        self._crypto = crypto

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return default if row is None or row[0] is None else row[0]

    def set(self, key: str, value: str | None) -> None:
        if value is None:
            self._conn.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_secret(self, name: str) -> str | None:
        token = self.get(name)
        return None if token is None else self._crypto.decrypt(token)

    def set_secret(self, name: str, value: str | None) -> None:
        self.set(name, None if value is None else self._crypto.encrypt(value))

    def secret_hint(self, name: str) -> str | None:
        value = self.get_secret(name)
        return value[-4:] if value else None

    def enabled(self) -> bool:
        return self.get("enabled", "1") == "1"

    def cap_eur(self) -> float | None:
        raw = self.get("cap_eur")
        if raw is None or raw == "":
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        return value if math.isfinite(value) else None

    def prices(self) -> dict[str, dict]:
        raw = self.get("prices")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
