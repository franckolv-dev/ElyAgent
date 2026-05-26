/**
 * @project    ELY — Exactly Like You
 * @file       extension/chrome/src/background/service-worker.js
 * @brief      MV3 service worker — owns the WebSocket to the ELY backend and
 *             routes commands to/from the active tab's content script.
 *
 * Lifecycle:
 *   - On startup OR when config changes, attempt to connect.
 *   - WebSocket connects to <backendUrl>/ws/browser-extension with JWT
 *     passed via the initial HELLO envelope (cookie-less auth — works
 *     even from a different origin than the ELY web app).
 *   - Reconnect with exponential backoff (1s → 30s) if the socket drops.
 *   - Forward READ_DOM/CLICK/FILL/etc. to the active tab's content
 *     script via chrome.tabs.sendMessage(); pass results back to backend.
 */

import { CMD, EVT, makeEnvelope, makeResult } from "../shared/protocol.js";
import { getConfig, markSeen } from "../shared/storage.js";

// ── State (lives only as long as the service worker is awake) ────────
let ws = null;
let reconnectAttempts = 0;
let reconnectTimer = null;
let lastError = null;
// When set, we stop trying to reconnect automatically — only a manual
// "Reconnect" click from the popup or a config change wakes us up.
let suspended = false;
// Re-entrancy guard: prevents two concurrent connect() calls from
// racing each other when storage changes AND the popup explicitly
// sends "ely:reconnect" at almost the same time.
let connecting = false;

const MAX_BACKOFF_MS = 30_000;
const MIN_BACKOFF_MS = 1_000;
// Heartbeat keeps the MV3 service worker alive (Chrome shuts it down
// after ~30s of network inactivity) AND keeps the WebSocket chair
// behind nginx/Cloudflare idle timeouts.
const HEARTBEAT_MS = 20_000;
let heartbeatTimer = null;

// WebSocket close codes that mean "don't bother retrying — the user has
// to fix something". 4001 = invalid token, 4029 = rate-limited, 1008 =
// policy violation (bad handshake).
const FATAL_CLOSE_CODES = new Set([4001, 4029, 1008]);

function log(...args) {
  console.info("[ELY-EXT]", ...args);
}

function broadcastStatus(status, extra = {}) {
  // Popup listens to this to update its UI in real time.
  chrome.runtime.sendMessage({ kind: "ely:status", status, ...extra }).catch(() => {});
}

