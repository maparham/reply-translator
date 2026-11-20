"use strict";
const $ = (s) => document.querySelector(s);
const S = { cfg: null, user: null, sessionOk: false, widget: null, waiters: [], busy: false,
  last: null, histId: null, fails: 0, clerk: null, exchanging: false };

// ---------- storage ----------
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
};
const MAX_LOCAL = 100;
const validItem = (i) => i && typeof i === "object" && typeof i.id === "string" && i.inputs && typeof i.inputs === "object"
  && i.output && typeof i.output.message === "string" && typeof i.output.back_translation === "string";
function localHistory() { const h = store.get("rt.history", []); return Array.isArray(h) ? h.filter(validItem) : []; }

// ---------- api ----------
// Turnstile tokens are single use: a 401 means the session is gone, so get a fresh token and retry once.
async function api(method, path, body) {
  if (!S.user && !S.sessionOk) await waitForSession();
  try { return await rawApi(method, path, body); }
  catch (e) {
    if (e.status !== 401) throw e;
    if (S.user) { await refreshConfig(); throw e; }
    S.sessionOk = false;
    resetTurnstile();
    await waitForSession();
    return rawApi(method, path, body);
  }
}

// ---------- Turnstile ----------
function waitForSession() {
  if (S.sessionOk || S.user) return Promise.resolve();
  if (S.fails >= 2) return Promise.reject(new Error("Couldn't verify, reload the page"));
  if (S.fails > 0) resetTurnstile();
  return new Promise((resolve, reject) => {
    S.waiters.push({ resolve, reject });
    setTimeout(() => {
      const i = S.waiters.findIndex((w) => w.resolve === resolve);
      if (i >= 0) { S.waiters.splice(i, 1); reject(new Error("Verification is taking too long, reload the page")); }
    }, 30000);
  });
}
function resetTurnstile() { if (S.widget !== null && window.turnstile) window.turnstile.reset(S.widget); }
async function onTurnstileToken(token) {
  if (S.user) return; // signed in meanwhile: the user session already covers this
  try {
    await rawApi("POST", "/api/session", { turnstile_token: token });
    S.sessionOk = true;
    S.fails = 0;
    S.waiters.splice(0).forEach((w) => w.resolve());
  } catch (e) {
    S.fails += 1;
    const waiting = S.waiters.length > 0;
    if (S.fails >= 2) {
      S.waiters.splice(0).forEach((w) => w.reject(new Error("Couldn't verify, reload the page")));
      showError("Couldn't verify, reload the page");
    } else if (waiting) resetTurnstile(); // a request is waiting: try once more
  }
}
let turnstileLoading = null;
async function setupTurnstile() {
  if (S.user || S.widget !== null || !S.cfg.turnstile_site_key) return;
  try {
    turnstileLoading ??= loadScript("https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit");
    await turnstileLoading;
    S.widget = window.turnstile.render("#turnstile", {
      sitekey: S.cfg.turnstile_site_key, appearance: "interaction-only", callback: onTurnstileToken,
    });
  } catch (e) { showError("Could not load the verification check, reload the page."); }
}

// ---------- Clerk ----------
async function setupClerk() {
  S.clerk = await loadClerk(S.cfg.clerk_publishable_key, (clerk) => { S.clerk = clerk; if (!S.user) clerkExchange(); });
}
async function clerkExchange() {
  if (S.exchanging) return;
  S.exchanging = true;
  try {
    S.user = await clerkExchangeToken(S.clerk);
    S.cfg.user = S.user;
    renderAccount();
    offerImport();
    await renderHistory();
  } catch (e) { showError(e.message); }
  finally { S.exchanging = false; }
}
function offerImport() {
  const n = S.user ? localHistory().length : 0;
  if (!n) return;
  $("#import-text").textContent = `Move ${n} item${n === 1 ? "" : "s"} from this browser to your account?`;
  $("#import-bar").hidden = false;
}
const signOut = () => signOutAndReload(S.clerk);

