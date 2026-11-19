# Reply Translator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A web app that turns a rough text (and optionally a received message) into a ready-to-send message in a
target language, styled by admin-written prompts, using OpenAI or Anthropic.

**Architecture:** One FastAPI process serving a JSON API and static vanilla-JS pages, SQLite for settings/styles/
history/usage. The app owns a fixed "frame" prompt; the admin's style prompt is inserted into it; providers return
structured JSON `{received_gist, message, back_translation}`. Access: Turnstile-backed anonymous session cookie,
optional Clerk sign-in, admin = Clerk email in `ADMIN_EMAILS`.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx (raw provider HTTP calls — no SDKs), cryptography (Fernet,
RSA for Clerk JWT), tzdata, pytest + pytest-asyncio, uv. Frontend: plain HTML/CSS/JS, Clerk JS from its Frontend
API, Turnstile widget. Docker.

**Spec:** `docs/superpowers/specs/2026-11-19-reply-translator-design.md`

## Global Constraints

- Python package `translator` in `src/translator/`; tests in `tests/`; run with `uv run pytest`.
- Env: `APP_URL`, `APP_SECRET_KEY` (a Fernet key), `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `ADMIN_EMAILS`
  (comma-separated, compared lower-cased), `TRANSLATOR_DB` (default `/data/translator.db`), `TRANSLATOR_HOST`
  (default `127.0.0.1`), `TRANSLATOR_PORT` (default `18490`).
- API keys never leave the server: no endpoint returns them; admin settings show only "set" + last 4 chars.
- No message content of anonymous users is stored server-side or logged. Never log request bodies.
- OpenAI requests send `"store": false`.
- Daily cap day boundary: midnight `Europe/Vienna`.
- App is "off" (503 on generate/tweak) when the switch is off, when Turnstile keys are unset, or when the cap is
  reached for today.
- Signed-in users skip Turnstile.
- Tweaks are exactly: `shorter` "Shorter", `more_polite` "More polite", `firmer` "Firmer", `less_formal` "Less formal".
- Seed on first start: styles Official, Friendly, Neutral (Austrian-German prompts, provider `anthropic`, model
  `claude-sonnet-5-5`); one target language `de-AT` "German (Austria)".
- UI copy in English. UI name "Reply Translator".
- Input length limit: 8000 characters for each of `text` and `received` (my call; see Review Focus).
- Container: `mem_limit: 128m`, host networking, bound to `127.0.0.1:18490`, volume `translator_data`.
- Do not modify anything under `/Users/mahmoudparham/projects/claude_proxy`; copy from it only.

## Review Focus

1. **Provider returns malformed output, refuses, times out, or 4xx/5xx** → user gets 502 `{"error": "Couldn't generate, try again"}`, the server does not crash, nothing is saved to history. (Task 7)
2. **Style deleted/deactivated or its provider key missing between page load and Generate** → 400 `{"error": "This style is not available"}` (missing key: 400 `"This style is not configured yet"`); history items keep the style label, so old items still display. (Task 7)
3. **Very long paste (e.g. a whole email thread)** → over 8000 chars in either field gives 400 `{"error": "Text is too long (max 8000 characters)"}` before any provider call. (Task 7)
4. **History import run twice (sign in on the same browser again)** → no duplicates: items are keyed by client-generated UUID, re-import is idempotent; a user can't overwrite another user's item with the same id. (Task 8)
5. **Daily cap at the day boundary / models without price** → spend resets at Vienna midnight, not UTC; unpriced models count €0 and are listed in `GET /api/admin/usage` as `unpriced_models`. (Task 5)

---

## File Structure

```
pyproject.toml, Dockerfile, .gitignore, .dockerignore, README.md
src/translator/
  __init__.py
  config.py        # Config dataclass from env
  db.py            # connect(), schema, migrations
  crypto.py        # Fernet encrypt/decrypt + HMAC signing (key from APP_SECRET_KEY)
  settings.py      # key/value settings incl. encrypted API keys
  styles.py        # styles + languages CRUD and seed
  frame.py         # frame prompt, output schema, tweaks, output parsing
  providers.py     # Anthropic / OpenAI HTTP adapters, list_models
  usage.py         # usage recording, cost, cap check
  sessions.py      # signed session cookie
  clerk.py         # copied from claude_proxy (Verifier), proxy bits removed
  turnstile.py     # copied from claude_proxy
  history.py       # per-user history store
  app.py           # create_app(): routes, access rules
  __main__.py      # uvicorn entry
  static/index.html, app.js, admin.html, admin.js, app.css
