/**
 * @project    ELY — Exactly Like You
 * @file       extension/chrome/src/shared/protocol.js
 * @brief      Typed message protocol for ELY browser extension <-> backend
 *
 * Protocol overview:
 *   - The extension connects to the backend over wss:// on the user's
 *     configured ELY instance (e.g. ely.catalogmaker.fr).
 *   - All messages are JSON envelopes: { id, type, payload, ts }.
 *   - The backend issues commands (READ_DOM, CLICK, FILL, SCREENSHOT…).
 *   - The extension responds with the same `id` and a result/error.
 *   - The extension also pushes events (TAB_CHANGED, PAGE_NAVIGATED…).
 *   - Every destructive action goes through HITL: the extension renders
 *     an in-page overlay and waits for the user's explicit approval
 *     before executing. The user's choice is sent back to the backend.
 *
 * Versioning:
 *   - PROTOCOL_VERSION is bumped on every breaking change to the
 *     message shape. Backend rejects extensions on mismatched majors.
 */

export const PROTOCOL_VERSION = "0.1.0";

// ── Command types (backend → extension) ──────────────────────────────
export const CMD = Object.freeze({
  PING: "ping",                  // backend keepalive
  LIST_TABS: "list_tabs",        // enumerate all open tabs (id, url, title)
  OPEN_TAB: "open_tab",          // open URL in a new tab (inherits Chrome profile = sessions)
  CLOSE_TAB: "close_tab",        // close a tab by id (clean-up after read)
  WAIT_LOADED: "wait_loaded",    // wait until a tab finishes loading (status=complete)
  READ_DOM: "read_dom",          // serialize DOM of the target tab (or a selector)
  READ_TEXT: "read_text",        // textContent of the target tab body or selector
  GET_URL: "get_url",            // tab URL + title (defaults to active)
  SCREENSHOT: "screenshot",      // visible viewport of target tab as base64 PNG
  CLICK: "click",                // click(selector) — DESTRUCTIVE → HITL
  FILL: "fill",                  // fill(selector, value) — DESTRUCTIVE → HITL
  NAVIGATE: "navigate",          // load URL in target tab — DESTRUCTIVE → HITL
  WAIT_FOR: "wait_for",          // wait for selector to appear (read-only)
  // ── Sprint 0.7 — Chrome v2: history / bookmarks / downloads ─────────
  // All three are READ_ONLY. The backend tools clamp days_back ≤ 30 and
  // max_results ≤ 20, and a domain blacklist (banking/health/adult) is
  // applied server-side before the agent sees the results. The extension
  // simply executes the chrome.* APIs and returns the raw rows.
  GET_HISTORY: "get_history",      // chrome.history.search(query, days_back, max_results)
  GET_BOOKMARKS: "get_bookmarks",  // chrome.bookmarks.search(query) — folder tree if empty
  GET_DOWNLOADS: "get_downloads",  // chrome.downloads.search(query, state, max_results)
});

// ── Event types (extension → backend) ────────────────────────────────
export const EVT = Object.freeze({
  HELLO: "hello",                // sent on connect with extension info + auth
  TAB_CHANGED: "tab_changed",    // active tab id/URL changed
  PAGE_NAVIGATED: "page_navigated", // a tab finished loading a new URL
  HITL_DECISION: "hitl_decision", // user accepted/refused a destructive action
  PONG: "pong",
});

// Read-only / non-destructive commands don't require HITL approval.
// Note: OPEN_TAB and CLOSE_TAB are non-destructive — the user can always
// see the new tab appear or be closed (no data is altered server-side).
const READ_ONLY_CMDS = new Set([
  CMD.PING, CMD.LIST_TABS, CMD.OPEN_TAB, CMD.CLOSE_TAB, CMD.WAIT_LOADED,
  CMD.READ_DOM, CMD.READ_TEXT, CMD.GET_URL, CMD.SCREENSHOT, CMD.WAIT_FOR,
  // Sprint 0.7 — Chrome v2 read-only inspectors
  CMD.GET_HISTORY, CMD.GET_BOOKMARKS, CMD.GET_DOWNLOADS,
]);

export function isDestructive(commandType) {
  return !READ_ONLY_CMDS.has(commandType);
}

// ── Envelope helpers ─────────────────────────────────────────────────
let _nextId = 1;
export function makeEnvelope(type, payload = {}, id = null) {
  return {
    v: PROTOCOL_VERSION,
    id: id ?? `ext-${Date.now()}-${_nextId++}`,
    type,
    payload,
    ts: Date.now(),
  };
}

export function makeResult(requestId, ok, data = null, error = null) {
  return {
    v: PROTOCOL_VERSION,
    id: requestId,
    type: "result",
    payload: { ok, data, error },
    ts: Date.now(),
  };
}