// ---------- form ----------
const LOCALE = { en: "English", ar: "Arabic", fa: "Persian", ps: "Pashto", tr: "Turkish", ku: "Kurdish (Kurmanji)",
  uk: "Ukrainian", ru: "Russian", bs: "Bosnian/Croatian/Serbian", hr: "Bosnian/Croatian/Serbian",
  sr: "Bosnian/Croatian/Serbian", sq: "Albanian", ro: "Romanian", bg: "Bulgarian", pl: "Polish", cs: "Czech",
  sk: "Slovak", hu: "Hungarian", el: "Greek", es: "Spanish", fr: "French", it: "Italian", pt: "Portuguese",
  hi: "Hindi", ur: "Urdu", bn: "Bengali", zh: "Chinese", vi: "Vietnamese", tl: "Tagalog", fil: "Tagalog",
  so: "Somali", ti: "Tigrinya" };

function fill(select, options, value) {
  select.replaceChildren(...options.map(([v, label]) => { const o = document.createElement("option"); o.value = v; o.textContent = label; return o; }));
  if ([...select.options].some((o) => o.value === String(value))) select.value = String(value);
}
function buildForm() {
  const prefs = store.get("rt.prefs", {});
  const c = S.cfg;
  fill($("#style"), c.styles.map((s) => [s.id, s.label]), prefs.style);
  fill($("#lang"), c.languages.map((l) => [l.code, l.name]), prefs.lang);
  const guess = LOCALE[(navigator.language || "en").toLowerCase().split("-")[0]] || "English";
  fill($("#mylang"), c.my_languages.map((n) => [n, n]), prefs.my || guess);
  showStyleDesc();
  const tw = $("#tweaks");
  tw.replaceChildren(...c.tweaks.map((t) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = t.label; b.dataset.tweak = t.id;
    b.addEventListener("click", () => run(t.id, b));
    return b;
  }));
  const usable = c.open && c.styles.length && c.languages.length;
  $("#generate").disabled = !usable;
  if (!c.open) showNotice("Temporarily unavailable. Please try again later.");
}
function showStyleDesc() {
  const s = S.cfg.styles.find((x) => String(x.id) === $("#style").value);
  $("#style-desc").textContent = s?.description || "";
  $("#style-desc").hidden = !s?.description;
}
function savePrefs() {
  store.set("rt.prefs", { style: $("#style").value, lang: $("#lang").value, my: $("#mylang").value });
}
function showError(msg) { const e = $("#error"); e.textContent = msg; e.hidden = !msg; }
function showNotice(msg) { const e = $("#notice"); e.textContent = msg; e.hidden = !msg; }
function setBusy(on, button) {
  S.busy = on;
  const all = [$("#generate"), ...document.querySelectorAll("#tweaks button"), $("#copy")];
  all.forEach((b) => { b.disabled = on || (b.id === "generate" && !(S.cfg.open && S.cfg.styles.length)); b.classList.remove("busy"); });
  if (on && button) button.classList.add("busy");
}

