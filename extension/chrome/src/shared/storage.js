/**
 * @project    ELY — Exactly Like You
 * @file       extension/chrome/src/shared/storage.js
 * @brief      Local storage abstraction for ELY browser extension config.
 *
 * Stored fields:
 *   - backendUrl: base URL of the user's ELY instance (e.g. https://ely.catalogmaker.fr)
 *   - jwt:        access token copied from the ELY web app (Settings → Extension token)
 *   - lastSeen:   ISO timestamp of last successful backend ping (debug)
 */

const KEYS = Object.freeze({
  BACKEND_URL: "ely_backend_url",
  JWT: "ely_jwt",
  LAST_SEEN: "ely_last_seen",
});

export async function getConfig() {
  const items = await chrome.storage.local.get([
    KEYS.BACKEND_URL, KEYS.JWT, KEYS.LAST_SEEN,
  ]);
  return {
    backendUrl: items[KEYS.BACKEND_URL] || "",
    jwt: items[KEYS.JWT] || "",
    lastSeen: items[KEYS.LAST_SEEN] || null,
  };
}

export async function setConfig({ backendUrl, jwt }) {
  const updates = {};
  if (backendUrl !== undefined) updates[KEYS.BACKEND_URL] = backendUrl.trim().replace(/\/+$/, "");
  if (jwt !== undefined) updates[KEYS.JWT] = jwt.trim();
  await chrome.storage.local.set(updates);
}

export async function markSeen() {
  await chrome.storage.local.set({ [KEYS.LAST_SEEN]: new Date().toISOString() });
}

export async function clearConfig() {
  await chrome.storage.local.remove(Object.values(KEYS));
}

export { KEYS };
