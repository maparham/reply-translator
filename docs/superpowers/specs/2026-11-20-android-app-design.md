# Reply Translator — native Android app

## Intent
Android users get the Reply Translator as a real app, not just translate.rahkar.pro. Most of the messages it
answers arrive in WhatsApp or email on the phone, so the app should take them in through the share sheet.

## Goals
- Same main screen as the website: "what they wrote", "what you want to say", style / language / my-language
  pickers, "don't save this one", Generate, result with Copy / WhatsApp / "Means" and the tweak buttons, history.
- Anonymous use, protected by Turnstile like the website (user's choice: option 2 of 3).
- Optional Google sign-in via Clerk; signed in, history syncs with the account and phone-only history can be
  moved to the account ("Move N items to your account?").
- Share into the app: text shared from any app fills "what they wrote".

## Non-goals
- Admin settings (stay on the website).
- Play Store listing (later; doesn't change the code). Distribution is a signed APK.
- iOS.
- Offline use.

## Approaches considered
1. **Native Kotlin + Jetpack Compose calling the existing `/api/...` endpoints** — chosen (user asked for native).
2. Web wrapper (WebView / TWA) — rejected by the user in favour of native.
3. Flutter / React Native — no benefit for an Android-only app; not installed here.

Anonymous protection: (1) sign-in required, (2) Turnstile in a small web view, (3) Play Integrity (Play Store
only). **User picked (2).**

## Design
- **Project:** `android/` in this repo, package `pro.rahkar.translate`, Kotlin, Compose, Material 3, single
  activity, OkHttp + kotlinx.serialization, minSdk 26. `android/` is excluded from the server rsync.
- **API client:** every request goes to `https://translate.rahkar.pro`, sends `Origin: https://translate.rahkar.pro`
  (the server rejects non-GET `/api/` calls without it) and keeps the `tr_session` cookie in a persisted cookie
  jar. Same request/response shapes as `static/app.js`.
- **Anonymous session:** a new server page `GET /app-check` (static HTML + JS, same CSP as the site) renders the
  Turnstile widget with the configured site key and hands the token to the app through a JavaScript bridge.
  The app posts it to `/api/session` itself. Because the widget runs on translate.rahkar.pro the server's
  hostname check holds unchanged. The web view is shown only when Turnstile needs a click ("interaction-only");
  otherwise it runs invisibly. On a 401 the app gets a fresh token and retries once, like the website.
- **Sign-in:** Clerk Android SDK, Google. The app sends the Clerk session token to `/api/login/clerk`. The
  server's token check today requires `azp == https://translate.rahkar.pro`; tokens from the native SDK may carry
  no `azp`, so the check also accepts tokens without one (signature, issuer, expiry, session and user checks are
  unchanged; a token with a *different* `azp` is still rejected).
- **History:** anonymous items in app storage (JSON file, newest 100, same item shape as the website's
  `rt.history`); signed in, `/api/history`. On sign-in with local items, offer to import (batched like the
  website).
- **Prefs:** last style, language and my-language remembered; my-language defaults from the phone's locale
  using the website's mapping.
- **Share:** `ACTION_SEND` `text/plain` intent filter; shared text goes into "what they wrote".
- **WhatsApp button:** opens `https://wa.me/?text=…` (or the system share sheet if WhatsApp isn't installed).
- **Errors:** server error messages shown as on the website; "Temporarily unavailable" banner when `open` is false.

## Setup outside the code
- Clerk dashboard: enable native API, register the Android app (package + signing certificate fingerprint).
- Google Cloud (project with the existing "CV Lator Clerk Google Login" client): whatever Android OAuth client
  Clerk's native Google sign-in requires.
- A release signing key kept outside the repo.

## Left to the builder
Screen layout details within the website's structure, icon, colours, loading states.