tests/conftest.py, test_*.py
deploy/lightsail/docker-compose.yml, update.sh, translator-backup, README.md
```

---

### Task 1: Project scaffold, config, DB, crypto, settings

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/translator/{__init__,config,db,crypto,settings}.py`, `tests/conftest.py`, `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `config.Config` (frozen dataclass): `app_url: str, secret_key: str, clerk_publishable_key: str, clerk_secret_key: str, admin_emails: frozenset[str], db_path: str, host: str, port: int`; `config.from_env() -> Config`.
  - `db.connect(path: str) -> sqlite3.Connection` (WAL, `row_factory=sqlite3.Row`, creates all tables below, idempotent).
  - Tables: `settings(key TEXT PK, value TEXT)`, `styles(id INTEGER PK, label, description, prompt, provider, model, active INTEGER, position INTEGER)`, `languages(code TEXT PK, name, position INTEGER)`, `users(id TEXT PK /*clerk user id*/, email, created_at)`, `history(id TEXT PK, user_id, created_at, updated_at, style_label, language_code, inputs TEXT /*json*/, output TEXT /*json*/)`, `usage(id INTEGER PK, day TEXT, style_id, model, input_tokens, output_tokens, cost_eur REAL)`.
  - `crypto.Crypto(secret_key: str)`: `.encrypt(s: str) -> str`, `.decrypt(token: str) -> str`, `.sign(payload: dict) -> str`, `.unsign(token: str) -> dict | None` (HMAC-SHA256 with a key derived as `sha256(b"session:" + secret_key)`; returns None on bad signature).
  - `settings.Settings(conn, crypto)`: `get(key, default=None) -> str | None`, `set(key, value: str | None)`, `get_secret(name) -> str | None`, `set_secret(name, value: str | None)`, `secret_hint(name) -> str | None` (last 4 chars), `enabled() -> bool` (key `enabled`, default `"1"`), `cap_eur() -> float | None`, `prices() -> dict[str, dict]` (key `prices`, JSON `{model: {"in": float, "out": float}}` € per 1M tokens).
  - Secret names: `openai_api_key`, `anthropic_api_key`, `turnstile_secret`; plain setting `turnstile_site_key`.
  - `tests/conftest.py` fixtures: `cfg` (Config with tmp db, `Fernet.generate_key()` secret, `admin_emails={"admin@x.test"}`), `conn`, `crypto`, `settings`.

- [ ] **Step 1:** `uv init --package`-style `pyproject.toml` (name `translator`, deps `fastapi`, `uvicorn[standard]`, `httpx`, `cryptography`, `tzdata`; dev group `pytest`, `pytest-asyncio`; pytest `asyncio_mode = "auto"`, `pythonpath = ["src"]`). `.gitignore`: `.venv`, `__pycache__`, `*.db*`, `.env`, `*.env`.
- [ ] **Step 2: Write failing tests** in `tests/test_settings.py`:

```python
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
```

- [ ] **Step 3:** Run `uv run pytest tests/test_settings.py -v` → FAIL (import errors).
- [ ] **Step 4:** Implement the modules per Interfaces. `from_env` raises `ValueError` naming the missing var for `APP_URL`/`APP_SECRET_KEY`; Clerk vars may be empty (sign-in off).
- [ ] **Step 5:** Run tests → PASS.
- [ ] **Step 6:** `git add -A && git commit -m "feat: scaffold config, db, crypto, settings"`

---

### Task 2: Styles and languages

**Files:**
- Create: `src/translator/styles.py`, `tests/test_styles.py`

**Interfaces:**
- Consumes: `db.connect`.
- Produces:
  - `@dataclass Style(id: int, label: str, description: str, prompt: str, provider: str, model: str, active: bool, position: int)`
  - `styles.seed(conn) -> None` (only if `styles` and `languages` are both empty)
  - `styles.list_styles(conn, active_only: bool) -> list[Style]` (ordered by position)
  - `styles.get_style(conn, id: int) -> Style | None`
  - `styles.create_style(conn, label, description, prompt, provider, model, active=True) -> Style` (position = max+1)
  - `styles.update_style(conn, id, **fields) -> Style | None`, `styles.delete_style(conn, id) -> bool`, `styles.reorder_styles(conn, ids: list[int]) -> None`
  - `styles.list_languages(conn) -> list[dict]` (`{"code","name"}`), `styles.set_languages(conn, items: list[dict]) -> None` (replace all, position = list order)
  - `PROVIDERS = ("anthropic", "openai")`; create/update raise `ValueError` for other providers or empty label/prompt/model.

- [ ] **Step 1: Write failing tests:**

```python
def test_seed(conn):
    styles.seed(conn); styles.seed(conn)
    assert [s.label for s in styles.list_styles(conn, True)] == ["Official", "Friendly", "Neutral"]
    assert all(s.provider == "anthropic" and s.model == "claude-sonnet-5-5" for s in styles.list_styles(conn, True))
    assert styles.list_languages(conn) == [{"code": "de-AT", "name": "German (Austria)"}]

def test_inactive_hidden(conn):
    s = styles.create_style(conn, "X", "", "p", "openai", "m", active=False)
    assert s.id not in [x.id for x in styles.list_styles(conn, True)]
    assert s.id in [x.id for x in styles.list_styles(conn, False)]

def test_reorder(conn):
    a = styles.create_style(conn, "A", "", "p", "openai", "m"); b = styles.create_style(conn, "B", "", "p", "openai", "m")
    styles.reorder_styles(conn, [b.id, a.id])
    assert [s.label for s in styles.list_styles(conn, False)] == ["B", "A"]

def test_bad_provider(conn):
    with pytest.raises(ValueError): styles.create_style(conn, "A", "", "p", "gemini", "m")
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Seed prompts (style instructions only, no output format), each mentioning Austrian conventions (e.g. "Jänner", "Grüß Gott"/"Liebe Grüße" where fitting):
  - Official: formal "Sie", complete sentences, polite and clear, suitable for authorities, landlords, schools, doctors; proper greeting and closing ("Mit freundlichen Grüßen").
  - Friendly: warm, "Du" unless the received message uses "Sie", natural WhatsApp tone, short sentences, "Liebe Grüße".
  - Neutral: "Sie", plain and polite, no extra warmth or stiffness, short.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit `feat: styles and languages store with seed`.

