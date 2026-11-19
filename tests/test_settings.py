def test_secret_roundtrip_and_hint(settings, conn):
    settings.set_secret("openai_api_key", "sk-abcdef1234")
    assert settings.get_secret("openai_api_key") == "sk-abcdef1234"
    assert settings.secret_hint("openai_api_key") == "1234"
    raw = conn.execute("select value from settings where key='openai_api_key'").fetchone()[0]
    assert "sk-abcdef1234" not in raw

def test_secret_clear(settings):
    settings.set_secret("openai_api_key", "x1234"); settings.set_secret("openai_api_key", None)
    assert settings.get_secret("openai_api_key") is None and settings.secret_hint("openai_api_key") is None

def test_sign_unsign(crypto):
    t = crypto.sign({"kind": "anon", "exp": 9999999999})
    assert crypto.unsign(t) == {"kind": "anon", "exp": 9999999999}
    assert crypto.unsign(t[:-2] + "xx") is None

def test_defaults(settings):
    assert settings.enabled() is True and settings.cap_eur() is None and settings.prices() == {}

def test_connect_idempotent(cfg):
    from translator import db
    db.connect(cfg.db_path); db.connect(cfg.db_path)

def test_unsign_rejects_non_ascii(crypto):
    assert crypto.unsign("abc.é") is None
    assert crypto.unsign("!!!garbage.xx") is None
    assert crypto.unsign("nodot") is None

def test_cap_eur_non_finite(settings):
    for v in ("nan", "inf", "-inf"):
        settings.set("cap_eur", v)
        assert settings.cap_eur() is None
    settings.set("cap_eur", "5.5")
    assert settings.cap_eur() == 5.5
