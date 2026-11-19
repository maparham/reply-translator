from __future__ import annotations

import json
import math
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool, StrictInt, StrictStr
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect

from . import clerk as clerk_mod
from . import db, frame, history, providers, sessions, styles, turnstile, usage
from .config import Config
from .crypto import Crypto
from .settings import Settings

STATIC = Path(__file__).parent / "static"
MAX_CHARS = 8000


class PreviousIn(BaseModel):
    received_gist: StrictStr
    message: StrictStr
    back_translation: StrictStr


class GenerateIn(BaseModel):
    style_id: StrictInt
    language_code: StrictStr
    my_language: StrictStr
    text: StrictStr
    received: StrictStr | None = None
    save: StrictBool = False
    history_id: StrictStr | None = None


class TweakIn(GenerateIn):
    tweak: StrictStr
    previous: PreviousIn


class TryIn(BaseModel):
    prompt: StrictStr
    provider: StrictStr
    model: StrictStr
    language_code: StrictStr
    my_language: StrictStr
    text: StrictStr
    received: StrictStr | None = None


def is_open(conn, settings: Settings) -> bool:
    return bool(
        settings.enabled()
        and settings.get("turnstile_site_key")
        and settings.get_secret("turnstile_secret")
        and not usage.cap_reached(conn, settings)
    )


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, csp: str, allowed_origin: str):
        super().__init__(app)
        self.csp, self.allowed_origin = csp, allowed_origin

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin is None or origin.rstrip("/").lower() != self.allowed_origin:
                return _err(403, "Bad origin")
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = self.csp
        return resp


MAX_BODY_BYTES = 256 * 1024


