"""Account deletion (Google Play requires it in the app and on the web)."""
from helpers import body


def test_delete_account_removes_everything(user_client, client_factory, app):
    user_client.post("/api/generate", json=body())
    assert len(user_client.get("/api/history").json()) == 1
    r = user_client.delete("/api/account")
    assert r.status_code == 200
    assert app.state.clerk.deleted == ["user_u"]
    # Signed out, and nothing left on the server.
    assert user_client.get("/api/config").json()["user"] is None
    assert app.state.conn.execute("SELECT COUNT(*) FROM history WHERE user_id='user_u'").fetchone()[0] == 0
    assert app.state.conn.execute("SELECT COUNT(*) FROM users WHERE id='user_u'").fetchone()[0] == 0


def test_delete_account_keeps_other_users(user_client, client_factory, app):
    other = client_factory()
    other.post("/api/login/clerk", json={"token": "user2"})
    other.post("/api/generate", json=body())
    user_client.delete("/api/account")
    assert len(other.get("/api/history").json()) == 1


def test_delete_account_needs_sign_in(anon_client):
    assert anon_client.delete("/api/account").status_code == 401


def test_delete_account_keeps_data_if_clerk_fails(user_client, app):
    user_client.post("/api/generate", json=body())
    app.state.clerk.delete_fails = True
    assert user_client.delete("/api/account").status_code == 502
    assert len(user_client.get("/api/history").json()) == 1


def test_privacy_and_deletion_pages(client):
    for path in ("/privacy", "/delete-account"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
