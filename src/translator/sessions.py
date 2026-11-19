from __future__ import annotations

import time

from .crypto import Crypto

COOKIE = "tr_session"
TTL = {"anon": 12 * 3600, "user": 30 * 86400}


def issue(crypto: Crypto, kind: str, user_id: str | None = None, now: float | None = None) -> str:
    now = time.time() if now is None else now
    return crypto.sign({"kind": kind, "uid": user_id, "exp": now + TTL[kind]})


def read(crypto: Crypto, cookie: str | None, now: float | None = None) -> dict | None:
    if not cookie:
        return None
    p = crypto.unsign(cookie)
    if p is None or p.get("kind") not in TTL or not isinstance(p.get("exp"), (int, float)):
        return None
    now = time.time() if now is None else now
    if p["exp"] < now:
        return None
    return {"kind": p["kind"], "uid": p.get("uid")}
