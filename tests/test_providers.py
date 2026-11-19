import json
import logging

import httpx
import pytest

from translator import providers


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_anthropic_generate():
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        seen["key"] = req.headers["x-api-key"]
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "submit", "input": {"message": "Hallo"}}],
                                         "usage": {"input_tokens": 10, "output_tokens": 5}})
    schema = {"type": "object"}
    async with client(h) as http:
        g = await providers.generate("anthropic", "k", "claude-sonnet-5-5", "S", "U", schema, http)
    assert g.data == {"message": "Hallo"} and g.usage == providers.Usage(10, 5)
    assert seen["key"] == "k" and seen["body"]["tool_choice"] == {"type": "tool", "name": "submit"}
    assert seen["body"]["tools"][0]["input_schema"] == {"type": "object"}
    assert schema == {"type": "object"}


async def test_openai_generate_store_false():
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"message": "Hallo"}'}}],
                                         "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    async with client(h) as http:
        g = await providers.generate("openai", "k", "m", "S", "U", {"type": "object"}, http)
    assert seen["body"]["store"] is False and g.data == {"message": "Hallo"} and g.usage == providers.Usage(7, 3)


@pytest.mark.parametrize("resp", [
    httpx.Response(500), httpx.Response(401, json={}), httpx.Response(200, text="nope"),
    httpx.Response(200, json=[1]), httpx.Response(200, json={}),
    httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}], "usage": {}}),
    httpx.Response(200, json={"choices": [{"message": {"content": None, "refusal": "no"}}], "usage": {}})])
async def test_openai_errors(resp):
    async with client(lambda r: resp) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate("openai", "k", "m", "S", "U", {}, http)


async def test_anthropic_no_tool_use():
    r = httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 1, "output_tokens": 1}})
    async with client(lambda q: r) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate("anthropic", "k", "m", "S", "U", {}, http)


@pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
async def test_anthropic_bad_stop_reason(reason):
    r = httpx.Response(200, json={"content": [{"type": "tool_use", "input": {"a": 1}}], "stop_reason": reason,
                                  "usage": {"input_tokens": 1, "output_tokens": 1}})
    async with client(lambda q: r) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate("anthropic", "k", "m", "S", "U", {}, http)


async def test_missing_usage_defaults_to_zero():
    r = httpx.Response(200, json={"content": [{"type": "tool_use", "input": {"a": 1}}]})
    async with client(lambda q: r) as http:
        g = await providers.generate("anthropic", "k", "m", "S", "U", {}, http)
    assert g.usage == providers.Usage(0, 0)


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
async def test_timeout(provider):
    def h(req):
        raise httpx.ReadTimeout("slow")
    async with client(h) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate(provider, "k", "m", "S", "U", {}, http)


async def test_unknown_provider():
    async with client(lambda r: httpx.Response(200)) as http:
        with pytest.raises(ValueError):
            await providers.generate("nope", "k", "m", "S", "U", {}, http)
        with pytest.raises(ValueError):
            await providers.list_models("nope", "k", http)


async def test_error_log_has_no_secrets(caplog):
    r = httpx.Response(401, json={"error": "SECRET-BODY sk-leak"})
    with caplog.at_level(logging.INFO, logger="translator"):
        async with client(lambda q: r) as http:
            with pytest.raises(providers.ProviderError) as ei:
                await providers.generate("openai", "sk-leak", "m", "S", "U-text", {}, http)
    text = caplog.text + str(ei.value)
    assert "401" in caplog.text
    assert "SECRET-BODY" not in text and "sk-leak" not in text and "U-text" not in text


async def test_list_models():
    r = httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})
    async with client(lambda q: r) as http:
        assert await providers.list_models("openai", "k", http) == ["a", "b"]
        assert await providers.list_models("anthropic", "k", http) == ["a", "b"]


@pytest.mark.parametrize("resp", [httpx.Response(500), httpx.Response(200, text="x"), httpx.Response(200, json={"data": 3})])
async def test_list_models_errors(resp):
    async with client(lambda q: resp) as http:
        with pytest.raises(providers.ProviderError):
            await providers.list_models("openai", "k", http)
