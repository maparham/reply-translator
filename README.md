# Reply Translator

A small web app that turns a short message you write in your own language into a reply in another language
(German as spoken in Austria by default), in a chosen style (Official, Friendly, Neutral), with quick tweaks
(shorter, more polite, firmer, less formal). It can also explain a message you received. Anonymous visitors are
protected by Cloudflare Turnstile; signed-in users (Clerk) keep a history. An admin page (`/admin`) holds the
provider API keys (stored encrypted), styles, languages, the on/off switch and the daily spending cap.

FastAPI backend, SQLite storage, plain HTML/JS frontend in `src/translator/static`.

## Local development

```sh
uv sync
export APP_URL=http://localhost:18490
export APP_SECRET_KEY=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export CLERK_PUBLISHABLE_KEY=pk_test_...
export CLERK_SECRET_KEY=sk_test_...
export ADMIN_EMAILS=you@example.com
export TRANSLATOR_DB=./translator.db        # default is /data/translator.db
# optional: export ANTHROPIC_BASE_URL=https://claude.rahkar.pro   (or OPENAI_BASE_URL) to use a compatible gateway
uv run python -m translator                 # open http://localhost:18490
```

Use `localhost` consistently: every non-GET `/api/*` request must carry an `Origin` header equal to the origin of
`APP_URL`, so opening the app as `http://127.0.0.1:18490` while `APP_URL` says `localhost` gets 403 "Bad origin".
Change `APP_URL` if you use another host or port.

`TRANSLATOR_HOST` (default `127.0.0.1`) and `TRANSLATOR_PORT` (default `18490`) change the listener.

- `TRANSLATOR_FAKE_PROVIDER=1` replaces the AI providers with a canned responder, handy for UI work without keys.
- Cloudflare's Turnstile test keys work locally: site key `1x00000000000000000000AA` (always passes),
  `2x00000000000000000000AB` (always blocks); secret key `1x0000000000000000000000000000000AA` (always passes),
  `2x0000000000000000000000000000000AA` (always fails). Enter them at `/admin`.

## Tests

```sh
uv run pytest -q
```

## Deployment

Docker image plus Lightsail files: see [deploy/lightsail/README.md](deploy/lightsail/README.md).
