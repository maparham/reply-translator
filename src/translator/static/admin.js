"use strict";
const $ = (s) => document.querySelector(s);
const S = { cfg: null, user: null, clerk: null, exchanging: false, settings: null, styles: [], langs: [], editing: undefined };
const CLOSED = {
  switched_off: "Closed: the app is switched off.",
  turnstile_missing: "Closed: the Turnstile keys are missing (set the site key and secret).",
  cap_reached: "Closed: today's spending cap has been reached.",
};
const SECRET_LABELS = { openai_api_key: "OpenAI API key", anthropic_api_key: "Anthropic API key", turnstile_secret: "Turnstile secret" };
const PROVIDERS = ["anthropic", "openai"];

// ---------- helpers ----------
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
    else if (k === "on") Object.entries(v).forEach(([ev, fn]) => e.addEventListener(ev, fn));
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  e.append(...kids.filter((x) => x !== null && x !== undefined));
  return e;
}
const button = (text, onclick, cls = "link", extra = {}) => el("button", { type: "button", class: cls, text, on: { click: onclick }, ...extra });
const field = (label, input) => el("div", { class: "field" }, el("label", { for: input.id, text: label }), input);
let flashTimer;
function showError(msg) { const e = $("#error"); e.textContent = msg; e.hidden = !msg; if (msg) e.scrollIntoView({ block: "nearest" }); }
function flash(msg) {
  const e = $("#flash"); e.textContent = msg; e.hidden = false;
  clearTimeout(flashTimer); flashTimer = setTimeout(() => { e.hidden = true; }, 2500);
}
// Run an action, showing any error; returns undefined on failure.
async function guard(fn, okMsg) {
  showError("");
  try { const r = await fn(); if (okMsg) flash(okMsg); return r ?? true; }
  catch (e) { if (e.status === 403) { showGate("Admins only"); } else showError(e.message); }
}
function showGate(msg, withSignIn) {
  $("#panels").hidden = true; $("#gate").textContent = msg; $("#gate").hidden = false;
  $("#signin").hidden = !withSignIn;
}

// ---------- Clerk ----------
async function setupClerk() {
  S.clerk = await loadClerk(S.cfg.clerk_publishable_key, (clerk) => { S.clerk = clerk; if (!S.user) clerkExchange(); });
}
async function clerkExchange() {
  if (S.exchanging) return;
  S.exchanging = true;
  try { await clerkExchangeToken(S.clerk); await start(); }
  catch (e) { showError(e.message); }
  finally { S.exchanging = false; }
}
const signOut = () => signOutAndReload(S.clerk);

// ---------- status + keys ----------
function renderStatus() {
  const s = S.settings;
  $("#enabled").checked = s.enabled;
  const st = $("#open-state");
  st.textContent = s.open ? "Open: visitors can generate replies." : (CLOSED[s.closed_reason] || "Closed.");
  st.className = s.open ? "notice ok" : "notice";
}
function renderKeys() {
  $("#keys").replaceChildren(...Object.entries(SECRET_LABELS).map(([name, label]) => {
    const hint = S.settings.secrets[name];
    const input = el("input", { type: "password", id: `key-${name}`, autocomplete: "new-password", spellcheck: "false",
      placeholder: hint ? `set ${hint}` : "not set", "data-key": name });
    const clear = button("Clear", () => clearKey(name, label), "link danger", { disabled: !hint });
    return el("div", { class: "field" }, el("label", { for: input.id, text: label }), el("div", { class: "keyrow" }, input, clear));
  }));
  $("#site-key").value = S.settings.turnstile_site_key || "";
}
function applySettings(s) { S.settings = s; renderStatus(); renderKeys(); renderSpending(); }
async function clearKey(name, label) {
  if (!confirm(`Clear the ${label}?`)) return;
  const s = await guard(() => rawApi("PUT", "/api/admin/settings", { [name]: "" }), `${label} cleared`);
  if (s && s !== true) applySettings(s);
}
async function saveKeys(e) {
  e.preventDefault();
  const body = {};
  document.querySelectorAll("#keys input[data-key]").forEach((i) => { if (i.value.trim()) body[i.dataset.key] = i.value.trim(); });
  const site = $("#site-key").value.trim();
  if (site !== (S.settings.turnstile_site_key || "")) body.turnstile_site_key = site;
  if (!Object.keys(body).length) { flash("Nothing to save"); return; }
  const s = await guard(() => rawApi("PUT", "/api/admin/settings", body), "Keys saved");
  if (s && s !== true) applySettings(s);
}
async function toggleEnabled() {
  const on = $("#enabled").checked;
  const s = await guard(() => rawApi("PUT", "/api/admin/settings", { enabled: on }), on ? "Switched on" : "Switched off");
  if (s && s !== true) applySettings(s); else $("#enabled").checked = S.settings.enabled;
}

