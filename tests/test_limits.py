import json

import pytest

from helpers import body


def test_oversized_content_length_rejected_before_handler(anon_client, fake_gen):
    r = anon_client.post("/api/generate", content=b"x" * (256 * 1024 + 1), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == {"error": "Request too large"}
    assert fake_gen.calls == []


def test_oversized_pre_auth_endpoints_rejected(client):
    big = b"{" + b" " * (300 * 1024) + b"}"
    for path in ("/api/session", "/api/login/clerk"):
        assert client.post(path, content=big, headers={"Content-Type": "application/json"}).status_code == 413


def test_chunked_body_without_content_length_aborted(anon_client, fake_gen):
    def chunks():
        for _ in range(40):
            yield b" " * (16 * 1024)
    r = anon_client.post("/api/generate", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == {"error": "Request too large"}
    assert fake_gen.calls == []


def test_max_size_generate_body_still_works(anon_client, fake_gen):
    fake_gen.data = {"received_gist": "g", "message": "Hallo", "back_translation": "Hello"}
    s = "ü" * 8000
    payload = body(text=s, received=s)
    assert len(json.dumps(payload).encode()) < 256 * 1024
    r = anon_client.post("/api/generate", json=payload)
    assert r.status_code == 200, r.text
    # tweak carries 5 text fields
    prev = {"received_gist": s, "message": s, "back_translation": s}
    r = anon_client.post("/api/tweak", json=body(text=s, received=s, tweak="shorter", previous=prev))
    assert r.status_code == 200, r.text
