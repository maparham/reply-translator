# Reply Translator — Design

Date: 2026-11-19
Status: draft, awaiting approval (hosting, domain and Clerk decided 2026-11-19)

## Intent

People living somewhere whose language they don't speak (the motivating case: Austria, German) need to write
WhatsApp messages and emails to landlords, offices, schools, doctors and neighbours. Google Translate and DeepL
translate literally; the result usually needs manual fixing to fit the audience (tone, Du/Sie, local
conventions). This app produces a message that is **ready to copy and send**, shaped by a style prompt an admin
has written ("Official", "Friendly", …).

Success: a user pastes text, picks a style, copies the result into WhatsApp/email without editing it.

## Goals (v1)

1. **Translate / compose**: user writes what they want to say (any language, rough is fine) → message in the
   target language, in the chosen style.
2. **Reply mode**: user optionally pastes the message they received. They get (a) the received message's meaning
   in their own language and (b) a reply that fits the conversation.
3. **Back-translation**: every result shows what it says in the user's language, so they can trust it.
4. **Tweak buttons**: "Shorter", "More polite", "Firmer", "Less formal" refine the last result without
   starting over.
5. **Styles are admin prompts**: each has a label (Official, Friendly, …), a short description, the instruction
   text, a provider (OpenAI or Anthropic) and a model. Du/Sie and Austrian conventions ("Jänner", "Grüß Gott",
   "Liebe Grüße") live inside these prompts — no separate feature.
6. **Open access**: no login needed to use it.
7. **Optional accounts (Clerk)**: signed-in users get server-side history synced across devices.
8. **Admin page**: API keys, styles, target languages, on/off switch, optional daily spending cap, Turnstile keys.
9. **One-click copy** and a "Send via WhatsApp" link (`https://wa.me/?text=…`).

## Non-goals (v1)