// ---------- styles ----------
const modelCache = {};
async function modelsFor(provider) {
  if (!(provider in modelCache)) {
    try { modelCache[provider] = (await rawApi("GET", `/api/admin/models?provider=${encodeURIComponent(provider)}`)).models; }
    catch { return []; } // don't cache failures: the key may be set later
  }
  return modelCache[provider];
}
async function loadStyles() {
  const r = await guard(() => rawApi("GET", "/api/admin/styles"));
  if (r && r !== true) { S.styles = r; renderStyles(); }
}
function renderStyles() {
  $("#styles").replaceChildren(...S.styles.map((s, i) => {
    const meta = `${s.provider} · ${s.model}${s.active ? "" : " · inactive"}`;
    return el("li", { class: "sitem" + (s.active ? "" : " off") },
      el("span", { class: "stitle", text: s.label }), el("span", { class: "smeta", text: meta }),
      el("div", { class: "sbtns" },
        button("Up", () => move(i, -1), "link", { disabled: i === 0, "aria-label": `Move ${s.label} up` }),
        button("Down", () => move(i, 1), "link", { disabled: i === S.styles.length - 1, "aria-label": `Move ${s.label} down` }),
        el("label", { class: "check small" }, el("input", { type: "checkbox", checked: s.active, on: { change: (e) => setActive(s, e.target.checked, e.target) } }), "Active"),
        button("Edit", () => openEditor(s)),
        button("Delete", () => deleteStyle(s), "link danger")));
  }));
}
async function move(i, d) {
  const ids = S.styles.map((s) => s.id);
  [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
  const r = await guard(() => rawApi("PUT", "/api/admin/styles/order", { ids }));
  if (r) { S.styles = r; renderStyles(); }
}
async function setActive(s, active, box) {
  const r = await guard(() => rawApi("PUT", `/api/admin/styles/${s.id}`, { active }), active ? "Activated" : "Deactivated");
  if (r && r !== true) { Object.assign(s, r); renderStyles(); if (S.editing === s.id) { const e = $("#e-active"); if (e) e.checked = r.active; } } else box.checked = s.active;
}
async function deleteStyle(s) {
  if (!confirm(`Delete the style "${s.label}"? Old history items keep their label.`)) return;
  if (await guard(() => rawApi("DELETE", `/api/admin/styles/${s.id}`), "Style deleted")) {
    if (S.editing === s.id) closeEditor();
    await loadStyles();
  }
}
function closeEditor() { S.editing = undefined; $("#editor").hidden = true; $("#editor").replaceChildren(); }
async function openEditor(style) {
  const isNew = !style;
  const s = style || { id: null, label: "", description: "", prompt: "", provider: "anthropic", model: "", active: true };
  S.editing = s.id;
  const label = el("input", { type: "text", id: "e-label", value: s.label, maxlength: "60" });
  const desc = el("input", { type: "text", id: "e-desc", value: s.description || "" });
  const prompt = el("textarea", { id: "e-prompt", class: "prompt", rows: "10", spellcheck: "false" }); prompt.value = s.prompt;
  const provider = el("select", { id: "e-provider" }, ...PROVIDERS.map((p) => el("option", { value: p, text: p }))); provider.value = s.provider;
  const model = el("input", { type: "text", id: "e-model", value: s.model, list: "e-models", autocomplete: "off", spellcheck: "false" });
  const models = el("datalist", { id: "e-models" });
  const active = el("input", { type: "checkbox", id: "e-active", checked: s.active });
  const fillModels = async () => { const m = await modelsFor(provider.value); models.replaceChildren(...m.map((x) => el("option", { value: x }))); };
  provider.addEventListener("change", fillModels);
  fillModels();

  const save = async () => {
    const body = { label: label.value, description: desc.value, prompt: prompt.value, provider: provider.value, model: model.value.trim(), active: active.checked };
    const r = await guard(() => isNew ? rawApi("POST", "/api/admin/styles", body) : rawApi("PUT", `/api/admin/styles/${s.id}`, body), "Style saved");
    if (r && r !== true) { await loadStyles(); const fresh = S.styles.find((x) => x.id === r.id); if (fresh) openEditor(fresh); }
  };
  $("#editor").replaceChildren(
    el("h3", { text: isNew ? "New style" : `Edit: ${s.label}` }),
    field("Label", label), field("Description (shown to users)", desc), field("Prompt", prompt),
    el("div", { class: "grid2" }, field("Provider", provider), field("Model", model)), models,
    el("label", { class: "check" }, active, "Active"),
    el("div", { class: "bar" }, button("Save style", save, "primary"), button("Close", closeEditor, "btn")),
    tryBox(prompt, provider, model));
  $("#editor").hidden = false;
  $("#editor").scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function tryBox(prompt, provider, model) {
  const text = el("textarea", { id: "t-text", rows: "3", placeholder: "What you want to say" });
  const received = el("textarea", { id: "t-received", rows: "3", placeholder: "Message received (optional)" });
  const lang = el("select", { id: "t-lang" }, ...S.langs.map((l) => el("option", { value: l.code, text: l.name })));
  const mine = el("select", { id: "t-mine" }, ...S.cfg.my_languages.map((n) => el("option", { value: n, text: n })));
  mine.value = "English";
  const out = el("div", { hidden: true });
  const run = el("button", { type: "button", class: "primary small", text: "Try it" });
  run.addEventListener("click", async () => {
    run.disabled = true; run.textContent = "Trying…";
    const body = { prompt: prompt.value, provider: provider.value, model: model.value.trim(), language_code: lang.value,
      my_language: mine.value, text: text.value, received: received.value.trim() ? received.value : null };
    const r = await guard(() => rawApi("POST", "/api/admin/try", body));
    run.disabled = false; run.textContent = "Try it";
    if (!r || r === true) { out.hidden = true; return; }
    const res = r.result;
    out.replaceChildren(
      res.received_gist ? el("p", { class: "gist" }, el("b", { text: "They wrote: " }), res.received_gist) : null,
      el("div", { class: "message", text: res.message }),
      el("p", { class: "means" }, el("span", { class: "means-label", text: "Means" }), `“${res.back_translation}”`));
    out.hidden = false;
    loadUsage();
  });
  return el("div", { class: "try" }, el("h3", { text: "Try it (uses the prompt above, unsaved changes included)" }),
    field("Text", text), field("Received", received),
    el("div", { class: "grid2" }, field("To", lang), field("My language", mine)),
    el("div", { class: "bar" }, run), out);
}

// ---------- languages ----------
async function loadLangs() { S.langs = (await rawApi("GET", "/api/admin/languages")).items; renderLangs(); }
function renderLangs() {
  $("#langs").replaceChildren(...S.langs.map((l) => langRow(l.code, l.name)));
}
function langRow(code, name) {
  const row = el("div", { class: "lrow" },
    el("input", { type: "text", "aria-label": "Code", placeholder: "code", value: code, "data-f": "code", spellcheck: "false" }),
    el("input", { type: "text", "aria-label": "Name", placeholder: "name", value: name, "data-f": "name" }),
    button("Remove", () => row.remove(), "link danger"));
  return row;
}
async function saveLangs() {
  const items = [...document.querySelectorAll("#langs .lrow")].map((r) => ({
    code: r.querySelector('[data-f="code"]').value.trim(), name: r.querySelector('[data-f="name"]').value.trim() }));
  const r = await guard(() => rawApi("PUT", "/api/admin/languages", { items }), "Languages saved");
  if (r && r !== true) { S.langs = r.items; renderLangs(); }
}

// ---------- spending ----------
function priceRow(model, p) {
  const row = el("div", { class: "prow" },
    el("input", { type: "text", "aria-label": "Model", placeholder: "model", value: model, "data-f": "model", list: "price-models", spellcheck: "false" }),
    el("input", { type: "number", "aria-label": "Input price per 1M tokens", placeholder: "in", min: "0", step: "any", value: p.in ?? "", "data-f": "in" }),
    el("input", { type: "number", "aria-label": "Output price per 1M tokens", placeholder: "out", min: "0", step: "any", value: p.out ?? "", "data-f": "out" }),
    button("Remove", () => row.remove(), "link danger"));
  return row;
}
function renderSpending() {
  $("#cap").value = S.settings.cap_eur ?? "";
  const known = [...new Set(S.styles.map((s) => s.model))];
  $("#prices").replaceChildren(
    el("datalist", { id: "price-models" }, ...known.map((m) => el("option", { value: m }))),
    ...Object.entries(S.settings.prices).map(([m, p]) => priceRow(m, p)));
}
async function saveSpending() {
  const capRaw = $("#cap").value.trim();
  const prices = {};
  for (const r of document.querySelectorAll("#prices .prow")) {
    const model = r.querySelector('[data-f="model"]').value.trim();
    const pin = r.querySelector('[data-f="in"]').value, pout = r.querySelector('[data-f="out"]').value;
    if (!model && pin === "" && pout === "") continue;
    if (!model || pin === "" || pout === "") { showError("Each price row needs a model, an input price and an output price."); return; }
    prices[model] = { in: Number(pin), out: Number(pout) };
  }
  const s = await guard(() => rawApi("PUT", "/api/admin/settings", { cap_eur: capRaw === "" ? null : Number(capRaw), prices }), "Spending saved");
  if (s && s !== true) { applySettings(s); loadUsage(); }
}
const eur = (n) => `€${Number(n || 0).toFixed(4)}`;
function table(el_, head, rows) {
  const t = el_;
  t.replaceChildren(el("thead", {}, el("tr", {}, ...head.map((h) => el("th", { text: h })))),
    el("tbody", {}, ...rows.map((r) => el("tr", {}, ...r.map((c) => el("td", { text: String(c) }))))));
  if (!rows.length) t.querySelector("tbody").append(el("tr", {}, el("td", { text: "No usage yet", colspan: String(head.length) })));
}
async function loadUsage() {
  const u = await guard(() => rawApi("GET", "/api/admin/usage"));
  if (!u || u === true) return;
  $("#today").textContent = `Spent today: ${eur(u.spent_today)}`;
  table($("#usage-days"), ["Day", "Requests", "Cost"], u.days.map((d) => [d.day, d.requests, eur(d.cost_eur)]));
  table($("#usage-styles"), ["Style", "Requests", "Cost"], u.by_style.map((d) => [d.label, d.requests, eur(d.cost_eur)]));
  const w = $("#unpriced");
  w.hidden = !u.unpriced_models.length;
  w.textContent = u.unpriced_models.length
    ? `No price set for: ${u.unpriced_models.join(", ")}. These count as €0 towards the cap.` : "";
}

// ---------- init ----------
async function start() {
  S.cfg = await rawApi("GET", "/api/config");
  S.user = S.cfg.user;
  $("#who").hidden = !S.user; $("#who").textContent = S.user?.email || "";
  $("#signout").hidden = !S.user;
  if (!S.user) { showGate("Sign in to continue.", !!S.cfg.clerk_publishable_key); return; }
  if (!S.user.is_admin) { showGate("Admins only"); return; }
  $("#gate").hidden = true; $("#signin").hidden = true;
  try {
    S.settings = await rawApi("GET", "/api/admin/settings");
    S.styles = await rawApi("GET", "/api/admin/styles");
    S.langs = (await rawApi("GET", "/api/admin/languages")).items;
  } catch (e) { if (e.status === 403) showGate("Admins only"); else showError(e.message); return; }
  $("#panels").hidden = false;
  renderStatus(); renderKeys(); renderStyles(); renderLangs(); renderSpending();
  await loadUsage();
}
function init() {
  $("#keys-form").addEventListener("submit", saveKeys);
  $("#enabled").addEventListener("change", toggleEnabled);
  $("#style-new").addEventListener("click", () => openEditor(null));
  $("#lang-add").addEventListener("click", () => $("#langs").append(langRow("", "")));
  $("#lang-save").addEventListener("click", saveLangs);
  $("#price-add").addEventListener("click", () => $("#prices").append(priceRow("", {})));
  $("#spend-save").addEventListener("click", saveSpending);
  $("#signin").addEventListener("click", () => { if (S.clerk) S.clerk.openSignIn(); else showError("Sign-in is still loading, try again in a moment."); });
  $("#signout").addEventListener("click", signOut);
  // Always set up Clerk (not only when signed out): signOut needs the Clerk object, and onSession skips the exchange when S.user is set.
  start().then(setupClerk).catch((e) => showError(e.message));
}
init();
