import json

from translator.providers import ProviderError

from helpers import body

TRY = {"prompt": "p", "provider": "anthropic", "model": "m", "language_code": "de-AT",
       "my_language": "English", "text": "hi", "received": None}


def test_settings_never_return_keys(admin_client):
    admin_client.put("/api/admin/settings", json={"openai_api_key": "sk-secret9876"})
    j = admin_client.get("/api/admin/settings").json()
    assert j["secrets"]["openai_api_key"] == "…9876" and "sk-secret9876" not in json.dumps(j)


def test_clear_secret(admin_client):
    admin_client.put("/api/admin/settings", json={"openai_api_key": "x1234"})
    admin_client.put("/api/admin/settings", json={"openai_api_key": ""})
    assert admin_client.get("/api/admin/settings").json()["secrets"]["openai_api_key"] is None


def test_switch_off(admin_client, anon_client):
    r = admin_client.put("/api/admin/settings", json={"enabled": False}).json()
    assert r["open"] is False and r["closed_reason"] == "switched_off"
    assert anon_client.post("/api/generate", json=body()).status_code == 503


def test_admin_only(anon_client, user_client):
    for c in (anon_client, user_client):
        assert c.get("/api/admin/settings").status_code == 403
        assert c.put("/api/admin/settings", json={}).status_code == 403
        assert c.post("/api/admin/try", json=TRY).status_code == 403


def test_settings_validation_saves_nothing(admin_client):
    for bad in ({"enabled": "no"}, {"cap_eur": -1}, {"cap_eur": "x"}, {"prices": {"m": {"in": -1, "out": 1}}},
                {"prices": {"m": {"in": 1}}}, {"prices": []}, {"openai_api_key": 5}, {"bogus": 1}):
        r = admin_client.put("/api/admin/settings", json={"turnstile_site_key": "NEW", **bad})
        assert r.status_code == 400 and "error" in r.json()
    assert admin_client.get("/api/admin/settings").json()["turnstile_site_key"] == "site-key"


def test_settings_roundtrip_and_cap(admin_client, anon_client):
    j = admin_client.put("/api/admin/settings", json={"cap_eur": 1.5, "prices": {"m": {"in": 1, "out": 2}}}).json()
    assert j["cap_eur"] == 1.5 and j["prices"] == {"m": {"in": 1, "out": 2}} and j["closed_reason"] is None
    assert admin_client.put("/api/admin/settings", json={"cap_eur": None}).json()["cap_eur"] is None
    j = admin_client.put("/api/admin/settings", json={"turnstile_site_key": ""}).json()
    assert j["closed_reason"] == "turnstile_missing"


def test_cap_reached_reason(admin_client, conn, settings):
    from translator import usage
    from translator.providers import Usage
    settings.set("prices", json.dumps({"claude-sonnet-5-5": {"in": 1000000, "out": 0}}))
    settings.set("cap_eur", "1")
    usage.record(conn, settings, None, "claude-sonnet-5-5", Usage(10, 0))
    assert admin_client.get("/api/admin/settings").json()["closed_reason"] == "cap_reached"


def test_style_crud(admin_client):
    s = admin_client.post("/api/admin/styles", json={"label": "Short", "description": "", "prompt": "p", "provider": "openai", "model": "m"}).json()
    admin_client.put(f"/api/admin/styles/{s['id']}", json={"active": False})
    assert "Short" not in [x["label"] for x in admin_client.get("/api/config").json()["styles"]]
    assert "Short" in [x["label"] for x in admin_client.get("/api/admin/styles").json()]
    assert admin_client.post("/api/admin/styles", json={"label": "", "prompt": "p", "provider": "openai", "model": "m"}).status_code == 400
    assert admin_client.put(f"/api/admin/styles/{s['id']}", json={"provider": "x"}).status_code == 400
    assert admin_client.put("/api/admin/styles/9999", json={"active": True}).status_code == 404
    assert admin_client.delete(f"/api/admin/styles/{s['id']}").status_code == 200
    assert admin_client.delete(f"/api/admin/styles/{s['id']}").status_code == 404


def test_style_order(admin_client):
    ids = [s["id"] for s in admin_client.get("/api/admin/styles").json()]
    r = admin_client.put("/api/admin/styles/order", json={"ids": ids[::-1]})
    assert r.status_code == 200 and [s["id"] for s in r.json()] == ids[::-1]
    for bad in (ids[:-1], ids + [ids[0]], ids[:-1] + [9999], "x"):
        assert admin_client.put("/api/admin/styles/order", json={"ids": bad}).status_code == 400
    assert [s["id"] for s in admin_client.get("/api/admin/styles").json()] == ids[::-1]


def test_languages_validation(admin_client):
    assert admin_client.put("/api/admin/languages", json={"items": []}).status_code == 400
    dup = [{"code": "a", "name": "A"}, {"code": "a", "name": "B"}]
    assert admin_client.put("/api/admin/languages", json={"items": dup}).status_code == 400
    assert admin_client.put("/api/admin/languages", json={"items": ["x"]}).status_code == 400
    ok = [{"code": "de-AT", "name": "German"}, {"code": "de-DE", "name": "German (DE)"}]
    assert admin_client.put("/api/admin/languages", json={"items": ok}).json()["items"] == ok
    assert admin_client.get("/api/admin/languages").json()["items"] == ok


def test_models(admin_client, app, monkeypatch):
    from translator import providers

    async def fake(provider, key, http):
        if provider == "anthropic":
            raise ProviderError("x")
        return ["a", "b"]
    monkeypatch.setattr(providers, "list_models", fake)
    assert admin_client.get("/api/admin/models?provider=openai").status_code == 400  # no key
    assert admin_client.get("/api/admin/models?provider=nope").status_code == 400
    assert admin_client.get("/api/admin/models?provider=anthropic").status_code == 502
    admin_client.put("/api/admin/settings", json={"openai_api_key": "k"})
    assert admin_client.get("/api/admin/models?provider=openai").json() == {"models": ["a", "b"]}


def test_try_works_when_off(admin_client, fake_gen, conn):
    admin_client.put("/api/admin/settings", json={"enabled": False})
    r = admin_client.post("/api/admin/try", json=TRY)
    assert r.status_code == 200 and r.json()["result"]["message"] == "Hallo"
    assert conn.execute("SELECT style_id FROM usage").fetchall()[-1][0] is None
    assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
    assert fake_gen.calls[0]["model"] == "m"


def test_try_errors(admin_client, fake_gen):
    assert admin_client.post("/api/admin/try", json=TRY | {"provider": "openai"}).status_code == 400
    assert admin_client.post("/api/admin/try", json=TRY | {"text": "x" * 8001}).status_code == 400
    assert admin_client.post("/api/admin/try", json=TRY | {"my_language": "Klingon"}).status_code == 400
    assert admin_client.post("/api/admin/try", json=TRY | {"language_code": "zz"}).status_code == 400
    fake_gen.fail = "provider_error"
    assert admin_client.post("/api/admin/try", json=TRY).status_code == 502


def test_usage(admin_client):
    assert admin_client.get("/api/admin/usage").status_code == 200
