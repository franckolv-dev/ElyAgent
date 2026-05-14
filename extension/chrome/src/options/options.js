/**
 * @project    ELY — Exactly Like You
 * @file       extension/chrome/src/options/options.js
 * @brief      Options page logic — read/write config, trigger reconnect,
 *             live status feedback.
 */

import { getConfig, setConfig, clearConfig } from "../shared/storage.js";

const $ = (id) => document.getElementById(id);

const STATUS_LBL = {
  connected:    "Connecté à ELY",
  connecting:   "Connexion en cours…",
  disconnected: "Déconnecté",
};

function applyStatus(status, extra = {}) {
  const box = $("statusBox");
  box.classList.remove("connected", "connecting", "disconnected");
  box.classList.add(status);
  $("statusLabel").textContent = STATUS_LBL[status] || status;

  let hint = "";
  if (status === "disconnected") {
    if (extra.reason === "missing_config") {
      hint = "Renseignez l'URL et le jeton ci-dessus, puis cliquez sur Enregistrer.";
    } else if (extra.reason) {
      hint = `Erreur : ${extra.reason}`;
    }
  } else if (status === "connected") {
    hint = "L'extension écoute les commandes envoyées par Ely. Tu peux fermer cette page.";
  }
  $("statusHint").textContent = hint;
}

async function refresh() {
  const cfg = await getConfig();
  $("backendUrl").value = cfg.backendUrl || "";
  $("jwt").value = cfg.jwt || "";

  try {
    const status = await chrome.runtime.sendMessage({ kind: "ely:get-status" });
    if (status?.connected) applyStatus("connected");
    else applyStatus("disconnected", { reason: status?.lastError });
  } catch {
    applyStatus("disconnected", { reason: "no_sw" });
  }
}

// Live status broadcasts.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.kind === "ely:status") {
    applyStatus(msg.status, msg);
  }
});

$("save").addEventListener("click", async () => {
  const backendUrl = $("backendUrl").value.trim();
  const jwt = $("jwt").value.trim();
  if (!backendUrl || !jwt) {
    applyStatus("disconnected", { reason: "missing_config" });
    return;
  }
  await setConfig({ backendUrl, jwt });
  applyStatus("connecting");
  await chrome.runtime.sendMessage({ kind: "ely:reconnect" });
});

// "Generate a token in ELY" — opens the Settings → Extension page in a new
// tab on whatever backend URL is currently configured (falls back to
// agent-ely.fr if empty so first-time users have a sane default).
$("openTokenPage").addEventListener("click", async () => {
  const cfgUrl = $("backendUrl").value.trim().replace(/\/$/, "");
  // The backend URL is the API host; the web UI lives at the same origin
  // for ely.catalogmaker.fr / agent-ely.fr deployments. For users running
  // a split deployment (api.foo / app.foo) they'll need to fix the URL
  // by hand but that's a niche case — the help text above flags it.
  const base = cfgUrl || "https://agent-ely.fr";
  chrome.tabs.create({ url: `${base}/settings/extension` });
});

$("clear").addEventListener("click", async () => {
  if (!confirm("Effacer la configuration et déconnecter l'extension ?")) return;
  await clearConfig();
  $("backendUrl").value = "";
  $("jwt").value = "";
  await chrome.runtime.sendMessage({ kind: "ely:disconnect" });
  applyStatus("disconnected", { reason: "manual" });
});

refresh();