// ---------- generate / tweak ----------
function snapshot() {
  return { style_id: Number($("#style").value), language_code: $("#lang").value, my_language: $("#mylang").value,
    text: $("#text").value, received: $("#received").value };
}
async function run(tweak, button) {
  if (S.busy || !S.cfg) return;
  showError("");
  const inputs = tweak && S.last ? S.last.inputs : snapshot();
  if (!tweak) savePrefs();
  const save = !$("#nosave").checked;
  const body = { ...inputs, save, history_id: tweak ? S.histId : null };
  if (tweak) { body.tweak = tweak; body.previous = S.last.result; }
  setBusy(true, button);
  try {
    const res = await api("POST", tweak ? "/api/tweak" : "/api/generate", body);
    if (!tweak) S.histId = null;
    S.last = { inputs, result: res.result, styleLabel: styleLabel(inputs.style_id) };
    showResult(res.result);
    if (save) {
      if (S.user) S.histId = res.history_id;
      else S.histId = saveLocal(S.histId, S.last);
      await renderHistory();
    }
  } catch (e) { showError(e.message); }
  finally { setBusy(false); }
}
function styleLabel(id) { return S.cfg.styles.find((s) => s.id === id)?.label || "Style"; }
function showResult(r) {
  const gist = $("#gist");
  gist.hidden = !r.received_gist;
  gist.replaceChildren();
  if (r.received_gist) { const b = document.createElement("b"); b.textContent = "They wrote: "; gist.append(b, r.received_gist); }
  $("#message").textContent = r.message;
  $("#message").lang = ($("#lang").value || "de").split("-")[0];
  $("#back").textContent = `“${r.back_translation}”`;
  $("#whatsapp").href = "https://wa.me/?text=" + encodeURIComponent(r.message);
  $("#copy").textContent = "Copy";
  const box = $("#result");
  const wasHidden = box.hidden;
  box.hidden = false;
  if (wasHidden || !isVisible($("#message"))) $("#message").scrollIntoView({ block: "center", behavior: "smooth" });
}
function isVisible(el) { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }
async function copyText(text, button) {
  let ok = true;
  try { await navigator.clipboard.writeText(text); }
  catch {
    const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select();
    try { ok = document.execCommand("copy"); } catch { ok = false; } finally { t.remove(); }
  }
  const old = button.dataset.label || button.textContent;
  button.dataset.label = old;
  button.textContent = ok ? "Copied ✓" : "Couldn't copy, select the text";
  setTimeout(() => { button.textContent = old; }, 1800);
}

// ---------- history ----------
function saveLocal(id, last) {
  const items = localHistory();
  const now = new Date().toISOString();
  const existing = id ? items.find((i) => i.id === id) : null;
  const item = {
    id: existing?.id || crypto.randomUUID(), created_at: existing?.created_at || now, updated_at: now,
    style_label: last.styleLabel, language_code: last.inputs.language_code,
    inputs: { text: last.inputs.text, received: last.inputs.received, my_language: last.inputs.my_language },
    output: last.result,
  };
  store.set("rt.history", [item, ...items.filter((i) => i.id !== item.id)].slice(0, MAX_LOCAL));
  return item.id;
}
async function historyItems() {
  if (!S.user) return localHistory();
  try { return await api("GET", "/api/history"); } catch (e) { showError(e.message); return []; }
}
async function renderHistory() {
  try { await renderHistoryUnsafe(); }
  catch (e) { console.warn("history failed", e); }
}
async function renderHistoryUnsafe() {
  const items = (await historyItems()).filter(validItem);
  $("#history-count").textContent = items.length ? `(${items.length})` : "";
  $("#history-empty").hidden = items.length > 0;
  $("#history-anon").hidden = !!S.user;
  $("#history-clear").hidden = items.length === 0;
  $("#history-list").replaceChildren(...items.map(historyRow));
}
function historyRow(item) {
  const li = document.createElement("li"); li.className = "hitem";
  const open = document.createElement("button"); open.type = "button"; open.className = "hopen";
  const meta = document.createElement("span"); meta.className = "meta";
  const lang = S.cfg.languages.find((l) => l.code === item.language_code)?.name || item.language_code;
  meta.textContent = `${item.style_label} · ${lang} · ${new Date(item.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`;
  const snip = document.createElement("span"); snip.className = "snip"; snip.textContent = item.output.message.replace(/\s+/g, " ");
  open.append(meta, snip);
  open.addEventListener("click", () => loadItem(item));
  const btns = document.createElement("div"); btns.className = "hbtns";
  const copy = document.createElement("button"); copy.type = "button"; copy.className = "link"; copy.textContent = "Copy";
  copy.addEventListener("click", () => copyText(item.output.message, copy));
  const del = document.createElement("button"); del.type = "button"; del.className = "link danger"; del.textContent = "Delete";
  del.addEventListener("click", () => deleteItem(item.id));
  btns.append(copy, del);
  li.append(open, btns);
  return li;
}
function loadItem(item) {
  $("#received").value = item.inputs.received || "";
  $("#text").value = item.inputs.text || "";
  const style = S.cfg.styles.find((s) => s.label === item.style_label);
  if (style) $("#style").value = String(style.id);
  if ([...$("#lang").options].some((o) => o.value === item.language_code)) $("#lang").value = item.language_code;
  if ([...$("#mylang").options].some((o) => o.value === item.inputs.my_language)) $("#mylang").value = item.inputs.my_language;
  showStyleDesc();
  S.histId = item.id;
  S.last = { inputs: snapshot(), result: item.output, styleLabel: item.style_label };
  showError("");
  showResult(item.output);
}
async function deleteItem(id) {
  if (S.user) { try { await api("DELETE", `/api/history/${encodeURIComponent(id)}`); } catch (e) { showError(e.message); } }
  else store.set("rt.history", localHistory().filter((i) => i.id !== id));
  if (S.histId === id) S.histId = null;
  await renderHistory();
}
async function deleteAll() {
  if (!confirm("Delete all history?")) return;
  if (S.user) { try { await api("DELETE", "/api/history"); } catch (e) { showError(e.message); } }
  else store.del("rt.history");
  S.histId = null;
  await renderHistory();
}
const IMPORT_BATCH_BYTES = 200000; // headroom under the server's 256 KB body cap; a lone max-size item (~96 KB) fits
const jsonBytes = (items) => new TextEncoder().encode(JSON.stringify({ items })).length;
async function importLocal() {
  const items = localHistory();
  const batches = [];
  let batch = [];
  for (const item of items) {
    if (batch.length && jsonBytes([...batch, item]) > IMPORT_BATCH_BYTES) { batches.push(batch); batch = []; }
    batch.push(item);
  }
  if (batch.length) batches.push(batch);
  try {
    let imported = 0;
    for (const b of batches) {
      const r = await rawApi("POST", "/api/history/import", { items: b });
      imported += r.imported || 0;
    }
    store.del("rt.history");
    $("#import-bar").hidden = true;
    await renderHistory();
  } catch (e) { showError(e.message); }
}