---

### Task 3: Frame (prompt building, schema, tweaks, parsing)

**Files:**
- Create: `src/translator/frame.py`, `tests/test_frame.py`

**Interfaces:**
- Produces:
  - `OUTPUT_SCHEMA: dict` — JSON Schema object, `additionalProperties: false`, required `["received_gist", "message", "back_translation"]`, all strings (`received_gist` is `""` in compose mode).
  - `TWEAKS: dict[str, tuple[str, str]]` — `id -> (button label, instruction)`, ids/labels per Global Constraints.
  - `@dataclass Output(received_gist: str, message: str, back_translation: str)` with `.to_dict()`.
  - `class FrameError(Exception)`.
  - `build_prompt(style_prompt: str, target_language: str, my_language: str, text: str, received: str | None = None, previous: Output | None = None, tweak: str | None = None) -> tuple[str, str]` → `(system, user)`.
  - `parse_output(data: object, reply_mode: bool) -> Output` — raises `FrameError` if not a dict, a field missing/not a string, `message` blank, or `reply_mode` and `received_gist` blank; strips whitespace.

System prompt must state: write a message ready to send in `target_language`; the user's text may be in any language and is what they want to say (intent, not text to translate literally); in reply mode, reply fitting the received message and summarize it in `my_language` as `received_gist`; `back_translation` is a faithful rendering of `message` in `my_language`; follow the style instructions (inserted verbatim under a "Style instructions" heading); never add facts the user didn't give; return only the JSON fields. User content wraps inputs in clearly labelled tags (`<received_message>`, `<what_i_want_to_say>`, and for tweaks `<previous_message>` + `<change_request>`) so inputs can't override the frame.

- [ ] **Step 1: Write failing tests:**

```python
def test_compose_prompt_contains_parts():
    system, user = frame.build_prompt("Be formal.", "German (Austria)", "English", "say no")
    assert "Be formal." in system and "German (Austria)" in system and "English" in system
    assert "<what_i_want_to_say>" in user and "say no" in user and "<received_message>" not in user

def test_reply_prompt_includes_received():
    _, user = frame.build_prompt("s", "German (Austria)", "English", "ok", received="Hallo")
    assert "<received_message>" in user and "Hallo" in user

def test_tweak_prompt():
    prev = frame.Output("", "Hallo", "Hello")
    _, user = frame.build_prompt("s", "de", "en", "x", previous=prev, tweak="shorter")
    assert "<previous_message>" in user and frame.TWEAKS["shorter"][1] in user

def test_unknown_tweak():
    with pytest.raises(ValueError): frame.build_prompt("s", "de", "en", "x", previous=frame.Output("", "a", "b"), tweak="louder")

def test_parse_ok_and_errors():
    assert frame.parse_output({"received_gist": "", "message": " Hi ", "back_translation": "Hi"}, False).message == "Hi"
    for bad in [None, [], {"message": "x"}, {"received_gist": "", "message": " ", "back_translation": "b"}]:
        with pytest.raises(frame.FrameError): frame.parse_output(bad, False)
    with pytest.raises(frame.FrameError):
        frame.parse_output({"received_gist": "", "message": "m", "back_translation": "b"}, True)

def test_tweak_ids():
    assert list(frame.TWEAKS) == ["shorter", "more_polite", "firmer", "less_formal"]
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit `feat: frame prompt, schema and tweaks`.

---

### Task 4: Provider adapters

**Files:**
- Create: `src/translator/providers.py`, `tests/test_providers.py`

**Interfaces:**
- Consumes: `frame.OUTPUT_SCHEMA` (passed in as `schema`).
- Produces:
  - `@dataclass Usage(input_tokens: int, output_tokens: int)`; `@dataclass Generation(data: object, usage: Usage)`
  - `class ProviderError(Exception)` (any HTTP error, timeout, non-2xx, unreadable body, refusal, missing structured output)
  - `async def generate(provider: str, api_key: str, model: str, system: str, user: str, schema: dict, http: httpx.AsyncClient) -> Generation`
  - `async def list_models(provider: str, api_key: str, http: httpx.AsyncClient) -> list[str]` (sorted ids)

Wire formats:
- **Anthropic**: `POST https://api.anthropic.com/v1/messages`, headers `x-api-key`, `anthropic-version: 2023-06-01`; body `{model, max_tokens: 2048, system, messages:[{role:"user",content:user}], tools:[{name:"submit", description:"Return the result", input_schema: schema}], tool_choice:{type:"tool", name:"submit"}}`. Data = the `input` of the first `tool_use` block; usage from `usage.input_tokens/output_tokens`. Models: `GET /v1/models` → `data[].id`.
- **OpenAI**: `POST https://api.openai.com/v1/chat/completions`, `Authorization: Bearer`; body `{model, store: false, messages:[{role:"system",...},{role:"user",...}], response_format:{type:"json_schema", json_schema:{name:"result", strict:true, schema}}}`. Data = `json.loads(choices[0].message.content)`; `message.refusal` set → ProviderError. Usage from `usage.prompt_tokens/completion_tokens`. Models: `GET /v1/models` → `data[].id`.
- Timeout 60 s per call. Unknown provider → `ValueError`.

- [ ] **Step 1: Write failing tests** using `httpx.MockTransport` handlers that capture the request:

