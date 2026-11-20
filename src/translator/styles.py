from __future__ import annotations

import sqlite3
from dataclasses import dataclass

PROVIDERS = ("anthropic", "openai")

_FIELDS = ("label", "description", "prompt", "provider", "model", "active")


@dataclass
class Style:
    id: int
    label: str
    description: str
    prompt: str
    provider: str
    model: str
    active: bool
    position: int


_SEED_MODEL = "claude-sonnet-5-5"

_SEED_STYLES = [
    (
        "Official",
        "Formal and polite, for authorities, landlords, schools and doctors",
        """Write in a formal, courteous register suitable for authorities, landlords, schools, doctors and other official contacts in Austria.
Address the other person with "Sie" throughout, in complete, well-structured sentences. Be polite and clear; state the request or answer directly without sounding cold.
When the message has a greeting and closing (only if the input has them, see the general rules): greet with the recipient's exact name and title when the received message gives one (e.g. "Sehr geehrte Frau Mag. Huber"), otherwise "Sehr geehrte Damen und Herren", and close with "Mit freundlichen Grüßen".
Use standard Austrian vocabulary where it fits, e.g. "Jänner" instead of "Januar", "Termin" for appointments; use "Ordination" only when writing to a doctor's practice.
No slang, no colloquial contractions (not "gibt's", "hab'", "ham"), no emojis.
Never invent names, dates, numbers or facts that are not in the input, and never output placeholders of any kind (no bracketed names, no ellipses standing in for missing text, no slash forms for titles).""",
    ),
    (
        "Friendly",
        "Warm and casual, like a chat message",
        """Write in a warm, natural tone, like a friendly WhatsApp message in Austria.
Use "du" by default, but use "Sie" if the received message uses "Sie". If there is a greeting (only if the input has one, see the general rules): with "Sie" use "Guten Tag" or "Grüß Gott", never "Servus" or "Hallo"; keep "Servus" for people the user clearly knows well.
Keep sentences short and conversational; light colloquial phrasing is fine, but nothing sloppy or rude. If there is a sign-off, use "Liebe Grüße".
Use Austrian vocabulary where it fits, e.g. "Jänner" instead of "Januar", "passt" for agreement.
At most one emoji, and only where it truly fits.
Never invent names, dates, numbers or facts that are not in the input, and never output placeholders of any kind (no bracketed names, no ellipses standing in for missing text).""",
    ),
    (
        "Neutral",
        "Plain and polite, neither stiff nor chatty",
        """Write in a plain, polite and matter-of-fact tone.
Address the other person with "Sie". Add no extra warmth and no stiff formality: no flowery phrases, no small talk.
Keep it short: the essential content. If there is a greeting and closing (only if the input has them, see the general rules), keep them brief, e.g. "Guten Tag" and "Freundliche Grüße".
Use Austrian vocabulary where relevant, e.g. "Jänner" instead of "Januar".
No emojis.
Never invent names, dates, numbers or facts that are not in the input, and never output placeholders of any kind (no bracketed names, no ellipses standing in for missing text).""",
    ),
]


def _row(r: sqlite3.Row) -> Style:
    return Style(r["id"], r["label"], r["description"], r["prompt"], r["provider"], r["model"], bool(r["active"]), r["position"])


def _validate(fields: dict) -> None:
    if "provider" in fields and fields["provider"] not in PROVIDERS:
        raise ValueError(f"provider must be one of {PROVIDERS}")
    for k in ("label", "prompt", "model"):
        if k in fields and not (isinstance(fields[k], str) and fields[k].strip()):
            raise ValueError(f"{k} must not be empty")


def seed(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        if (
            conn.execute("SELECT COUNT(*) FROM styles").fetchone()[0]
            or conn.execute("SELECT COUNT(*) FROM languages").fetchone()[0]
        ):
            conn.execute("ROLLBACK")
            return
        for label, description, prompt in _SEED_STYLES:
            _insert_style(conn, label, description, prompt, "anthropic", _SEED_MODEL, True)
        _replace_languages(conn, [{"code": "de-AT", "name": "German (Austria)"}])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def list_styles(conn: sqlite3.Connection, active_only: bool) -> list[Style]:
    sql = "SELECT * FROM styles"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY position, id"
    return [_row(r) for r in conn.execute(sql)]


def get_style(conn: sqlite3.Connection, id: int) -> Style | None:
    r = conn.execute("SELECT * FROM styles WHERE id = ?", (id,)).fetchone()
    return _row(r) if r else None


def create_style(conn, label, description, prompt, provider, model, active=True) -> Style:
    _validate({"label": label, "prompt": prompt, "provider": provider, "model": model})
    return _insert_style(conn, label, description, prompt, provider, model, active)


def _insert_style(conn, label, description, prompt, provider, model, active) -> Style:
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM styles").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO styles (label, description, prompt, provider, model, active, position) VALUES (?,?,?,?,?,?,?)",
        (label.strip(), description or "", prompt, provider, model.strip(), int(bool(active)), pos),
    )
    return get_style(conn, cur.lastrowid)


def update_style(conn, id: int, **fields) -> Style | None:
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    _validate(fields)
    if get_style(conn, id) is None:
        return None
    if fields:
        if "description" in fields and fields["description"] is None:
            fields["description"] = ""
        if "active" in fields:
            fields["active"] = int(bool(fields["active"]))
        for k in ("label", "model"):
            if k in fields:
                fields[k] = fields[k].strip()
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE styles SET {sets} WHERE id = ?", (*fields.values(), id))
    return get_style(conn, id)


def delete_style(conn: sqlite3.Connection, id: int) -> bool:
    return conn.execute("DELETE FROM styles WHERE id = ?", (id,)).rowcount > 0


def reorder_styles(conn: sqlite3.Connection, ids: list[int]) -> None:
    conn.execute("BEGIN")
    try:
        for pos, sid in enumerate(ids):
            conn.execute("UPDATE styles SET position = ? WHERE id = ?", (pos, sid))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def list_languages(conn: sqlite3.Connection) -> list[dict]:
    return [{"code": r["code"], "name": r["name"]} for r in conn.execute("SELECT code, name FROM languages ORDER BY position, code")]


def _replace_languages(conn: sqlite3.Connection, items: list[dict]) -> None:
    seen = set()
    for it in items:
        code, name = it.get("code"), it.get("name")
        if not (isinstance(code, str) and code.strip() and isinstance(name, str) and name.strip()):
            raise ValueError("language code and name must not be empty")
        if code in seen:
            raise ValueError(f"duplicate language code: {code}")
        seen.add(code)
    conn.execute("DELETE FROM languages")
    for pos, it in enumerate(items):
        conn.execute("INSERT INTO languages (code, name, position) VALUES (?,?,?)", (it["code"].strip(), it["name"].strip(), pos))


def set_languages(conn: sqlite3.Connection, items: list[dict]) -> None:
    conn.execute("BEGIN")
    try:
        _replace_languages(conn, items)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
