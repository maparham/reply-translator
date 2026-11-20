import httpx
import pytest

from translator import turnstile


def _answer(monkeypatch, body):
    monkeypatch.setattr(turnstile, "_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))))


@pytest.mark.parametrize("body,ok", [
    ({"success": True, "hostname": "translate.example"}, True),
    ({"success": True, "hostname": "evil.example"}, False),   # token solved on another site using the same key
    ({"success": True}, False),
    ({"success": False, "hostname": "translate.example"}, False),
])
async def test_verify_checks_hostname(monkeypatch, body, ok):
    _answer(monkeypatch, body)
    assert await turnstile.verify("s", "t", None, hostname="translate.example") is ok


async def test_cloudflare_test_secret_skips_hostname(monkeypatch):
    # Cloudflare's documented test secrets always answer hostname "example.com"; local development uses them.
    _answer(monkeypatch, {"success": True, "hostname": "example.com"})
    assert await turnstile.verify("1x0000000000000000000000000000000AA", "t", None, hostname="localhost") is True
