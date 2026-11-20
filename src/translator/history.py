from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

MAX_ITEMS = 200
MAX_TEXT = 8000
MAX_LABEL = 100
INPUT_FIELDS = ("text", "received", "my_language")
OUTPUT_FIELDS = ("received_gist", "message", "back_translation")


def _now(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save(conn: sqlite3.Connection, user_id: str, item_id: str | None, style_label: str, language_code: str,
         inputs: dict, output: dict, now: datetime | None = None) -> str:
    ts = _now(now)
    if item_id is not None:
        row = conn.execute("SELECT user_id FROM history WHERE id=?", (item_id,)).fetchone()
        if row is not None:
            if row["user_id"] != user_id:
                raise PermissionError(item_id)
            conn.execute("UPDATE history SET output=?, inputs=?, updated_at=?, style_label=?, language_code=? "
                         "WHERE id=? AND user_id=?",
                         (json.dumps(output), json.dumps(inputs), ts, style_label, language_code, item_id, user_id))
            return item_id
    new_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO history (id, user_id, created_at, updated_at, style_label, language_code, inputs, output) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id, user_id, ts, ts, style_label, language_code, json.dumps(inputs), json.dumps(output)))
    prune(conn, user_id)
    return new_id


def prune(conn: sqlite3.Connection, user_id: str) -> None:
    """Keep only the user's newest MAX_ITEMS items (the most the app ever shows), so history can't grow unbounded."""
    conn.execute(
        "DELETE FROM history WHERE user_id=? AND id NOT IN (SELECT id FROM history WHERE user_id=? "
        "ORDER BY updated_at DESC, created_at DESC LIMIT ?)", (user_id, user_id, MAX_ITEMS))


def list_items(conn: sqlite3.Connection, user_id: str, limit: int = MAX_ITEMS) -> list[dict]:
    rows = conn.execute(
        "SELECT id, created_at, updated_at, style_label, language_code, inputs, output FROM history "
        "WHERE user_id=? ORDER BY updated_at DESC, created_at DESC LIMIT ?", (user_id, limit)).fetchall()
    return [{**{k: r[k] for k in ("id", "created_at", "updated_at", "style_label", "language_code")},
             "inputs": json.loads(r["inputs"] or "{}"), "output": json.loads(r["output"] or "{}")} for r in rows]


def delete(conn: sqlite3.Connection, user_id: str, item_id: str) -> bool:
    return conn.execute("DELETE FROM history WHERE id=? AND user_id=?", (item_id, user_id)).rowcount > 0


def delete_all(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute("DELETE FROM history WHERE user_id=?", (user_id,)).rowcount


def _str(value, limit: int) -> str | None:
    """Missing -> "", non-string or too long -> None (invalid)."""
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        return None
    return value


def _timestamp(value, fallback: str) -> str | None:
    if value is None or value == "":
        return fallback
    if not isinstance(value, str) or len(value) > MAX_LABEL:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return _now(dt)
    except (ValueError, OverflowError):  # OverflowError: a date at the edge of the calendar, e.g. year 1 at +01:00
        return None


def _valid(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    try:
        item_id = str(uuid.UUID(item["id"])) if isinstance(item.get("id"), str) else None
    except ValueError:
        item_id = None
    if item_id is None:
        return None
    inputs, output = item.get("inputs"), item.get("output")
    if not isinstance(inputs, dict) or not isinstance(output, dict):
        return None
    clean_in = {k: _str(inputs.get(k), MAX_TEXT) for k in INPUT_FIELDS}
    clean_out = {k: _str(output.get(k), MAX_TEXT) for k in OUTPUT_FIELDS}
    label = _str(item.get("style_label"), MAX_LABEL)
    code = _str(item.get("language_code"), MAX_LABEL)
    created = _timestamp(item.get("created_at"), _now(None))
    if created is None:
        return None
    updated = _timestamp(item.get("updated_at"), created)
    if updated is None or None in clean_in.values() or None in clean_out.values() or None in (label, code):
        return None
    return {"id": item_id, "created_at": created, "updated_at": updated, "style_label": label,
            "language_code": code, "inputs": clean_in, "output": clean_out}


def import_items(conn: sqlite3.Connection, user_id: str, items: list[dict]) -> int:
    imported = 0
    for raw in items:
        item = _valid(raw)
        if item is None:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO history (id, user_id, created_at, updated_at, style_label, language_code, "
            "inputs, output) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item["id"], user_id, item["created_at"], item["updated_at"], item["style_label"],
             item["language_code"], json.dumps(item["inputs"]), json.dumps(item["output"])))
        imported += cur.rowcount
    prune(conn, user_id)
    return imported
