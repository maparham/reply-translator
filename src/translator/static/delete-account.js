"use strict";
const $ = (s) => document.querySelector(s);
(async () => {
  let cfg;
  try { cfg = await rawApi("GET", "/api/config"); }
  catch { $("#error").textContent = "Could not load, reload the page."; $("#error").hidden = false; return; }
  if (!cfg.user) { $("#signed-out").hidden = false; return; }
  $("#email").textContent = cfg.user.email;
  $("#signed-in").hidden = false;
  $("#delete").addEventListener("click", async () => {
    if (!confirm(`Delete the account ${cfg.user.email} and all its history? This cannot be undone.`)) return;
    $("#delete").disabled = true;
    try {
      await rawApi("DELETE", "/api/account");
      $("#signed-in").hidden = true;
      $("#done").hidden = false;
    } catch (e) {
      $("#error").textContent = e.message; $("#error").hidden = false;
      $("#delete").disabled = false;
    }
  });
})();