```python
async def test_anthropic_generate():
    seen = {}
    def h(req):
        seen["body"] = json.loads(req.content); seen["key"] = req.headers["x-api-key"]
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "submit", "input": {"message": "Hallo"}}],
                                         "usage": {"input_tokens": 10, "output_tokens": 5}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as http:
        g = await providers.generate("anthropic", "k", "claude-sonnet-5-5", "S", "U", {"type": "object"}, http)
    assert g.data == {"message": "Hallo"} and g.usage == providers.Usage(10, 5)
    assert seen["key"] == "k" and seen["body"]["tool_choice"] == {"type": "tool", "name": "submit"}

async def test_openai_generate_store_false():
    seen = {}
    def h(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"message": "Hallo"}'}}],
                                         "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as http:
        g = await providers.generate("openai", "k", "m", "S", "U", {"type": "object"}, http)
    assert seen["body"]["store"] is False and g.data == {"message": "Hallo"} and g.usage == providers.Usage(7, 3)

@pytest.mark.parametrize("resp", [httpx.Response(500), httpx.Response(401, json={}), httpx.Response(200, text="nope"),
    httpx.Response(200, json={"choices": [{"message": {"content": None, "refusal": "no"}}], "usage": {}})])
async def test_openai_errors(resp):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: resp)) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate("openai", "k", "m", "S", "U", {}, http)

async def test_anthropic_no_tool_use():
    r = httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 1, "output_tokens": 1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda q: r)) as http:
        with pytest.raises(providers.ProviderError):
            await providers.generate("anthropic", "k", "m", "S", "U", {}, http)

async def test_list_models():
    r = httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda q: r)) as http:
        assert await providers.list_models("openai", "k", http) == ["a", "b"]
```

Also a timeout test: handler raises `httpx.ReadTimeout` → `ProviderError`.

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit `feat: anthropic and openai adapters`.

---

### Task 5: Usage, cost and daily cap

**Files:**
- Create: `src/translator/usage.py`, `tests/test_usage.py`

**Interfaces:**
- Consumes: `Settings.prices()`, `Settings.cap_eur()`, `providers.Usage`.
- Produces:
  - `today(now: datetime | None = None) -> str` — ISO date in `Europe/Vienna`.
  - `cost_eur(prices: dict, model: str, usage: Usage) -> float` — 0.0 if model unpriced.
  - `record(conn, settings, style_id: int, model: str, usage: Usage, now: datetime | None = None) -> None`
  - `spent_today(conn, now: datetime | None = None) -> float`
  - `cap_reached(conn, settings, now: datetime | None = None) -> bool` — False when no cap.
  - `summary(conn, settings, days: int = 30) -> dict` — `{"days": [{"day", "requests", "cost_eur"}], "by_style": [{"style_id", "label", "requests", "cost_eur"}], "spent_today": float, "unpriced_models": [str]}` (`unpriced_models` = models in usage within `days` with no price entry).

- [ ] **Step 1: Write failing tests:**