// ── Connection lifecycle ──────────────────────────────────────────────
async function connect() {
  // Hard guard: prevent concurrent connect() races. Three legitimate
  // entry points exist (onInstalled, onStartup, top-level, storage
  // listener, popup) and they can fire near-simultaneously — without
  // this lock the registry would "replace" a connection with another
  // initiated 50ms earlier, kicking the user into a reconnect loop.
  if (connecting) {
    log("connect() already in progress — ignored");
    return;
  }
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    log("connect() called but socket is already open/connecting — ignored");
    return;
  }
  if (suspended) {
    log("connect() called while suspended — ignoring");
    return;
  }
  connecting = true;
  const { backendUrl, jwt } = await getConfig();
  if (!backendUrl || !jwt) {
    lastError = "missing_config";
    suspended = true; // no point in retrying without config
    connecting = false;
    broadcastStatus("disconnected", { reason: "missing_config" });
    return;
  }

  // Convert https → wss, http → ws.
  const wsUrl = backendUrl.replace(/^https?/, (m) => (m === "https" ? "wss" : "ws"))
                          + "/ws/browser-extension";
  log("Connecting to", wsUrl);
  broadcastStatus("connecting");

  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    lastError = String(e);
    connecting = false;
    scheduleReconnect();
    return;
  }

  ws.onopen = async () => {
    log("WebSocket open");
    connecting = false;
    reconnectAttempts = 0;
    // Send HELLO with JWT immediately — backend rejects/closes if invalid.
    const tab = await getActiveTab();
    const hello = makeEnvelope(EVT.HELLO, {
      jwt,
      extension_version: chrome.runtime.getManifest().version,
      user_agent: navigator.userAgent,
      initial_tab: tab ? { id: tab.id, url: tab.url, title: tab.title } : null,
    });
    ws.send(JSON.stringify(hello));
    await markSeen();
    broadcastStatus("connected");
    startHeartbeat();
  };

  ws.onmessage = async (evt) => {
    let env;
    try { env = JSON.parse(evt.data); }
    catch (e) { log("Bad JSON from backend:", e); return; }

    if (env.type === "ping") {
      ws.send(JSON.stringify(makeEnvelope(EVT.PONG, {}, env.id)));
      return;
    }
    if (env.type === "error") {
      log("Backend error:", env.payload);
      lastError = env.payload?.message || "backend_error";
      return;
    }
    // Backend's post-handshake ACK — informational, not a command.
    if (env.type === "connected") {
      log("Backend ACK:", env.payload);
      return;
    }

    // Dispatch a command to the active tab's content script.
    await handleCommand(env);
  };

  ws.onclose = (e) => {
    log("WebSocket closed", e.code, e.reason);
    stopHeartbeat();
    ws = null;
    connecting = false;
    const reason = e.reason || `code_${e.code}`;
    broadcastStatus("disconnected", { reason });
    // On fatal codes, freeze the loop and wait for the user to act.
    if (FATAL_CLOSE_CODES.has(e.code)) {
      suspended = true;
      lastError = reason;
      log("Suspending auto-reconnect — fix the config or click Reconnect.");
      return;
    }
    scheduleReconnect();
  };

  ws.onerror = (e) => {
    log("WebSocket error", e);
    lastError = "ws_error";
    connecting = false;
  };
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws?.readyState !== WebSocket.OPEN) return;
    try { ws.send(JSON.stringify(makeEnvelope("ping"))); }
    catch (e) { log("heartbeat failed:", e); }
  }, HEARTBEAT_MS);
}
function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
}

function scheduleReconnect() {
  if (suspended) return;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  const delay = Math.min(
    MAX_BACKOFF_MS,
    MIN_BACKOFF_MS * Math.pow(2, reconnectAttempts),
  );
  reconnectAttempts++;
  log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
  reconnectTimer = setTimeout(() => connect().catch(log), delay);
}

function disconnect() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  if (ws) { try { ws.close(); } catch {} ws = null; }
  suspended = true;
  broadcastStatus("disconnected", { reason: "manual" });
}

// Called from popup "Reconnect" button or from storage change.
function manualReconnect() {
  suspended = false;
  reconnectAttempts = 0;
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  if (ws) { try { ws.close(); } catch {} ws = null; }
  connect().catch(log);
}

// ── Tab helpers ───────────────────────────────────────────────────────
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab || null;
}

// ── Command dispatch (backend → content script) ──────────────────────
//
// Tab targeting:
//   - If the payload has a numeric tab_id, that exact tab is used. The
//     backend gets the list of tabs via list_tabs first, then sends
//     follow-up commands with the chosen tab_id. This is how the user
//     can ask "look at my LinkedIn tab" while typing in the ELY chat
//     tab.
//   - If no tab_id is given, fall back to the active tab (legacy
//     single-tab use case, e.g. the ELY mobile app browsing while ELY
//     runs on another device).
async function resolveTargetTab(env) {
  const explicit = env?.payload?.tab_id;
  if (explicit != null) {
    try { return await chrome.tabs.get(explicit); }
    catch { return null; }
  }
  return await getActiveTab();
}

