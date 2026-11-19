from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    app_url: str
    secret_key: str
    clerk_publishable_key: str
    clerk_secret_key: str
    admin_emails: frozenset[str]
    db_path: str
    host: str
    port: int


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable {name}")
    return value


def from_env() -> Config:
    admin_emails = frozenset(
        e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
    )
    return Config(
        app_url=_required("APP_URL").rstrip("/"),
        secret_key=_required("APP_SECRET_KEY"),
        clerk_publishable_key=os.environ.get("CLERK_PUBLISHABLE_KEY", ""),
        clerk_secret_key=os.environ.get("CLERK_SECRET_KEY", ""),
        admin_emails=admin_emails,
        db_path=os.environ.get("TRANSLATOR_DB", "/data/translator.db"),
        host=os.environ.get("TRANSLATOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("TRANSLATOR_PORT", "18490")),
    )
