"use strict";
// Shared by app.js and admin.js (plain script, loaded first; no build step).

async function rawApi(method, path, body) {
  const res = await fetch(path, {
    method, credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty or non-JSON body */ }
  if (!res.ok) { const e = new Error(data?.error || "Something went wrong, try again"); e.status = res.status; throw e; }
  return data;
}

function loadScript(src, attrs = {}) {
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = src; el.async = true;
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    el.onload = resolve; el.onerror = () => reject(new Error(`Could not load ${src}`));
    document.head.appendChild(el);
  });
}

function frontendApi(pk) {
  try { return atob(pk.replace(/^pk_(test|live)_/, "")).replace(/\$$/, ""); } catch { return null; }
}

// Loads Clerk (ui@1 -> clerk-js@6 -> Clerk.load) and calls onSession(clerk) whenever a session exists.
// Resolves to the Clerk object, or null when Clerk isn't configured or fails to load.
async function loadClerk(pk, onSession) {
  const fapi = pk && frontendApi(pk);
  if (!fapi) return null;
  try {
    const npm = `https://${fapi}/npm`;
    await loadScript(`${npm}/@clerk/ui@1/dist/ui.browser.js`, { crossorigin: "anonymous" });
    await loadScript(`${npm}/@clerk/clerk-js@6/dist/clerk.browser.js`,
      { crossorigin: "anonymous", "data-clerk-publishable-key": pk });
    await window.Clerk.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });
    const clerk = window.Clerk;
    clerk.addListener(({ session }) => { if (session) onSession(clerk); });
    if (clerk.session) onSession(clerk);
    return clerk;
  } catch (e) { console.warn(e); return null; }
}

// Exchanges the Clerk session token for our own session cookie; resolves to {email, is_admin}.
async function clerkExchangeToken(clerk) {
  return rawApi("POST", "/api/login/clerk", { token: await clerk.session.getToken() });
}

async function signOutAndReload(clerk) {
  try { await rawApi("POST", "/api/logout", {}); } catch { /* cookie may already be gone */ }
  try { await clerk?.signOut(); } catch (e) { console.warn(e); }
  location.reload();
}
