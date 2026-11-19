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
    client.post("/api/session", json={"turnstile_token": "t"})
    assert client.get("/api/admin/settings").status_code == 403
    client.post("/api/login/clerk", json={"token": "user"})
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

    async def boom(*a):
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
