/**
 * @project    ELY — Exactly Like You
 * @file       extension/chrome/src/popup/popup.js
 * @brief      Popup UI logic — show connection status, allow reconnect /
 *             jump to options page.
 */

import { getConfig } from "../shared/storage.js";

const $ = (id) => document.getElementById(id);

const STATUS_LBL = {
  connected:    "Connecté",
  connecting:   "Connexion…",
  disconnected: "Déconnecté",
};

function applyStatus(status, extra = {}) {
  const box = $("status");
  box.classList.remove("connected", "connecting", "disconnected");
  box.classList.add(status);
  $("lbl").textContent = STATUS_LBL[status] || status;

  let hint = "";
  if (status === "disconnected") {
    if (extra.reason === "missing_config") {
      hint = `Aucune configuration — clic sur <em>Réglages</em> pour ajouter l'URL d'ELY et un jeton d'accès.`;
    } else {
      hint = `Dernière erreur : <code>${extra.reason || "inconnue"}</code>`;
    }
  } else if (status === "connected") {
    hint = `Ely peut maintenant lire les pages que tu ouvres et — avec ton accord — agir dessus.`;
  }
  $("hint").innerHTML = hint;
}

async function refresh() {
  const cfg = await getConfig();
  $("backend").textContent = cfg.backendUrl || "—";
  $("backend").title = cfg.backendUrl || "";

  // Active tab info
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tab) {
      const host = (() => { try { return new URL(tab.url).hostname; } catch { return tab.url || "—"; } })();
      $("tab").textContent = host;
      $("tab").title = tab.url || "";
    }
  } catch {}

  // Status from background service worker.
  try {
    const status = await chrome.runtime.sendMessage({ kind: "ely:get-status" });
    if (status?.connected) applyStatus("connected");
    else applyStatus("disconnected", { reason: status?.lastError });
  } catch {
    applyStatus("disconnected", { reason: "no_sw" });
  }
}

// Listen for real-time status broadcasts from the service worker.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.kind === "ely:status") {
    applyStatus(msg.status, msg);
  }
});

$("btnReconnect").addEventListener("click", async () => {
  applyStatus("connecting");
  await chrome.runtime.sendMessage({ kind: "ely:reconnect" });
});

$("btnSettings").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

refresh();
