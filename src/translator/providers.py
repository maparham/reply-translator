"""Anthropic / OpenAI adapters over raw httpx. Never logs bodies or keys."""
import json
import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger("translator")
TIMEOUT = 60.0
_DEFAULT_BASE = {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com"}


def _base(provider: str) -> str:
    """API origin; ANTHROPIC_BASE_URL / OPENAI_BASE_URL override it (e.g. a compatible gateway)."""
    url = os.environ.get(f"{provider.upper()}_BASE_URL", "").strip()
    return (url or _DEFAULT_BASE[provider]).rstrip("/")


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class Generation:
    data: object
    usage: Usage


class ProviderError(Exception):
    pass


def _fail(provider: str, what: str, status: int | None = None, exc: BaseException | None = None):
    log.warning("provider=%s status=%s error=%s", provider, status, type(exc).__name__ if exc else what)
    raise ProviderError(f"{provider}: {what}") from None


async def _request(provider: str, http: httpx.AsyncClient, method: str, url: str, headers: dict, body=None) -> dict:
    try:
        resp = await http.request(method, url, headers=headers, json=body, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        _fail(provider, "request failed", exc=e)
    if not resp.is_success:
        _fail(provider, f"HTTP {resp.status_code}", status=resp.status_code)
    try:
        data = resp.json()
    except ValueError as e:
        _fail(provider, "unreadable response", status=resp.status_code, exc=e)
    if not isinstance(data, dict):
        _fail(provider, "unexpected response", status=resp.status_code)
    return data


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _usage(data: dict, a: str, b: str) -> Usage:
    u = data.get("usage")
    u = u if isinstance(u, dict) else {}
    return Usage(_int(u.get(a)), _int(u.get(b)))


def _check_provider(provider: str) -> None:
    if provider not in ("anthropic", "openai"):
        raise ValueError(f"unknown provider: {provider}")


async def generate(provider: str, api_key: str, model: str, system: str, user: str,
                   schema: dict, http: httpx.AsyncClient) -> Generation:
    _check_provider(provider)
    if provider == "anthropic":
        return await _anthropic(api_key, model, system, user, schema, http)
    return await _openai(api_key, model, system, user, schema, http)


async def _anthropic(api_key, model, system, user, schema, http) -> Generation:
    # Structured outputs: current models reject forced tool_choice, so the JSON comes back as a text block.
    body = {"model": model, "max_tokens": 16000, "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}}}
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    data = await _request("anthropic", http, "POST", f"{_base('anthropic')}/v1/messages", headers, body)
    if data.get("stop_reason") in ("max_tokens", "refusal"):
        _fail("anthropic", f"stopped: {data['stop_reason']}")
    content = data.get("content")
    if not isinstance(content, list):
        _fail("anthropic", "missing content")
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            try:
                return Generation(json.loads(block["text"]), _usage(data, "input_tokens", "output_tokens"))
            except ValueError as e:
                _fail("anthropic", "invalid JSON output", exc=e)
    _fail("anthropic", "missing structured output")


async def _openai(api_key, model, system, user, schema, http) -> Generation:
    body = {"model": model, "store": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "result", "strict": True, "schema": schema}}}
    headers = {"Authorization": f"Bearer {api_key}"}
    data = await _request("openai", http, "POST", f"{_base('openai')}/v1/chat/completions", headers, body)
    choices = data.get("choices")
    msg = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    if not isinstance(msg, dict):
        _fail("openai", "missing choices")
    if msg.get("refusal"):
        _fail("openai", "refusal")
    content = msg.get("content")
    if not isinstance(content, str):
        _fail("openai", "missing content")
    try:
        parsed = json.loads(content)
    except ValueError as e:
        _fail("openai", "invalid JSON output", exc=e)
    return Generation(parsed, _usage(data, "prompt_tokens", "completion_tokens"))


async def list_models(provider: str, api_key: str, http: httpx.AsyncClient) -> list[str]:
    _check_provider(provider)
    if provider == "anthropic":
        url = f"{_base('anthropic')}/v1/models?limit=1000"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    else:
        url = f"{_base('openai')}/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"}
    data = await _request(provider, http, "GET", url, headers)
    items = data.get("data")
    if not isinstance(items, list):
        _fail(provider, "missing data")
    ids = [m["id"] for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)]
    return sorted(ids)
