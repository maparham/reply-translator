from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import clerk as clerk_mod
from . import db, frame, providers, sessions, styles, turnstile, usage
from .config import Config
from .crypto import Crypto
from .settings import Settings

STATIC = Path(__file__).parent / "static"


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
    http = http or httpx.AsyncClient(timeout=60.0)
    if clerk_verifier is None and cfg.clerk_publishable_key and cfg.clerk_secret_key:
        clerk_verifier = clerk_mod.Verifier(cfg.clerk_publishable_key, cfg.clerk_secret_key, cfg.app_url, http)
    fapi = clerk_mod.frontend_api(cfg.clerk_publishable_key) if cfg.clerk_publishable_key else None
    secure = cfg.app_url.lower().startswith("https")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.conn, app.state.crypto = cfg, conn, crypto
    app.state.settings, app.state.http = settings, http
    app.state.generate, app.state.clerk = generate, clerk_verifier
    app.add_middleware(SecurityMiddleware, csp=_csp(fapi), allowed_origin=_origin(cfg.app_url))

    @app.exception_handler(HTTPException)
    async def _http_exc(request, exc: HTTPException):
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
    app.state.require_admin = require_admin

    def set_cookie(resp: JSONResponse, kind: str, uid: str | None = None) -> None:
        resp.set_cookie(sessions.COOKIE, sessions.issue(crypto, kind, uid), max_age=sessions.TTL[kind],
                        path="/", httponly=True, samesite="lax", secure=secure)

    async def _json(request: Request) -> dict:
        try:
            data = await request.json()
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

    @app.get("/api/admin/settings")
    def admin_settings_stub(_: dict = Depends(require_admin)):
        return {}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