```python
def test_cost(): assert usage.cost_eur({"m": {"in": 3.0, "out": 15.0}}, "m", Usage(1_000_000, 100_000)) == pytest.approx(4.5)
def test_unpriced(): assert usage.cost_eur({}, "m", Usage(10, 10)) == 0.0

def test_vienna_day_boundary():
    # 23:30 UTC on 2026-11-19 is 00:30 on 2026-11-20 in Vienna (CET, UTC+1)
    assert usage.today(datetime(2026, 11, 19, 23, 30, tzinfo=timezone.utc)) == "2026-11-20"

def test_cap(conn, settings):
    settings.set("prices", json.dumps({"m": {"in": 1.0, "out": 1.0}})); settings.set("cap_eur", "1.0")
    t = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    usage.record(conn, settings, 1, "m", Usage(600_000, 0), now=t)
    assert not usage.cap_reached(conn, settings, now=t)
    usage.record(conn, settings, 1, "m", Usage(500_000, 0), now=t)
    assert usage.cap_reached(conn, settings, now=t)
    assert not usage.cap_reached(conn, settings, now=t + timedelta(days=1))

def test_summary_lists_unpriced(conn, settings):
    usage.record(conn, settings, 1, "mystery", Usage(1, 1))
    assert usage.summary(conn, settings)["unpriced_models"] == ["mystery"]
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (`zoneinfo.ZoneInfo("Europe/Vienna")`). **Step 4:** PASS. **Step 5:** Commit `feat: usage tracking and daily cap`.

---

### Task 6: Sessions, Turnstile, Clerk, app skeleton and access rules

**Files:**
- Create: `src/translator/{sessions,turnstile,clerk,app,__main__}.py`, `tests/test_access.py`
- Copy from: `/Users/mahmoudparham/projects/claude_proxy/src/claude_proxy/turnstile.py` (as is) and `clerk.py` (keep `frontend_api`, `Verifier.verify`, `Verifier.email`; drop `proxy_url` and `delete_user`; constructor `Verifier(publishable_key, secret_key, origin, http)`).

**Interfaces:**
- Consumes: Tasks 1, 2, 5.
- Produces:
  - `sessions.COOKIE = "tr_session"`, TTL 12 h for anon, 30 days for users. `sessions.issue(crypto, kind: str, user_id: str | None = None, now=None) -> str`, `sessions.read(crypto, cookie: str | None, now=None) -> dict | None` (`{"kind": "anon"|"user", "uid": str|None}`; expired → None). Cookie flags: HttpOnly, SameSite=Lax, Secure when `APP_URL` is https.
  - `app.create_app(cfg: Config, http: httpx.AsyncClient | None = None, generate=providers.generate, verify_turnstile=turnstile.verify, clerk_verifier=None) -> FastAPI` — test hooks: `generate` and `verify_turnstile` are injectable; `clerk_verifier` is any object with `async verify(token) -> claims` and `async email(user_id) -> str` (built from cfg when None and Clerk keys are set). Calls `styles.seed` on startup.
  - Dependency helpers in `app.py`: `current_session(request) -> dict | None`, `require_session` (401 `{"error": "Session expired, reload the page"}`), `require_admin` (403 unless user session whose email (from `users` table) is in `cfg.admin_emails`).
  - `is_open(conn, settings) -> bool` = `settings.enabled()` and Turnstile site key + secret set and not `usage.cap_reached`.
  - Routes:
    - `GET /` → `static/index.html`; `GET /admin` → `static/admin.html`; `/static/*`.
    - `GET /health` → `{"ok": true}`.
    - `GET /api/config` → `{"open": bool, "turnstile_site_key": str|None, "clerk_publishable_key": str|None, "styles": [{"id","label","description"}], "languages": [{"code","name"}], "tweaks": [{"id","label"}], "user": {"email", "is_admin"}|None}`.
    - `POST /api/session` `{"turnstile_token"}` → verifies with secret + client IP; ok → set anon cookie, `{"ok": true}`; rejected → 403; `TurnstileUnavailable` → 503.
    - `POST /api/login/clerk` `{"token"}` → verify, fetch email, upsert `users`, set user cookie, `{"email", "is_admin"}`; `ClerkError` → 401.
    - `POST /api/logout` → clear cookie.
  - Security headers middleware: CSP allowing `'self'`, the Clerk Frontend API host, `https://challenges.cloudflare.com` (script + frame), `https://img.clerk.com` (img).

- [ ] **Step 1: Write failing tests** (`TestClient(create_app(cfg, verify_turnstile=fake, clerk_verifier=FakeClerk()))`; set Turnstile keys in settings in a fixture `client`):

```python
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
    r = client.post("/api/login/clerk", json={"token": "admin"})   # FakeClerk maps token -> user_admin / admin@x.test
    assert r.json() == {"email": "admin@x.test", "is_admin": True}
    assert client.get("/api/config").json()["user"]["is_admin"] is True

def test_bad_clerk_token(client): assert client.post("/api/login/clerk", json={"token": "bad"}).status_code == 401

def test_admin_route_forbidden_for_anon_and_users(client):
    client.post("/api/session", json={"turnstile_token": "t"})
    assert client.get("/api/admin/settings").status_code == 403
    client.post("/api/login/clerk", json={"token": "user"})
    assert client.get("/api/admin/settings").status_code == 403

def test_expired_session_cookie(crypto):
    tok = sessions.issue(crypto, "anon", now=0)
    assert sessions.read(crypto, tok, now=13 * 3600) is None
```

(`/api/admin/settings` is added in Task 9; here register it as a stub behind `require_admin` returning `{}` so the access test exists from the start.)

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; `__main__.py` runs `uvicorn.run(create_app(from_env()), host=cfg.host, port=cfg.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")`. Client IP for Turnstile: `CF-Connecting-IP` header if present, else `request.client.host`. **Step 4:** PASS. **Step 5:** Commit `feat: sessions, turnstile, clerk sign-in and access rules`.

---

### Task 7: Generate and tweak endpoints

**Files:**
- Modify: `src/translator/app.py`
- Create: `tests/test_generate.py`

**Interfaces:**
- Consumes: `frame.build_prompt/parse_output/OUTPUT_SCHEMA/TWEAKS`, `generate` hook, `usage.record`, `history.save` (Task 8 — in this task call it only through a function `app._maybe_save(...)` that Task 8 fills; until then it returns None).
- Produces:
  - `POST /api/generate` body `{"style_id": int, "language_code": str, "my_language": str, "text": str, "received": str|null, "save": bool, "history_id": str|null}`
  - `POST /api/tweak` same body plus `{"tweak": str, "previous": {"received_gist","message","back_translation"}}`
  - Response 200: `{"result": {"received_gist","message","back_translation"}, "history_id": str|null}` (`history_id` only for signed-in users with `save: true`).
  - Errors (JSON `{"error": ...}`): 401 no session; 503 `"Temporarily unavailable"` when not `is_open`; 400 `"Text is too long (max 8000 characters)"`; 400 `"Please write what you want to say"` for blank `text` on generate; 400 `"This style is not available"` (missing/inactive); 400 `"This style is not configured yet"` (no API key for its provider); 400 `"Unknown language"`; 400 `"Unknown change"` for bad tweak; 502 `"Couldn't generate, try again"` on `ProviderError` or `FrameError`.
  - Language name passed to the frame = `languages.name` for `language_code`; `my_language` is a free display name from the client's fixed list (max 40 chars).
  - Usage recorded on every successful provider response (even if parsing then fails, since tokens were spent).

- [ ] **Step 1: Write failing tests** (fake `generate` returns a `Generation` or raises; signed-in anon session fixture `anon_client`; anthropic key set in fixture):

```python
def test_generate_reply_mode(anon_client, fake_gen):
    fake_gen.data = {"received_gist": "Landlord asks", "message": "Sehr geehrter…", "back_translation": "Dear…"}
    r = anon_client.post("/api/generate", json=body(received="Hallo", text="no"))
    assert r.status_code == 200 and r.json()["result"]["message"] == "Sehr geehrter…" and r.json()["history_id"] is None
    assert "<received_message>" in fake_gen.calls[0]["user"] and fake_gen.calls[0]["model"] == "claude-sonnet-5-5"

def test_requires_session(client): assert client.post("/api/generate", json=body()).status_code == 401

def test_closed_when_switched_off(anon_client, settings):
    settings.set("enabled", "0")
    assert anon_client.post("/api/generate", json=body()).status_code == 503

def test_too_long(anon_client, fake_gen):
    r = anon_client.post("/api/generate", json=body(text="x" * 8001))
    assert r.status_code == 400 and "too long" in r.json()["error"] and fake_gen.calls == []

def test_inactive_style(anon_client, conn):
    styles.update_style(conn, 1, active=False)
    assert anon_client.post("/api/generate", json=body(style_id=1)).json()["error"] == "This style is not available"

def test_missing_key(anon_client, settings):
    settings.set_secret("anthropic_api_key", None)
    assert anon_client.post("/api/generate", json=body()).json()["error"] == "This style is not configured yet"

@pytest.mark.parametrize("failure", ["provider_error", "bad_json"])
def test_provider_failure(anon_client, fake_gen, failure):
    fake_gen.fail = failure
    r = anon_client.post("/api/generate", json=body())
    assert r.status_code == 502 and r.json()["error"] == "Couldn't generate, try again"

def test_usage_recorded(anon_client, fake_gen, conn):
    anon_client.post("/api/generate", json=body())
    assert conn.execute("select count(*) from usage").fetchone()[0] == 1

def test_tweak(anon_client, fake_gen):
    r = anon_client.post("/api/tweak", json=body(tweak="shorter", previous={"received_gist": "", "message": "Hallo lang", "back_translation": "Hello"}))
    assert r.status_code == 200 and "<previous_message>" in fake_gen.calls[0]["user"]
    assert anon_client.post("/api/tweak", json=body(tweak="louder", previous={"received_gist": "", "message": "a", "back_translation": "b"})).status_code == 400
```

(`body(**kw)` helper defaults: `style_id=1, language_code="de-AT", my_language="English", text="say no", received=None, save=True, history_id=None`.)

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: generate and tweak endpoints`.

---

### Task 8: History

**Files:**
- Create: `src/translator/history.py`, `tests/test_history.py`
- Modify: `src/translator/app.py` (fill `_maybe_save`, add routes)

**Interfaces:**
- Produces:
  - `history.save(conn, user_id: str, item_id: str | None, style_label: str, language_code: str, inputs: dict, output: dict, now=None) -> str` — `item_id` None → new uuid4 insert; existing id owned by user → update `output`, `inputs`, `updated_at`; id owned by another user → `PermissionError`.
  - `history.list_items(conn, user_id, limit=200) -> list[dict]` newest `updated_at` first; each `{"id","created_at","updated_at","style_label","language_code","inputs","output"}`.
  - `history.delete(conn, user_id, item_id) -> bool`, `history.delete_all(conn, user_id) -> int`.
  - `history.import_items(conn, user_id, items: list[dict]) -> int` — insert-or-ignore by `id` (must be a UUID string) for this user; ids existing for another user are skipped; max 200 items; returns number inserted.
  - Routes (user session required, else 401): `GET /api/history`, `DELETE /api/history/{id}` (404 if not theirs), `DELETE /api/history`, `POST /api/history/import {"items": [...]}` → `{"imported": n}`.
  - `inputs` stored = `{"text","received","my_language"}`; generate/tweak save only when session kind is `user` and `save` is true; tweak with `history_id` updates that item.

- [ ] **Step 1: Write failing tests:**

```python
def test_generate_then_tweak_updates_same_item(user_client, fake_gen):
    hid = user_client.post("/api/generate", json=body()).json()["history_id"]
    fake_gen.data = {**fake_gen.data, "message": "kurz"}
    hid2 = user_client.post("/api/tweak", json=body(tweak="shorter", history_id=hid, previous=PREV)).json()["history_id"]
    items = user_client.get("/api/history").json()
    assert hid2 == hid and len(items) == 1 and items[0]["output"]["message"] == "kurz"

def test_dont_save(user_client):
    assert user_client.post("/api/generate", json=body(save=False)).json()["history_id"] is None
    assert user_client.get("/api/history").json() == []

def test_anon_has_no_history(anon_client):
    assert anon_client.get("/api/history").status_code == 401

def test_import_idempotent(user_client):
    items = [{"id": str(uuid.uuid4()), "created_at": "2026-11-19T10:00:00Z", "style_label": "Official",
              "language_code": "de-AT", "inputs": {"text": "a"}, "output": {"message": "b"}}]
    assert user_client.post("/api/history/import", json={"items": items}).json() == {"imported": 1}
    assert user_client.post("/api/history/import", json={"items": items}).json() == {"imported": 0}

def test_cannot_touch_others_items(conn):
    i = history.save(conn, "user_a", None, "Official", "de-AT", {}, {"message": "x"})
    with pytest.raises(PermissionError): history.save(conn, "user_b", i, "Official", "de-AT", {}, {"message": "y"})
    assert history.delete(conn, "user_b", i) is False
    assert history.import_items(conn, "user_b", [{"id": i, "output": {}, "inputs": {}}]) == 0

def test_delete_all(user_client):
    user_client.post("/api/generate", json=body()); user_client.delete("/api/history")
    assert user_client.get("/api/history").json() == []

def test_deleted_style_history_still_lists(user_client, conn):
    user_client.post("/api/generate", json=body()); styles.delete_style(conn, 1)
    assert user_client.get("/api/history").json()[0]["style_label"] == "Official"
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: signed-in history`.

---

### Task 9: Admin API

**Files:**
- Modify: `src/translator/app.py`
- Create: `tests/test_admin.py`

**Interfaces:**
- All under `require_admin`:
  - `GET /api/admin/settings` → `{"enabled": bool, "cap_eur": float|null, "prices": {...}, "turnstile_site_key": str|null, "secrets": {"openai_api_key": "…1234"|null, "anthropic_api_key": ..., "turnstile_secret": ...}, "open": bool}`
  - `PUT /api/admin/settings` partial body with any of: `enabled`, `cap_eur` (null clears), `prices`, `turnstile_site_key`, `openai_api_key`, `anthropic_api_key`, `turnstile_secret` (empty string clears a secret). Returns same shape as GET.
  - `GET /api/admin/styles` (all, incl. inactive, full fields), `POST /api/admin/styles`, `PUT /api/admin/styles/{id}`, `DELETE /api/admin/styles/{id}`, `PUT /api/admin/styles/order {"ids": [...]}`; `ValueError` → 400.
  - `GET /api/admin/languages`, `PUT /api/admin/languages {"items": [{"code","name"}]}` (non-empty list, codes unique, else 400).
  - `GET /api/admin/models?provider=openai` → `{"models": [...]}`; no key → 400; `ProviderError` → 502.
  - `POST /api/admin/try` `{"prompt", "provider", "model", "language_code", "my_language", "text", "received"}` → same response as generate (not saved, usage recorded with `style_id` NULL); works even when the app is switched off.
  - `GET /api/admin/usage` → `usage.summary(...)`.

- [ ] **Step 1: Write failing tests:**

```python
def test_settings_never_return_keys(admin_client):
    admin_client.put("/api/admin/settings", json={"openai_api_key": "sk-secret9876"})
    j = admin_client.get("/api/admin/settings").json()
    assert j["secrets"]["openai_api_key"] == "…9876" and "sk-secret9876" not in json.dumps(j)

def test_clear_secret(admin_client):
    admin_client.put("/api/admin/settings", json={"openai_api_key": "x1234"})
    admin_client.put("/api/admin/settings", json={"openai_api_key": ""})
    assert admin_client.get("/api/admin/settings").json()["secrets"]["openai_api_key"] is None

def test_switch_off(admin_client, anon_client):
    admin_client.put("/api/admin/settings", json={"enabled": False})
    assert anon_client.post("/api/generate", json=body()).status_code == 503

def test_style_crud(admin_client):
    s = admin_client.post("/api/admin/styles", json={"label": "Short", "description": "", "prompt": "p", "provider": "openai", "model": "m"}).json()
    admin_client.put(f"/api/admin/styles/{s['id']}", json={"active": False})
    assert "Short" not in [x["label"] for x in admin_client.get("/api/config").json()["styles"]]
    assert admin_client.post("/api/admin/styles", json={"label": "", "prompt": "p", "provider": "openai", "model": "m"}).status_code == 400

def test_languages_validation(admin_client):
    assert admin_client.put("/api/admin/languages", json={"items": []}).status_code == 400

def test_try_works_when_off(admin_client, fake_gen):
    admin_client.put("/api/admin/settings", json={"enabled": False})
    r = admin_client.post("/api/admin/try", json={"prompt": "p", "provider": "anthropic", "model": "m", "language_code": "de-AT", "my_language": "English", "text": "hi", "received": None})
    assert r.status_code == 200
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: admin api`.

---

### Task 10: Main page (frontend)

**Files:**
- Create: `src/translator/static/index.html`, `app.js`, `app.css`

**Interfaces:**
- Consumes: `/api/config`, `/api/session`, `/api/login/clerk`, `/api/logout`, `/api/generate`, `/api/tweak`, `/api/history*`.

Behaviour (layout per the spec's main-screen sketch, mobile-first, single column ≤ 640 px wide):
- On load: `GET /api/config`. If `open` is false → show "Temporarily unavailable" and disable Generate. If no user → render Turnstile (`https://challenges.cloudflare.com/turnstile/v0/api.js`, site key from config, `appearance: "interaction-only"`), on token `POST /api/session`. On 401 from any call → re-run Turnstile once and retry.
- Clerk: if `clerk_publishable_key`, load Clerk JS from its Frontend API (`https://<fapi>/npm/@clerk/clerk-js@5/dist/clerk.browser.js` with `data-clerk-publishable-key`); "Sign in" opens `Clerk.openSignIn()`; on session → `POST /api/login/clerk` with `await Clerk.session.getToken()`; then offer "Move N items from this browser to your account?" → `/api/history/import`, clear local on success. "Sign out" → `/api/logout` + `Clerk.signOut()`.
- Form: received (optional textarea), text (textarea), Style select (label; description shown under it), To select, My language select (fixed list of ~30 languages, default from `navigator.language`), "Don't save this one" checkbox, Generate.
- Result: gist (only if non-empty), message box, Copy (`navigator.clipboard.writeText`, button shows "Copied ✓"), WhatsApp (`https://wa.me/?text=` + `encodeURIComponent(message)`), "Means: …" back-translation, four tweak buttons. Spinner + disabled buttons while a request runs; errors shown inline from `error`.
- Remembered in `localStorage` (`rt.prefs`): style id, language code, my language.
- History panel (collapsible): signed in → server list; anonymous → `localStorage` `rt.history` (max 100, newest first, each item has a `crypto.randomUUID()` id, updated in place on tweak). Tap item → loads inputs + output into the form/result. Per-item delete and "Delete all".

- [ ] **Step 1:** Implement the page.
- [ ] **Step 2: Verify in a browser** (use the `run` skill / Playwright): start the app locally with Turnstile test keys (site key `1x00000000000000000000AA`, secret `1x0000000000000000000000000000000AA`) and a fake provider (`TRANSLATOR_FAKE_PROVIDER=1` env makes `__main__` pass a canned `generate` — add this hook, off by default). Check: compose and reply mode render correctly; Copy works; WhatsApp link encodes umlauts; tweak replaces the result and keeps one history item; anonymous history survives reload; phone width (390 px) has no horizontal scroll.
- [ ] **Step 3:** Commit `feat: main page`.

---

### Task 11: Admin page (frontend)

**Files:**
- Create: `src/translator/static/admin.html`, `admin.js` (reuses `app.css`)

Behaviour: on load Clerk sign-in (same as Task 10); `GET /api/admin/settings` → 403 shows "Admins only". Sections:
- **Status**: on/off toggle, `open` state with reason (switched off / Turnstile keys missing / cap reached).
- **Keys**: OpenAI, Anthropic, Turnstile secret as password inputs showing "set …1234" placeholder; Save sends only changed fields; Clear button sends `""`. Turnstile site key as plain input.
- **Styles**: list in order with up/down buttons (→ order endpoint), active toggle, edit form (label, description, prompt textarea, provider select, model input with a datalist filled from `/api/admin/models`), "Try it" box (text + optional received → `/api/admin/try`, shows result), delete with confirm.
- **Languages**: editable rows code + name, add/remove, Save.
- **Spending**: cap (€/day, empty = none), price table per model (€ per 1M in/out), usage table from `/api/admin/usage` (last 30 days, by style, spent today), warning listing `unpriced_models`.

- [ ] **Step 1:** Implement.
- [ ] **Step 2: Verify in a browser** with the fake provider: as admin, edit a style's prompt and see it used by Try it; deactivate a style and confirm it disappears from the main page; switch off and confirm the main page shows "Temporarily unavailable"; keys never appear in page source or network responses.
- [ ] **Step 3:** Commit `feat: admin page`.

---

### Task 12: Docker and deployment

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `deploy/lightsail/docker-compose.yml`, `deploy/lightsail/update.sh`, `deploy/lightsail/translator-backup`, `deploy/lightsail/README.md`, `README.md`

**Interfaces:**
- Dockerfile: `python:3.12-slim`, `pip install .`, non-root user `translator`, `/data` volume, `ENV TRANSLATOR_DB=/data/translator.db`, `CMD ["python", "-m", "translator"]`.
- Compose (project name `translator`): service `translator`, image `translator:${TRANSLATOR_TAG:-latest}`, `network_mode: host`, `restart: unless-stopped`, `mem_limit: 128m`, `env_file: translator.env` (chmod 600; holds the five env vars), `TRANSLATOR_HOST=127.0.0.1`, `TRANSLATOR_PORT=18490`, volume `translator_data:/data` (external), json-file logging 10m×3.
- `update.sh user@host`: modelled on claude_proxy's `deploy/lightsail/update.sh` — rsync to `~/translator/` (excluding `.git`, `.venv`, `*.db*`, `*.env`, `docs`, `tests`), build tagged image, write `.env` with `TRANSLATOR_TAG`, `docker compose up -d --no-build`, wait for `http://127.0.0.1:18490/health` up to 30 s.
- `translator-backup`: modelled on claude_proxy's `claude-gateway-backup` (SQLite backup API → gzip → `age -R` recipients file `/usr/local/etc/translator-backup.age.pub`), volume `translator_data`.
- `deploy/lightsail/README.md`: first-time steps — create volume, write `translator.env`, create Clerk production app for `translate.rahkar.pro`, create Turnstile widget for that hostname, add Cloudflare tunnel route `translate.rahkar.pro → http://127.0.0.1:18490` on the `claude-gateway` tunnel (dashboard → Networking → Tunnels → Routes), run `update.sh`, sign in with an `ADMIN_EMAILS` address and set keys at `/admin`.

- [ ] **Step 1:** Write files.
- [ ] **Step 2: Verify:** `docker build -t translator:test . && docker run --rm -d --name tr -p 18490:18490 -e APP_URL=http://localhost:18490 -e APP_SECRET_KEY=$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())') -e TRANSLATOR_HOST=0.0.0.0 -e TRANSLATOR_DB=/tmp/t.db translator:test && sleep 3 && curl -fsS localhost:18490/health; docker rm -f tr` → prints `{"ok":true}`. `bash -n deploy/lightsail/update.sh deploy/lightsail/translator-backup` → no output.
- [ ] **Step 3:** Run full suite `uv run pytest -q` → all pass.
- [ ] **Step 4:** Commit `feat: docker image and lightsail deploy`. (Actual deploy to the box is a separate step, done only when the user asks.)
