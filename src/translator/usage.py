from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .providers import Usage
from .settings import Settings

VIENNA = ZoneInfo("Europe/Vienna")


def today(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(VIENNA).date().isoformat()


def cost_eur(prices: dict, model: str, usage: Usage) -> float:
    p = prices.get(model)
    if not isinstance(p, dict):
        return 0.0
    try:
        return (
            usage.input_tokens * float(p.get("in", 0)) + usage.output_tokens * float(p.get("out", 0))
        ) / 1_000_000
    except (TypeError, ValueError):
        return 0.0


def record(
    conn: sqlite3.Connection,
    settings: Settings,
    style_id: int | None,
    model: str,
    usage: Usage,
    now: datetime | None = None,
) -> None:
    cost = cost_eur(settings.prices(), model, usage)
    conn.execute(
        "INSERT INTO usage (day, style_id, model, input_tokens, output_tokens, cost_eur) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (today(now), style_id, model, usage.input_tokens, usage.output_tokens, cost),
    )


def spent_today(conn: sqlite3.Connection, now: datetime | None = None) -> float:
    row = conn.execute("SELECT COALESCE(SUM(cost_eur), 0) FROM usage WHERE day=?", (today(now),)).fetchone()
    return float(row[0])


def cap_reached(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> bool:
    cap = settings.cap_eur()
    return cap is not None and spent_today(conn, now) >= cap


def summary(conn: sqlite3.Connection, settings: Settings, days: int = 30) -> dict:
    day_rows = conn.execute(
        "SELECT day, COUNT(*) AS requests, SUM(cost_eur) AS cost_eur FROM usage "
        "GROUP BY day ORDER BY day DESC LIMIT ?",
        (days,),
    ).fetchall()
    day_list = [{"day": r["day"], "requests": r["requests"], "cost_eur": r["cost_eur"]} for r in day_rows]
    since = day_list[-1]["day"] if day_list else None

    by_style: list[dict] = []
    used_models: set[str] = set()
    if since is not None:
        for r in conn.execute(
            "SELECT u.style_id AS style_id, s.label AS label, COUNT(*) AS requests, "
            "SUM(u.cost_eur) AS cost_eur FROM usage u LEFT JOIN styles s ON s.id = u.style_id "
            "WHERE u.day >= ? GROUP BY u.style_id ORDER BY cost_eur DESC, requests DESC",
            (since,),
        ):
            label = "Try it" if r["style_id"] is None else (r["label"] or "(deleted)")
            by_style.append(
                {"style_id": r["style_id"], "label": label, "requests": r["requests"], "cost_eur": r["cost_eur"]}
            )
        used_models = {
            r[0] for r in conn.execute("SELECT DISTINCT model FROM usage WHERE day >= ?", (since,)) if r[0]
        }
    active_models = {r[0] for r in conn.execute("SELECT DISTINCT model FROM styles WHERE active=1")}
    prices = settings.prices()
    return {
        "days": day_list,
        "by_style": by_style,
        "spent_today": spent_today(conn),
        "unpriced_models": sorted((used_models | active_models) - set(prices)),
    }
