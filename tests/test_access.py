from fastapi.testclient import TestClient

from translator import sessions


def test_session_requires_valid_turnstile(client_factory):
    c = client_factory(turnstile_ok=False)
    assert c.post("/api/session", json={"turnstile_token": "t"}).status_code == 403
    c = client_factory(turnstile_ok=True)
    r = c.post("/api/session", json={"turnstile_token": "t"})
    assert r.status_code == 200 and "tr_session" in r.cookies


def test_config_lists_seeded(client):
    j = client.get("/api/config").json()
    assert [s["label"] for s in j["styles"]] == ["Official", "Friendly", "Neutral"]
    assert [t["id"] for t in j["tweaks"]] == ["shorter", "more_polite", "firmer", "less_formal"]
    assert j["open"] is True and j["user"] is None


def test_closed_without_turnstile_keys(client, settings):
    settings.set("turnstile_site_key", None)
    assert client.get("/api/config").json()["open"] is False


def test_clerk_login_and_admin(client):
    r = client.post("/api/login/clerk", json={"token": "admin"})
    assert r.json() == {"email": "admin@x.test", "is_admin": True}
    assert client.get("/api/config").json()["user"]["is_admin"] is True


def test_bad_clerk_token(client):
    assert client.post("/api/login/clerk", json={"token": "bad"}).status_code == 401


def test_admin_route_forbidden_for_anon_and_users(client):
    assert client.post("/api/session", json={"turnstile_token": "t"}).status_code == 200
    assert client.get("/api/admin/settings").status_code == 403
    assert client.post("/api/login/clerk", json={"token": "user"}).status_code == 200
    assert client.get("/api/admin/settings").status_code == 403


def test_admin_route_allowed_for_admin(admin_client):
    assert admin_client.get("/api/admin/settings").status_code == 200


def test_cross_origin_post_rejected(app):
    c = TestClient(app, headers={"Origin": "https://evil.rahkar.pro"})
    r = c.post("/api/session", json={"turnstile_token": "t"})
    assert r.status_code == 403 and r.json() == {"error": "Bad origin"}
    assert TestClient(app).post("/api/logout").status_code == 403


def test_turnstile_unavailable_is_503(app):
    from translator.turnstile import TurnstileUnavailable
    from translator.app import create_app

    async def boom(*a, **kw):
        raise TurnstileUnavailable("x")

    a = create_app(app.state.cfg, verify_turnstile=boom, clerk_verifier=app.state.clerk)
    c = TestClient(a, headers={"Origin": "http://testserver"})
    assert c.post("/api/session", json={"turnstile_token": "t"}).status_code == 503


def test_security_headers_and_health(client):
    r = client.get("/health")
    assert r.json() == {"ok": True}
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_logout_clears_cookie(anon_client):
    anon_client.post("/api/logout")
    assert anon_client.get("/api/config").json()["user"] is None
    assert "tr_session" not in anon_client.cookies


def test_expired_session_cookie(crypto):
    tok = sessions.issue(crypto, "anon", now=0)
    assert sessions.read(crypto, tok, now=13 * 3600) is None
    assert sessions.read(crypto, tok, now=3600) == {"kind": "anon", "uid": None}


import httpx
import pytest

from translator import clerk as clerk_mod


def test_router_errors_are_json_error(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"error": "Not Found"}
    r = client.get("/api/session")
    assert r.status_code == 405 and r.json() == {"error": "Method Not Allowed"}


@pytest.mark.parametrize("origin", ["null", "https://testserver", "http://testserver:80", "http://testserver.evil"])
def test_origin_variants_rejected(app, origin):
    c = TestClient(app, headers={"Origin": origin})
    assert c.post("/api/logout").status_code == 403


def test_require_user_rejects_anon(app, anon_client, user_client):
    from fastapi import Depends

    app.add_api_route("/api/_who", lambda s=Depends(app.state.require_user): s, methods=["GET"])
    r = anon_client.get("/api/_who")
    assert r.status_code == 401 and r.json() == {"error": "Please sign in"}
    assert user_client.get("/api/_who").json()["kind"] == "user"


def _verifier(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return clerk_mod.Verifier("pk_test_" + "Y2xlcmsueC50ZXN0JA==", "sk", "http://testserver", http)


@pytest.mark.parametrize("content", [b"not json", b"[1]"])
async def test_clerk_email_unreadable_body_is_clerk_error(content):
    v = _verifier(lambda req: httpx.Response(200, content=content))
    with pytest.raises(clerk_mod.ClerkError):
        await v.email("user_x")


@pytest.mark.parametrize("content", [b"not json", b"[1]"])
async def test_clerk_jwks_unreadable_body_is_clerk_error(content):
    v = _verifier(lambda req: httpx.Response(200, content=content))
    with pytest.raises(clerk_mod.ClerkError):
        await v._key("k1")


def test_login_maps_clerk_error_to_401(app, client_factory):
    class Bad:
        async def verify(self, token):
            raise clerk_mod.ClerkError("x")

    from translator.app import create_app

    a = create_app(app.state.cfg, clerk_verifier=Bad())
    c = TestClient(a, headers={"Origin": "http://testserver"})
    assert c.post("/api/login/clerk", json={"token": "x"}).status_code == 401


def test_csp_allows_clerk_bot_protection(client):
    csp = client.get("/health").headers["content-security-policy"]
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert "https://cdn.protect.clerk.com" in script_src


def test_turnstile_session_does_not_downgrade_signed_in_user(client):
    # The Turnstile widget can finish after a Clerk sign-in; that must not replace the user session.
    assert client.post("/api/login/clerk", json={"token": "admin"}).status_code == 200
    assert client.post("/api/session", json={"turnstile_token": "t"}).status_code == 200
    assert client.get("/api/config").json()["user"]["email"] == "admin@x.test"
    assert client.get("/api/admin/settings").status_code == 200


def test_pages_reference_versioned_assets(client):
    # Cloudflare caches /static/* at the edge; a content hash in the URL makes each deploy fetch fresh files.
    import hashlib, re
    from translator.app import STATIC
    for path in ("/", "/admin"):
        r = client.get(path)
        assert r.headers["cache-control"] == "no-cache"
        refs = re.findall(r'/static/([\w.]+)\?v=(\w+)"', r.text)
        assert {"app.css", "common.js"} <= {name for name, _ in refs}
        for name, v in refs:
            assert v == hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
        assert not re.search(r'/static/[\w.]+"', r.text)  # nothing left unversioned


def test_app_check_page_for_android(client):
    r = client.get("/app-check")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert "/static/app-check.js?v=" in r.text
    assert client.get("/static/app-check.js").status_code == 200