async function handleCommand(env) {
  // LIST_TABS doesn't target a specific tab.
  if (env.type === CMD.LIST_TABS) {
    try {
      const tabs = await chrome.tabs.query({});
      const list = tabs
        .filter((t) => /^https?:/i.test(t.url || ""))
        .map((t) => ({
          tab_id: t.id,
          window_id: t.windowId,
          url: t.url,
          title: t.title,
          active: t.active,
          index: t.index,
        }));
      ws?.send(JSON.stringify(makeResult(env.id, true, { tabs: list })));
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  // OPEN_TAB — creates a new Chrome tab. Inherits the user's Chrome profile,
  // i.e. their cookies / authenticated sessions. Returns the new tab id.
  // Defaults to background (active=false) so the user isn't disrupted.
  if (env.type === CMD.OPEN_TAB) {
    try {
      const url = (env.payload?.url || "").trim();
      if (!/^https?:\/\//i.test(url)) {
        ws?.send(JSON.stringify(makeResult(env.id, false, null, "url_must_be_http_or_https")));
        return;
      }
      const active = !!env.payload?.active; // default false
      const newTab = await chrome.tabs.create({ url, active });
      ws?.send(JSON.stringify(makeResult(env.id, true, {
        tab_id: newTab.id, url: newTab.url, title: newTab.title, active,
      })));
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  // CLOSE_TAB — clean up after reading. Refuses to close ELY's own tab
  // to protect the chat session.
  if (env.type === CMD.CLOSE_TAB) {
    try {
      const tabId = env.payload?.tab_id;
      if (typeof tabId !== "number") {
        ws?.send(JSON.stringify(makeResult(env.id, false, null, "missing_tab_id")));
        return;
      }
      const target = await chrome.tabs.get(tabId).catch(() => null);
      if (!target) {
        ws?.send(JSON.stringify(makeResult(env.id, false, null, "tab_not_found")));
        return;
      }
      // Protect ELY's own tab from being closed by itself.
      const { backendUrl } = await getConfig();
      if (backendUrl && target.url && target.url.startsWith(backendUrl)) {
        ws?.send(JSON.stringify(makeResult(env.id, false, null, "refused_close_ely_tab")));
        return;
      }
      await chrome.tabs.remove(tabId);
      ws?.send(JSON.stringify(makeResult(env.id, true, { tab_id: tabId, closed: true })));
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  // WAIT_LOADED — resolves when the target tab reaches `status: "complete"`.
  // Useful right after OPEN_TAB to make sure the DOM is settled before
  // calling read_text / read_dom.
  if (env.type === CMD.WAIT_LOADED) {
    const tabId = env.payload?.tab_id;
    const timeoutMs = (env.payload?.timeout_s ?? 15) * 1000;
    if (typeof tabId !== "number") {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, "missing_tab_id")));
      return;
    }
    try {
      const current = await chrome.tabs.get(tabId).catch(() => null);
      if (!current) {
        ws?.send(JSON.stringify(makeResult(env.id, false, null, "tab_not_found")));
        return;
      }
      if (current.status === "complete") {
        ws?.send(JSON.stringify(makeResult(env.id, true, {
          tab_id: tabId, url: current.url, title: current.title, waited_ms: 0,
        })));
        return;
      }
      // Listen for status updates with a timeout.
      const result = await new Promise((resolve) => {
        const start = Date.now();
        const listener = (updatedId, info, tab) => {
          if (updatedId !== tabId) return;
          if (info.status === "complete") {
            chrome.tabs.onUpdated.removeListener(listener);
            resolve({
              ok: true, tab_id: tabId, url: tab.url, title: tab.title,
              waited_ms: Date.now() - start,
            });
          }
        };
        chrome.tabs.onUpdated.addListener(listener);
        setTimeout(() => {
          chrome.tabs.onUpdated.removeListener(listener);
          resolve({ ok: false, error: "timeout", waited_ms: Date.now() - start });
        }, timeoutMs);
      });
      if (result.ok) {
        ws?.send(JSON.stringify(makeResult(env.id, true, result)));
      } else {
        ws?.send(JSON.stringify(makeResult(env.id, false, null, result.error)));
      }
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  // ── Sprint 0.7 — Chrome v2 read-only inspectors ──────────────────────
  // These commands query Chrome's APIs directly (no tab targeting). The
  // backend tool clamps `days_back ≤ 30` and `max_results ≤ 20` BEFORE
  // we get here, and applies a domain blacklist on the response. The
  // extension just executes the API and returns the rows.

  // GET_HISTORY — visit history. Defaults: 7 days back, 50 max items
  // (the backend will already have clamped max_results to ≤20).
  if (env.type === CMD.GET_HISTORY) {
    try {
      const query = String(env.payload?.query ?? "");
      // chrome.history.search wants `startTime` (epoch ms). Convert days
      // back into a timestamp; cap at 30 days as a second line of
      // defence even if the backend clamping is ever bypassed.
      const daysBack = Math.min(Math.max(Number(env.payload?.days_back ?? 7), 1), 30);
      const maxResults = Math.min(Math.max(Number(env.payload?.max_results ?? 50), 1), 100);
      const startTime = Date.now() - daysBack * 24 * 60 * 60 * 1000;
      const items = await chrome.history.search({
        text: query,
        startTime,
        maxResults,
      });
      const rows = items.map((it) => ({
        url: it.url,
        title: it.title || "",
        visit_count: it.visitCount ?? 0,
        last_visit_time: it.lastVisitTime ?? 0,
        typed_count: it.typedCount ?? 0,
      }));
      ws?.send(JSON.stringify(makeResult(env.id, true, { items: rows })));
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  // GET_BOOKMARKS — search if a query is given, else the full tree.
  // chrome.bookmarks.search returns a flat list; chrome.bookmarks.getTree
  // gives the folder hierarchy. The backend asks for one or the other.
  if (env.type === CMD.GET_BOOKMARKS) {
    try {
      const query = String(env.payload?.query ?? "").trim();
      let items;
      if (query) {
        const hits = await chrome.bookmarks.search(query);
        items = hits.map((b) => ({
          id: b.id,
          parent_id: b.parentId,
          title: b.title || "",
          url: b.url || null,                   // null for folders
          date_added: b.dateAdded ?? 0,
        }));
      } else {
        // Empty query → flatten the full tree to a list of bookmarks.
        const tree = await chrome.bookmarks.getTree();
        items = [];
        const walk = (node, folderPath) => {
          if (node.url) {
            items.push({
              id: node.id,
              parent_id: node.parentId,
              title: node.title || "",
              url: node.url,
              date_added: node.dateAdded ?? 0,
              folder_path: folderPath,
            });
          }
          if (node.children) {
            const nextPath = node.title ? `${folderPath}/${node.title}` : folderPath;
            for (const child of node.children) walk(child, nextPath);
          }
        };
        for (const root of tree) walk(root, "");
      }
      ws?.send(JSON.stringify(makeResult(env.id, true, { items })));
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  // GET_DOWNLOADS — recent downloads. `state` filters to in_progress /
  // interrupted / complete (default: any).
  if (env.type === CMD.GET_DOWNLOADS) {
    try {
      const query = String(env.payload?.query ?? "").trim();
      const state = env.payload?.state;  // undefined | "in_progress" | "interrupted" | "complete"
      const maxResults = Math.min(Math.max(Number(env.payload?.max_results ?? 20), 1), 100);
      const searchParams = { limit: maxResults, orderBy: ["-startTime"] };
      if (query) searchParams.query = [query];
      if (state) searchParams.state = state;
      const items = await chrome.downloads.search(searchParams);
      const rows = items.map((d) => ({
        id: d.id,
        url: d.url,
        final_url: d.finalUrl || d.url,
        filename: d.filename || "",
        mime: d.mime || "",
        state: d.state,
        bytes_received: d.bytesReceived ?? 0,
        total_bytes: d.totalBytes ?? 0,
        start_time: d.startTime || "",
        end_time: d.endTime || "",
        exists: d.exists ?? false,
      }));
      ws?.send(JSON.stringify(makeResult(env.id, true, { items: rows })));
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  const tab = await resolveTargetTab(env);
  if (!tab) {
    ws?.send(JSON.stringify(makeResult(env.id, false, null, "tab_not_found")));
    return;
  }

  // Tabs on chrome:// or extension pages can't be scripted.
  if (!/^https?:/i.test(tab.url || "")) {
    ws?.send(JSON.stringify(makeResult(env.id, false, null, "protected_url")));
    return;
  }

  // GET_URL handled entirely by the service worker.
  if (env.type === CMD.GET_URL) {
    ws?.send(JSON.stringify(makeResult(env.id, true, {
      tab_id: tab.id, url: tab.url, title: tab.title,
    })));
    return;
  }

  // SCREENSHOT also lives in the SW (chrome.tabs.captureVisibleTab).
  // captureVisibleTab takes a windowId — we capture the window containing
  // the target tab, switching to it briefly if necessary.
  if (env.type === CMD.SCREENSHOT) {
    try {
      // captureVisibleTab captures the active tab in the target window.
      // If the requested tab isn't already active there, we activate it,
      // capture, then restore — slightly invasive but the only way to
      // screenshot a non-active tab in MV3.
      let prevActiveId = null;
      if (!tab.active) {
        const [prevActive] = await chrome.tabs.query({ active: true, windowId: tab.windowId });
        prevActiveId = prevActive?.id;
        await chrome.tabs.update(tab.id, { active: true });
      }
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
      if (prevActiveId != null) {
        await chrome.tabs.update(prevActiveId, { active: true });
      }
      ws?.send(JSON.stringify(makeResult(env.id, true, { tab_id: tab.id, data_url: dataUrl })));
    } catch (e) {
      ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
    }
    return;
  }

  // Everything else: forward to the content script on the target tab.
  try {
    const response = await chrome.tabs.sendMessage(tab.id, {
      kind: "ely:cmd",
      envelope: env,
    });
    ws?.send(JSON.stringify(makeResult(env.id, true, response)));
  } catch (e) {
    ws?.send(JSON.stringify(makeResult(env.id, false, null, String(e))));
  }
}

// ── Tab events → backend ─────────────────────────────────────────────
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (tab && ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(makeEnvelope(EVT.TAB_CHANGED, {
      tab_id: tab.id, url: tab.url, title: tab.title,
    })));
  }
});

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" && ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(makeEnvelope(EVT.PAGE_NAVIGATED, {
      tab_id: tabId, url: tab.url, title: tab.title,
    })));
  }
});

// ── Messages from popup / options page / content scripts ─────────────
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.kind === "ely:reconnect") {
    manualReconnect();
    sendResponse({ ok: true });
    return false;
  }
  if (msg?.kind === "ely:disconnect") {
    disconnect();
    sendResponse({ ok: true });
    return false;
  }
  if (msg?.kind === "ely:get-status") {
    sendResponse({
      connected: ws?.readyState === WebSocket.OPEN,
      lastError,
      readyState: ws?.readyState ?? -1,
    });
    return false;
  }
  if (msg?.kind === "ely:hitl-decision") {
    // Forward the user's HITL choice back to the backend.
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(makeEnvelope(EVT.HITL_DECISION, msg.payload)));
    }
    sendResponse({ ok: true });
    return false;
  }
  return false;
});

// ── Storage changes (config update via Options page) ─────────────────
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.ely_backend_url || changes.ely_jwt) {
    log("Config changed, reconnecting…");
    manualReconnect();
  }
});

// ── Startup ──────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  log("Installed", chrome.runtime.getManifest().version);
  connect().catch(log);
});
chrome.runtime.onStartup.addListener(() => {
  connect().catch(log);
});
// Attempt connection immediately when the SW spins up (e.g. after sleep).
connect().catch(log);
