# Google Play: everything to paste into Play Console

Package: `pro.rahkar.translate` · Upload file: the `.aab` from the latest GitHub Actions run
(artifact **reply-translator-aab**) · Graphics: `icon-512.png`, `feature-1024x500.png` in this folder.

## Store listing

**App name** (30): Reply Translator

**Short description** (80):
Answer German letters and messages in perfect German, written from your words.

**Full description** (4000):
Got a letter from your landlord, a message from school, or a WhatsApp from a neighbour in German, and not sure how to answer?

Reply Translator writes the answer for you. Paste or share what they wrote, then say what you want to answer, in your own language, in a few words. You get a ready-to-send German reply, plus a translation back into your language so you know exactly what you are sending.

• Answer in your language: English, Arabic, Persian, Turkish, Ukrainian, Russian and many more
• Choose the tone: Official (authorities, landlords, schools, doctors), Friendly (chat messages) or Neutral
• Austrian German by default, with the right greetings and closings
• See what they wrote: a short summary of the received message in your language
• Adjust with one tap: shorter, more polite, more direct and more
• Share straight from WhatsApp, email or any app into Reply Translator, then copy or send the reply to WhatsApp
• History on your phone, or sign in with Google to keep it across devices

Free to use. No ads.

Privacy: https://translate.rahkar.pro/privacy

**App category:** Productivity · **Tags:** translation, communication
**Contact email:** mahmoud.shahrood@gmail.com · **Website:** https://translate.rahkar.pro
**Privacy policy URL:** https://translate.rahkar.pro/privacy

## App content (Policy → App content)

- **Privacy policy:** https://translate.rahkar.pro/privacy
- **Ads:** No, the app does not contain ads.
- **App access:** All functionality is available without special access (sign-in is optional; the bot check is a
  single tap).
- **Content rating questionnaire:** Category "Utility, productivity, communication or other". Answer **No** to
  violence, sexuality, language, controlled substances, gambling. User-generated content shared with other users: **No**
  (texts are private). Expected rating: Everyone / PEGI 3.
- **Target audience:** 18 and over (or 16+). Not designed for children.
- **News app:** No. **Government app:** No. **Financial features:** None. **Health:** None.
- **Account deletion:** in-app (account menu → Delete account) and web URL
  https://translate.rahkar.pro/delete-account

## Data safety form

Data is encrypted in transit: **Yes** (HTTPS only). Users can request deletion: **Yes** (link above).

| Data type | Collected | Shared | Optional | Purpose |
|---|---|---|---|---|
| Personal info → Email address | Yes (only when signed in) | No | Yes | Account management |
| Personal info → User IDs | Yes (only when signed in) | No | Yes | Account management |
| Messages → Other in-app messages (the texts you enter) | Yes | No* | No | App functionality |
| App activity → Other user-generated content (history) | Yes (only when signed in) | No | Yes | App functionality |

*Sending data to service providers that process it on our behalf (AI provider, Cloudflare, Clerk, AWS) is not
"sharing" under Play's definitions. Data is **not** processed ephemerally for signed-in history; texts of anonymous
users are processed only to answer (you may mark "Messages" as processed ephemerally only for not signed-in use, so
keep the conservative answer above).
IP addresses seen by Cloudflare/our server for the bot check and logs are not used to derive location, so no
"Location" entry is needed; if Play asks about fraud prevention, Turnstile is the bot check.

## After the first upload: Play App Signing (important)

Google re-signs the app with its own **app signing key**. Our key (`~/.config/reply-translator/release.jks`) becomes
the **upload key**. Google sign-in in the store version only works after adding Google's key too:

1. Play Console → Test and release → App integrity → App signing: copy the **SHA-1** and **SHA-256** of the *app
   signing key*.
2. Google Cloud project **cvlator** (dark-form-378317) → Clients → create another Android client
   `pro.rahkar.translate` with that SHA-1.
3. Clerk dashboard → Native applications → Android → add that SHA-256 to `pro.rahkar.translate`.

(Without this, store installs still sign in through the Chrome-tab fallback.)

## New personal developer accounts: testing requirement

Personal accounts created after Nov 2023 must run a **closed test with at least 12 testers for 14 days** before they
can apply for production. Plan: upload the AAB to a closed testing track, invite 12+ Google accounts (friends,
family), keep them opted in for 14 days, then apply for production access.

## Still needed

- Phone screenshots (2–8, 9:16, e.g. 1080×1920): the main form, a reply with "They wrote" summary, the tweak buttons,
  history.
