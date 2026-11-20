"use strict";
// Runs inside the Android app's web view: gets a Turnstile token on this domain (so the server's hostname check
// holds) and hands it to the app, which exchanges it at /api/session. Window.ReplyApp is the app's JS bridge.
const bridge = window.ReplyApp;
const report = (kind, value) => { if (bridge) bridge[kind](value); };
function fail(msg) {
  const e = document.getElementById("error"); e.textContent = msg; e.hidden = false;
  report("onError", msg);
}
(async () => {
  let cfg;
  try { cfg = await rawApi("GET", "/api/config"); }
  catch { fail("Could not load the check, try again"); return; }
  if (!cfg.turnstile_site_key) { fail("Temporarily unavailable"); return; }
  try { await loadScript("https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"); }
  catch { fail("Could not load the check, try again"); return; }
  window.turnstile.render("#turnstile", {
    sitekey: cfg.turnstile_site_key, appearance: "interaction-only",
    callback: (token) => report("onToken", token),
    "before-interactive-callback": () => report("onInteractive", ""),
    "error-callback": () => fail("The check failed, try again"),
  });
})();
