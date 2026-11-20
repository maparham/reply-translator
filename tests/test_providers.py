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
        return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": "", "signature": "x"},
                                                     {"type": "text", "text": '{"message": "Hallo"}'}],
                                         "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}})
    schema = {"type": "object"}
    async with client(h) as http:
        g = await providers.generate("anthropic", "k", "claude-sonnet-5-5", "S", "U", schema, http)
    assert g.data == {"message": "Hallo"} and g.usage == providers.Usage(10, 5)
    assert seen["key"] == "k" and "tool_choice" not in seen["body"] and "tools" not in seen["body"]
    assert seen["body"]["output_config"] == {"format": {"type": "json_schema", "schema": {"type": "object"}}}
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


@pytest.mark.parametrize("content", [[{"type": "text", "text": "not json"}], [{"type": "thinking", "thinking": ""}], []])
async def test_anthropic_no_json_text(content):
    r = httpx.Response(200, json={"content": content, "usage": {"input_tokens": 1, "output_tokens": 1}})
    async with client(lambda q: r) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate("anthropic", "k", "m", "S", "U", {}, http)


@pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
async def test_anthropic_bad_stop_reason(reason):
    r = httpx.Response(200, json={"content": [{"type": "text", "text": '{"a": 1}'}], "stop_reason": reason,
                                  "usage": {"input_tokens": 1, "output_tokens": 1}})
    async with client(lambda q: r) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate("anthropic", "k", "m", "S", "U", {}, http)


async def test_missing_usage_defaults_to_zero():
    r = httpx.Response(200, json={"content": [{"type": "text", "text": '{"a": 1}'}]})
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


@pytest.mark.parametrize("provider,env,expected", [
    ("anthropic", "ANTHROPIC_BASE_URL", "https://gw.example/v1/messages"),
    ("openai", "OPENAI_BASE_URL", "https://gw.example/v1/chat/completions"),
])
async def test_base_url_override(monkeypatch, provider, env, expected):
    monkeypatch.setenv(env, "https://gw.example/")
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        if provider == "anthropic":
            return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as http:
        await providers.generate(provider, "k", "m", "S", "U", {}, http)
    assert seen["url"] == expected


async def test_default_base_url(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"data": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as http:
        await providers.list_models("anthropic", "k", http)
    assert seen["url"] == "https://api.anthropic.com/v1/models?limit=1000"


async def test_output_tokens_are_capped():
    seen = {}

    def h(req):
        seen[req.url.path] = json.loads(req.content)
        if "chat" in req.url.path:
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {}})
    async with client(h) as http:
        await providers.generate("anthropic", "k", "m", "S", "U", {}, http)
        await providers.generate("openai", "k", "m", "S", "U", {}, http)
    assert seen["/v1/messages"]["max_tokens"] == providers.MAX_OUTPUT_TOKENS
    assert seen["/v1/chat/completions"]["max_completion_tokens"] == providers.MAX_OUTPUT_TOKENS
    assert providers.MAX_OUTPUT_TOKENS <= 4096


@pytest.mark.parametrize("provider,resp", [
    ("anthropic", {"content": [], "stop_reason": "max_tokens", "usage": {"input_tokens": 9, "output_tokens": 4096}}),
    ("anthropic", {"content": [{"type": "text", "text": "{trunc"}], "usage": {"input_tokens": 9, "output_tokens": 4096}}),
    ("openai", {"choices": [{"message": {"content": "{trunc"}}], "usage": {"prompt_tokens": 9, "completion_tokens": 4096}}),
])
async def test_failure_after_billing_carries_usage(provider, resp):
    async with client(lambda r: httpx.Response(200, json=resp)) as http:
        with pytest.raises(providers.ProviderError) as e:
            await providers.generate(provider, "k", "m", "S", "U", {}, http)
    assert e.value.usage == providers.Usage(9, 4096)


async def test_read_timeout_charges_worst_case():
    def h(req):
        raise httpx.ReadTimeout("slow", request=req)
    async with client(h) as http:
        with pytest.raises(providers.ProviderError) as e:
            await providers.generate("anthropic", "k", "m", "S" * 300, "U" * 300, {}, http)
    assert e.value.usage.output_tokens == providers.MAX_OUTPUT_TOKENS and e.value.usage.input_tokens >= 200


async def test_connect_error_charges_nothing():
    def h(req):
        raise httpx.ConnectError("down", request=req)
    async with client(h) as http:
        with pytest.raises(providers.ProviderError) as e:
            await providers.generate("anthropic", "k", "m", "S", "U", {}, http)
    assert e.value.usage is None
