# Android app Implementation Plan

**Goal:** Native Android client for translate.rahkar.pro (see spec).
**Spec:** docs/superpowers/specs/2026-11-20-android-app-design.md
**Tech:** Kotlin 2.4.21, AGP 9.5.1 (built-in Kotlin), Gradle 9.9.1, Compose BOM 2026.06.01, Material 3,
OkHttp 5.4.0, kotlinx.serialization, Clerk `com.clerk:clerk-android-api:1.4.1`. minSdk 26, target/compile 36.
Execution: native (user said "go").

## Global constraints
- Base URL `https://translate.rahkar.pro`; every request sends `Origin: https://translate.rahkar.pro`.
- Request/response shapes exactly as `src/translator/static/app.js` / `app.py` (GenerateIn, TweakIn, history items).
- Anonymous: Turnstile token from `/app-check` web view → `POST /api/session`; on 401 re-check once.
- Local history: newest 100, website item shape; import in batches ≤ 200 000 bytes of JSON.
- Package `pro.rahkar.translate`. Release keystore outside the repo.

## Tasks
1. Backend: `/app-check` page + JS bridge script; Clerk verifier accepts tokens without `azp` only when
   lifetime ≤ 120 s; `android/` excluded from deploy rsync. (done, tests in test_access/test_clerk)
2. Gradle project scaffold under `android/`, builds an empty Compose activity.
3. API client (`Api.kt`, `Models.kt`, persistent cookie jar) + unit tests with MockWebServer.
4. Local storage (`LocalStore.kt`: prefs, local history, import batching, locale → my-language) + unit tests.
5. Turnstile gate (web view + bridge) and session handling (401 → check → retry once).
6. Main screen UI + ViewModel (generate, tweaks, copy, WhatsApp, history, notices, share intent).
7. Clerk Google sign-in, token exchange, sign-out, import offer.
8. Dashboard setup: release keystore, Google Android OAuth client (SHA-1), Clerk native API + Android app
   (SHA-256). Build signed release APK, install on the attached phone, verify end to end.
9. Deploy backend, commit, push.