- Payment, tiers, per-user quotas or per-visitor rate limits (user explicitly doesn't care about heavy human use).
- Ready-made situation templates, side-by-side prompt testing for the admin, cultural notes (later).
- DeepL/Google integration, document/file translation, voice, native apps.
- UI localisation (UI is English in v1 — my call; the user's own language is still used for back-translation).

## Anti-goals (failure even if it works)

- Output that still needs manual fixing — the whole point.
- API keys ever reaching the browser.
- Storing anonymous users' message content on the server (their history lives in their browser only).
- A slow or fiddly flow on a phone — this is used mostly on mobile, mid-conversation.

## Constraints

- Admin pays for all AI calls with their own OpenAI and Anthropic keys; usage is free for everyone.
- Abuse protection = Cloudflare Turnstile (bots) + on/off switch + optional daily € cap. Nothing more.
- Reuse the stack and patterns of `/Users/mahmoudparham/projects/claude_proxy`, which the user already runs.

## Approaches considered

- **A. Same stack as claude_proxy — chosen.** Python 3.12 + FastAPI + SQLite + vanilla HTML/JS, Docker. Reuses
  `clerk.py` (Clerk JWT verification without the SDK), `turnstile.py`, and the encrypted-credentials pattern
  (`credentials.py`). One stack the user already knows how to run and back up.
- **B. Next.js + `@clerk/nextjs` on Vercel.** Least Clerk glue, free hosting, but a second stack to maintain and
  the keys/history live on Vercel. Rejected for that.
- **Static site + serverless functions.** Rejected: storing history and admin settings becomes awkward.

## Design

### Users and access

- **Anonymous user**: opens the page. Turnstile runs (usually invisible); the server verifies the token once and
  sets a signed, HttpOnly session cookie (~12 h). `/api/*` translation endpoints reject requests without it.
- **Signed-in user**: Clerk sign-in widget in the browser (email code / Google, whatever the Clerk instance has
  on); the browser sends its Clerk session token to `/api/login/clerk`, the server verifies it (as in
  claude_proxy) and issues its own session cookie tied to the user. Signing in is never required.
- **Admin**: a Clerk user whose email is in `ADMIN_EMAILS` (env var). My call: reuse Clerk instead of a separate
  admin password.
- **Off switch**: when off, the page shows "Temporarily unavailable" and translation endpoints return 503.

### Main screen (mobile-first)

```
┌──────────────────────────────────────────┐
│ Reply Translator             [Sign in]   │
│                                          │
│ Message you received (optional)          │
│ ┌──────────────────────────────────────┐ │
│ │ Sehr geehrter Herr …                 │ │
│ └──────────────────────────────────────┘ │
│ What you want to say (any language)      │
│ ┌──────────────────────────────────────┐ │
│ │ say no, I can only do Tuesday        │ │
│ └──────────────────────────────────────┘ │
│ Style  [Official ▾]   To  [German (AT) ▾]│
│ My language [English ▾]                  │
│              [ Generate ]                │
│ ──────────────────────────────────────── │
│ They wrote (gist): The landlord asks …   │
│ ┌ Reply ───────────────────────────────┐ │
│ │ Sehr geehrter Herr Huber, …          │ │
│ └──────────────────────────────────────┘ │
│ [Copy] [WhatsApp]                        │
│ Means: "Dear Mr Huber, …"                │
│ [Shorter] [More polite] [Firmer] [Less formal] │
│ ──────────────────────────────────────── │
│ History ▸                                │
└──────────────────────────────────────────┘
```

- "Message you received" empty → compose mode; filled → reply mode (same screen, no mode toggle).
- Style dropdown shows label + description of each active style, in admin's order.
- "To" list = target languages the admin enabled (default: German (Austria)). "My language" is remembered in
  the browser (default from browser locale).
- Last choices (style, languages) remembered in localStorage.

### How a request is built

The app owns a fixed **frame** (system prompt) that defines the task and output format; the admin's style prompt
is inserted into it. So admins write only style instructions ("formal, Sie, Austrian conventions, short
paragraphs…"), never output-format rules.

Inputs: received message (optional), user's text, target language, user's language, style prompt.
Output (one call, JSON — structured output on both providers):

- `received_gist` (user's language; only in reply mode)
- `message` (target language — the thing to copy)
- `back_translation` (user's language)

Tweaks: a follow-up call with the previous inputs and output plus the tweak instruction; returns the same JSON.
The tweak list is fixed in v1 (the four above).

No streaming in v1 (outputs are short); show a spinner. Builder may add streaming if it's cheap.

### Providers and models

- Provider adapters for **Anthropic** (Messages API) and **OpenAI** (Responses or Chat Completions API), behind
  one interface: `generate(frame, inputs, model) -> {received_gist, message, back_translation, usage}`.
- Each style picks provider + model. Admin types the model ID, with a dropdown filled from the provider's
  models-list endpoint when a key is set. Defaults: latest Claude Sonnet (`claude-sonnet-5-5`) and a current
  OpenAI mid-tier model.
- Errors from the provider → a plain "Couldn't generate, try again" for the user; details in server logs.

### History

- **Anonymous**: localStorage only, last ~100 items. Server keeps no message content for anonymous users (not
  even in logs).
- **Signed in**: stored in SQLite per user. On sign-in, the browser offers to upload its local history.
- Each item: time, inputs, style label, target language, final output (after tweaks). Tap → reload into the
  form. Copy from history directly.
- Per-item delete, "Delete all my history", and a "Don't save this one" toggle on the form.

### Admin page (`/admin`)

- **API keys**: OpenAI, Anthropic. Stored encrypted in SQLite with a key from env (`APP_SECRET_KEY`), as in
  claude_proxy. Write-only in the UI (shows "set ✓ / last 4 chars").
- **Styles**: create/edit/reorder/activate; fields: label, description, prompt text, provider, model. A "Try it"
  box on the edit form to run the style once before saving.
- **Target languages**: list of enabled languages with display names (e.g. "German (Austria)").
- **On/off switch**.
- **Daily spending cap** (optional, off by default): admin enters price per 1M input/output tokens per model;
  the app sums today's estimated cost from returned token usage; over the cap → same as "off" until midnight
  (Europe/Vienna).
- **Turnstile** site key + secret; **Clerk** keys come from env (they're needed at startup).
- **Usage** view: counts and estimated cost per day/style (no message content).

Seed on first start: three styles — Official, Friendly, Neutral — with sensible Austrian-German prompts, and
German (Austria) as the only target language.

### Data (SQLite)

`settings` (key/value incl. encrypted API keys, switch, cap), `styles`, `languages`, `users` (Clerk user id,
email), `history` (user_id, created_at, inputs JSON, output JSON, style label, language), `usage`
(date, style_id, model, input_tokens, output_tokens, est_cost — no content).

### Deployment

- **Host**: the existing `claude-gateway` Lightsail nano (us-east-2) that runs claude_proxy, as a second
  container. Same pattern as `claude_proxy/deploy/lightsail`: host networking, bind to `127.0.0.1` on its own
  port, `mem_limit` ~128m (the gateway already takes 256m on a small box), its own named data volume, its own
  deploy/update/backup scripts. The gateway's files are not changed.
- **Domain**: `translate.rahkar.pro` (my pick of subdomain — easy to change), added as a published route on the
  existing `claude-gateway` Cloudflare tunnel (managed in the Cloudflare dashboard).
- **Clerk**: a **new, separate Clerk application** (production instance on `translate.rahkar.pro`); not shared
  with claude_proxy. Dev instance for local development.
- Env: `APP_URL`, `APP_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `ADMIN_EMAILS`.

## Calls made after the builder check (my calls — correct if wrong)

- Env gets `APP_URL` (the exact public origin); the Clerk verifier checks the token's `azp` against it.
- Until Turnstile keys are set the app starts **switched off** (admin can still sign in and configure).
- Signed-in users skip Turnstile (Clerk already proved they're human).
- A history item is saved after Generate and **updated in place** by each tweak (one item per conversation).
- OpenAI calls use `store=false`; neither provider should keep anonymous users' content longer than needed.
- "My language" list: a fixed list of ~30 common languages, default from browser locale.
- Spending cap: models with no price entered count as €0, and the admin page warns about them.
- Signed-in history is kept until the user deletes it.
- claude_proxy's Clerk Frontend API forwarder (`clerk_proxy.py`, for Iran) is not ported unless needed.

## Left to the builder

- Exact frame prompt wording and the seed style prompts.
- Which OpenAI API flavour and default model.
- Cookie/session details, CSP, page structure and styling (keep it clean, mobile-first).
- Whether to copy claude_proxy modules or reimplement the same small pieces.
- Tests: unit tests for the frame/adapters (with fake providers), API tests for access rules (no session →
  rejected, off switch, cap, admin-only), history ownership.

## Open

- App name (UI shows "Reply Translator" until decided).