// ---------- account ----------
function renderAccount() {
  $("#who").hidden = !S.user; $("#who").textContent = S.user?.email || "";
  $("#signout").hidden = !S.user;
  $("#signin").hidden = !!S.user || !S.cfg.clerk_publishable_key;
  $("#turnstile").hidden = !!S.user;
}
async function refreshConfig() {
  S.cfg = await rawApi("GET", "/api/config");
  S.user = S.cfg.user;
  renderAccount();
  if (!S.user) { S.sessionOk = false; setupTurnstile(); resetTurnstile(); }
}

// ---------- init ----------
async function init() {
  $("#form").addEventListener("submit", (e) => { e.preventDefault(); run(null, $("#generate")); });
  try { S.cfg = await rawApi("GET", "/api/config"); }
  catch (e) { showNotice("Could not load the app. Please reload."); return; }
  S.user = S.cfg.user;
  buildForm();
  renderAccount();
  offerImport();
  $("#style").addEventListener("change", () => { showStyleDesc(); savePrefs(); });
  $("#lang").addEventListener("change", savePrefs);
  $("#mylang").addEventListener("change", savePrefs);
  $("#copy").addEventListener("click", () => copyText(S.last.result.message, $("#copy")));
  $("#signin").addEventListener("click", () => { if (S.clerk) S.clerk.openSignIn(); else showError("Sign-in is still loading, try again in a moment."); });
  $("#signout").addEventListener("click", signOut);
  $("#import-yes").addEventListener("click", importLocal);
  $("#import-no").addEventListener("click", () => { $("#import-bar").hidden = true; });
  $("#history-clear").addEventListener("click", deleteAll);
  $("#history-toggle").addEventListener("click", () => {
    const panel = $("#history-panel");
    panel.hidden = !panel.hidden;
    $("#history-toggle").setAttribute("aria-expanded", String(!panel.hidden));
    $("#history-caret").textContent = panel.hidden ? "▸" : "▾";
  });
  setupTurnstile();
  setupClerk();
  renderHistory();
}
init();
