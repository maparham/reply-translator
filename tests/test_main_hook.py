import asyncio

from translator import frame
from translator.__main__ import build_app, fake_generate


def test_my_languages_in_config(client):
    assert client.get("/api/config").json()["my_languages"] == list(frame.MY_LANGUAGES)


def test_fake_generate_is_valid_output_and_depends_on_mode():
    reply = asyncio.run(fake_generate("anthropic", "k", "m", "sys", "<received_message>\nHi\n</received_message>", {}, None))
    frame.parse_output(reply.data, True)
    compose = asyncio.run(fake_generate("anthropic", "k", "m", "sys", "<what_i_want_to_say>\nx\n</what_i_want_to_say>", {}, None))
    assert compose.data["received_gist"] == ""
    tweaked = asyncio.run(fake_generate("anthropic", "k", "m", "sys", "<change_request>\nMake shorter\n</change_request>", {}, None))
    assert tweaked.data["message"] != compose.data["message"]


def test_fake_provider_off_by_default(cfg, monkeypatch):
    monkeypatch.delenv("TRANSLATOR_FAKE_PROVIDER", raising=False)
    assert build_app(cfg).state.generate.__name__ == "generate"
    monkeypatch.setenv("TRANSLATOR_FAKE_PROVIDER", "1")
    assert build_app(cfg).state.generate is fake_generate


def test_fake_provider_warns_loudly(cfg, monkeypatch, caplog):
    monkeypatch.setenv("TRANSLATOR_FAKE_PROVIDER", "1")
    with caplog.at_level("WARNING", logger="uvicorn.error"):
        build_app(cfg)
    assert "FAKE provider" in caplog.text