class BodyLimitMiddleware:
    """Pure-ASGI request body cap: rejects by Content-Length, and counts bytes for chunked bodies."""

    def __init__(self, app, limit: int = MAX_BODY_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.limit
            except ValueError:
                too_big = False
            if too_big:
                await self._reject(send)
                return
        seen = 0
        over = False

        async def counting_receive():
            nonlocal seen, over
            if over:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.limit:
                    over = True
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg):
            if not over:  # once over the limit, whatever the app says about the truncated body is dropped
                await send(msg)

        try:
            await self.app(scope, counting_receive, guarded_send)
        finally:
            if over:
                await self._reject(send)


    @staticmethod
    async def _reject(send):
        payload = b'{"error":"Request too large"}'
        await send({"type": "http.response.start", "status": 413, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
            (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": payload})


def _csp(fapi: str | None) -> str:
    host = f" https://{fapi}" if fapi else ""
    return (
        f"default-src 'self'; script-src 'self'{host} https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' data:{host} https://img.clerk.com; "
        f"connect-src 'self'{host}; frame-src https://challenges.cloudflare.com; worker-src 'self' blob:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )


def create_app(cfg: Config, http: httpx.AsyncClient | None = None, generate=providers.generate,
               verify_turnstile=turnstile.verify, clerk_verifier=None) -> FastAPI:
    conn = db.connect(cfg.db_path)
    styles.seed(conn)
    crypto = Crypto(cfg.secret_key)
    settings = Settings(conn, crypto)
    owns_http = http is None
    http = http or httpx.AsyncClient(timeout=60.0)
    if clerk_verifier is None and cfg.clerk_publishable_key and cfg.clerk_secret_key:
        clerk_verifier = clerk_mod.Verifier(cfg.clerk_publishable_key, cfg.clerk_secret_key, cfg.app_url, http)
    fapi = clerk_mod.frontend_api(cfg.clerk_publishable_key) if cfg.clerk_publishable_key else None
    secure = cfg.app_url.lower().startswith("https")

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if owns_http:
            await http.aclose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.cfg, app.state.conn, app.state.crypto = cfg, conn, crypto
    app.state.settings, app.state.http = settings, http
    app.state.generate, app.state.clerk = generate, clerk_verifier
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(SecurityMiddleware, csp=_csp(fapi), allowed_origin=_origin(cfg.app_url))

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request, exc: StarletteHTTPException):
        return _err(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc):
        return _err(400, "Invalid request")

    def current_session(request: Request) -> dict | None:
        return sessions.read(crypto, request.cookies.get(sessions.COOKIE))

    def require_session(request: Request) -> dict:
        s = current_session(request)
        if s is None:
            raise HTTPException(401, "Session expired, reload the page")
        return s

    def require_user(request: Request) -> dict:
        s = current_session(request)
        if s is None or s["kind"] != "user" or not s["uid"]:
            raise HTTPException(401, "Please sign in")
        return s

    def _user_email(s: dict | None) -> str | None:
        if not s or s["kind"] != "user":
            return None
        row = conn.execute("SELECT email FROM users WHERE id=?", (s["uid"],)).fetchone()
        return row["email"].lower() if row and row["email"] else None

    def require_admin(request: Request) -> dict:
        s = current_session(request)
        email = _user_email(s)
        if email is None or email not in cfg.admin_emails:
            raise HTTPException(403, "Admins only")
        return s

    app.state.current_session, app.state.require_session = current_session, require_session
    app.state.require_admin, app.state.require_user = require_admin, require_user

    def set_cookie(resp: JSONResponse, kind: str, uid: str | None = None) -> None:
        resp.set_cookie(sessions.COOKIE, sessions.issue(crypto, kind, uid), max_age=sessions.TTL[kind],
                        path="/", httponly=True, samesite="lax", secure=secure)

    async def _json(request: Request) -> dict:
        try:
            data = await request.json()
        except ClientDisconnect:  # body cap aborted the stream; BodyLimitMiddleware answers 413
            raise HTTPException(413, "Request too large") from None
        except ValueError:
            raise HTTPException(400, "Invalid request") from None
        if not isinstance(data, dict):
            raise HTTPException(400, "Invalid request")
        return data

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/admin")
    def admin_page():
        return FileResponse(STATIC / "admin.html")

    @app.get("/api/config")
    def config(request: Request):
        email = _user_email(current_session(request))
        return {
            "open": is_open(conn, settings),
            "turnstile_site_key": settings.get("turnstile_site_key"),
            "clerk_publishable_key": cfg.clerk_publishable_key or None,
            "styles": [{"id": s.id, "label": s.label, "description": s.description}
                       for s in styles.list_styles(conn, active_only=True)],
            "languages": styles.list_languages(conn),
            "my_languages": list(frame.MY_LANGUAGES),
            "tweaks": [{"id": k, "label": v[0]} for k, v in frame.TWEAKS.items()],
            "user": {"email": email, "is_admin": email in cfg.admin_emails} if email else None,
        }

    @app.post("/api/session")
    async def session(request: Request):
        token = (await _json(request)).get("turnstile_token")
        secret = settings.get_secret("turnstile_secret")
        if not isinstance(token, str) or not token or not secret:
            raise HTTPException(403, "Verification failed")
        ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)
        try:
            ok = await verify_turnstile(secret, token, ip)
        except turnstile.TurnstileUnavailable:
            raise HTTPException(503, "Verification unavailable, try again") from None
        if not ok:
            raise HTTPException(403, "Verification failed")
        resp = JSONResponse({"ok": True})
        set_cookie(resp, "anon")
        return resp

    @app.post("/api/login/clerk")
    async def login_clerk(request: Request):
        token = (await _json(request)).get("token")
        if clerk_verifier is None:
            raise HTTPException(503, "Sign-in is not configured")
        try:
            if not isinstance(token, str) or not token:
                raise clerk_mod.ClerkError("missing token")
            uid = (await clerk_verifier.verify(token))["sub"]
            email = await clerk_verifier.email(uid)
        except (clerk_mod.ClerkError, httpx.HTTPError, KeyError):
            raise HTTPException(401, "Sign-in failed") from None
        conn.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET email=excluded.email",
            (uid, email, datetime.now(timezone.utc).isoformat()))
        resp = JSONResponse({"email": email, "is_admin": email.lower() in cfg.admin_emails})
        set_cookie(resp, "user", uid)
        return resp

    @app.post("/api/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(sessions.COOKIE, path="/")
        return resp

    def require_open(_: dict = Depends(require_session)) -> dict:
        if not is_open(conn, settings):
            raise HTTPException(503, "Temporarily unavailable")
        return _

    def _maybe_save(session: dict, req, style_label: str, language_code: str, output: frame.Output) -> str | None:
        if session["kind"] != "user" or not session["uid"] or not req.save:
            return None
        inputs = {"text": req.text, "received": req.received or "", "my_language": req.my_language}
        try:
            return history.save(conn, session["uid"], req.history_id, style_label, language_code,
                                inputs, output.to_dict())
        except PermissionError:
            # Not the caller's item: don't fail their tweak, store it as a new item instead.
            return history.save(conn, session["uid"], None, style_label, language_code,
                                inputs, output.to_dict())

    app.state.maybe_save = _maybe_save

    def _check_inputs(req, previous: PreviousIn | None) -> str:
        """Validate shared request fields; returns the target language name."""
        fields = [req.text, req.received or ""]
        if previous is not None:
            fields += [previous.message, previous.back_translation, previous.received_gist]
        if any(len(f) > MAX_CHARS for f in fields):
            raise HTTPException(400, "Text is too long (max 8000 characters)")
        if previous is None and not req.text.strip():
            raise HTTPException(400, "Please write what you want to say")
        if req.my_language not in frame.MY_LANGUAGES:
            raise HTTPException(400, "Unknown language")
        language = next((l["name"] for l in styles.list_languages(conn) if l["code"] == req.language_code), None)
        if language is None:
            raise HTTPException(400, "Unknown language")
        return language

    async def _call(req, language: str, style_prompt: str, provider: str, api_key: str, model: str,
                    style_id: int | None, tweak: str | None, previous: PreviousIn | None) -> frame.Output:
        if tweak is not None and tweak not in frame.TWEAKS:
            raise HTTPException(400, "Unknown change")
        reply_mode = bool((req.received or "").strip())
        system, user = frame.build_prompt(
            style_prompt, language, req.my_language, req.text, req.received,
            frame.Output(**previous.model_dump()) if previous else None, tweak)
        try:
            gen = await app.state.generate(provider, api_key, model, system, user, frame.OUTPUT_SCHEMA, http)
        except providers.ProviderError:
            raise HTTPException(502, "Couldn't generate, try again") from None
        usage.record(conn, settings, style_id, model, gen.usage)
        try:
            return frame.parse_output(gen.data, reply_mode)
        except frame.FrameError:
            raise HTTPException(502, "Couldn't generate, try again") from None

    async def _run(session: dict, req: GenerateIn, tweak: str | None = None,
                   previous: PreviousIn | None = None) -> dict:
        language = _check_inputs(req, previous)
        style = styles.get_style(conn, req.style_id)
        if style is None or not style.active:
            raise HTTPException(400, "This style is not available")
        api_key = settings.get_secret(f"{style.provider}_api_key")
        if not api_key:
            raise HTTPException(400, "This style is not configured yet")
        output = await _call(req, language, style.prompt, style.provider, api_key, style.model,
                             style.id, tweak, previous)
        history_id = _maybe_save(session, req, style.label, req.language_code, output)
        return {"result": output.to_dict(), "history_id": history_id}

    @app.post("/api/generate")
    async def generate_endpoint(req: GenerateIn, session: dict = Depends(require_open)):
        return await _run(session, req)

    @app.post("/api/tweak")
    async def tweak_endpoint(req: TweakIn, session: dict = Depends(require_open)):
        return await _run(session, req, req.tweak, req.previous)

    @app.get("/api/history")
    def history_list(user: dict = Depends(require_user)):
        return history.list_items(conn, user["uid"])

    @app.delete("/api/history/{item_id}")
    def history_delete(item_id: str, user: dict = Depends(require_user)):
        if not history.delete(conn, user["uid"], item_id):
            raise HTTPException(404, "Not found")
        return {"ok": True}

    @app.delete("/api/history")
    def history_delete_all(user: dict = Depends(require_user)):
        return {"deleted": history.delete_all(conn, user["uid"])}

    @app.post("/api/history/import")
    async def history_import(request: Request, user: dict = Depends(require_user)):
        items = (await _json(request)).get("items")
        if not isinstance(items, list):
            raise HTTPException(400, "Invalid request")
        if len(items) > history.MAX_ITEMS:
            raise HTTPException(400, "Too many items")
        return {"imported": history.import_items(conn, user["uid"], items)}

    SECRETS = ("openai_api_key", "anthropic_api_key", "turnstile_secret")

    def _hint(name: str) -> str | None:
        h = settings.secret_hint(name)
        return f"\u2026{h}" if h else None

    def _settings_view() -> dict:
        if not settings.enabled():
            reason = "switched_off"
        elif not (settings.get("turnstile_site_key") and settings.get_secret("turnstile_secret")):
            reason = "turnstile_missing"
        elif usage.cap_reached(conn, settings):
            reason = "cap_reached"
        else:
            reason = None
        return {
            "enabled": settings.enabled(), "cap_eur": settings.cap_eur(), "prices": settings.prices(),
            "turnstile_site_key": settings.get("turnstile_site_key"),
            "secrets": {n: _hint(n) for n in SECRETS},
            "open": is_open(conn, settings), "closed_reason": reason,
        }

    def _num(v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0

    @app.get("/api/admin/settings")
    def admin_settings_get(_: dict = Depends(require_admin)):
        return _settings_view()

    @app.put("/api/admin/settings")
    async def admin_settings_put(request: Request, _: dict = Depends(require_admin)):
        data = await _json(request)
        allowed = {"enabled", "cap_eur", "prices", "turnstile_site_key", *SECRETS}
        if set(data) - allowed:
            raise HTTPException(400, "Unknown setting")
        if "enabled" in data and not isinstance(data["enabled"], bool):
            raise HTTPException(400, "enabled must be true or false")
        if "cap_eur" in data and data["cap_eur"] is not None and not _num(data["cap_eur"]):
            raise HTTPException(400, "cap_eur must be a number of 0 or more, or null")
        if "prices" in data:
            pr = data["prices"]
            if not isinstance(pr, dict) or not all(
                    isinstance(m, str) and isinstance(p, dict) and set(p) == {"in", "out"}
                    and _num(p["in"]) and _num(p["out"]) for m, p in pr.items()):
                raise HTTPException(400, 'prices must map model to {"in": number, "out": number}')
        for k in ("turnstile_site_key", *SECRETS):
            if k in data and not (isinstance(data[k], str) or (k == "turnstile_site_key" and data[k] is None)):
                raise HTTPException(400, f"{k} must be a string")
        if "enabled" in data:
            settings.set("enabled", "1" if data["enabled"] else "0")
        if "cap_eur" in data:
            settings.set("cap_eur", None if data["cap_eur"] is None else repr(float(data["cap_eur"])))
        if "prices" in data:
            settings.set("prices", json.dumps(data["prices"]))
        if "turnstile_site_key" in data:
            settings.set("turnstile_site_key", data["turnstile_site_key"] or None)
        for k in SECRETS:
            if k in data:
                settings.set_secret(k, data[k] or None)
        return _settings_view()

    def _style_view(s: styles.Style) -> dict:
        return asdict(s)

    @app.get("/api/admin/styles")
    def admin_styles_list(_: dict = Depends(require_admin)):
        return [_style_view(s) for s in styles.list_styles(conn, active_only=False)]

    @app.post("/api/admin/styles")
    async def admin_styles_create(request: Request, _: dict = Depends(require_admin)):
        d = await _json(request)
        try:
            if not all(isinstance(d.get(k), str) for k in ("label", "prompt", "provider", "model")) \
                    or not isinstance(d.get("description", ""), (str, type(None))):
                raise ValueError("invalid style")
            s = styles.create_style(conn, d["label"], d.get("description") or "", d["prompt"],
                                    d["provider"], d["model"], bool(d.get("active", True)))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return _style_view(s)

    @app.put("/api/admin/styles/order")
    async def admin_styles_order(request: Request, _: dict = Depends(require_admin)):
        ids = (await _json(request)).get("ids")
        existing = {s.id for s in styles.list_styles(conn, active_only=False)}
        if (not isinstance(ids, list) or not all(type(i) is int for i in ids)
                or len(set(ids)) != len(ids) or set(ids) != existing):
            raise HTTPException(400, "ids must list every style exactly once")
        styles.reorder_styles(conn, ids)
        return [_style_view(s) for s in styles.list_styles(conn, active_only=False)]

    @app.put("/api/admin/styles/{style_id}")
    async def admin_styles_update(style_id: int, request: Request, _: dict = Depends(require_admin)):
        d = await _json(request)
        try:
            s = styles.update_style(conn, style_id, **d)
        except (ValueError, TypeError, AttributeError) as e:
            raise HTTPException(400, str(e)) from None
        if s is None:
            raise HTTPException(404, "Not found")
        return _style_view(s)

    @app.delete("/api/admin/styles/{style_id}")
    def admin_styles_delete(style_id: int, _: dict = Depends(require_admin)):
        if not styles.delete_style(conn, style_id):
            raise HTTPException(404, "Not found")
        return {"ok": True}

    @app.get("/api/admin/languages")
    def admin_languages_get(_: dict = Depends(require_admin)):
        return {"items": styles.list_languages(conn)}

    @app.put("/api/admin/languages")
    async def admin_languages_put(request: Request, _: dict = Depends(require_admin)):
        items = (await _json(request)).get("items")
        if not isinstance(items, list) or not items or not all(isinstance(i, dict) for i in items):
            raise HTTPException(400, "Provide at least one language")
        try:
            styles.set_languages(conn, items)
        except (ValueError, AttributeError) as e:
            raise HTTPException(400, str(e)) from None
        return {"items": styles.list_languages(conn)}

    @app.get("/api/admin/models")
    async def admin_models(provider: str, _: dict = Depends(require_admin)):
        if provider not in styles.PROVIDERS:
            raise HTTPException(400, "Unknown provider")
        key = settings.get_secret(f"{provider}_api_key")
        if not key:
            raise HTTPException(400, "No API key set for this provider")
        try:
            return {"models": await providers.list_models(provider, key, http)}
        except providers.ProviderError:
            raise HTTPException(502, "Couldn't load models") from None

    @app.post("/api/admin/try")
    async def admin_try(req: TryIn, _: dict = Depends(require_admin)):
        language = _check_inputs(req, None)
        if req.provider not in styles.PROVIDERS or not req.prompt.strip() or not req.model.strip():
            raise HTTPException(400, "Invalid request")
        api_key = settings.get_secret(f"{req.provider}_api_key")
        if not api_key:
            raise HTTPException(400, "This style is not configured yet")
        output = await _call(req, language, req.prompt, req.provider, api_key, req.model.strip(),
                             None, None, None)
        return {"result": output.to_dict(), "history_id": None}

    @app.get("/api/admin/usage")
    def admin_usage(_: dict = Depends(require_admin)):
        return usage.summary(conn, settings)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
