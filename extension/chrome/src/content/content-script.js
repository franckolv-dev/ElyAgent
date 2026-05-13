/**
 * @project    ELY — Exactly Like You
 * @file       extension/chrome/src/content/content-script.js
 * @brief      Injected on every page. Reads DOM, renders HITL overlay,
 *             executes clicks/fills under explicit user approval.
 *
 * Sprint 0 scope (current):
 *   - READ_DOM, READ_TEXT, WAIT_FOR — read-only, no approval needed.
 *   - CLICK, FILL, NAVIGATE — destructive — defer to Sprint 1
 *     (the protocol exists, the handler exists but always returns
 *      `{ ok: false, error: "not_implemented_yet" }` for safety until
 *      the HITL overlay is wired up).
 */

(function () {
  if (window.__ely_content_script_loaded) return;
  window.__ely_content_script_loaded = true;

  function safeOuterHTML(node, maxBytes = 200_000) {
    try {
      const html = node.outerHTML || "";
      if (html.length <= maxBytes) return html;
      return html.slice(0, maxBytes) + "<!-- ELY truncated at " + maxBytes + " bytes -->";
    } catch { return ""; }
  }

  function safeText(node, maxBytes = 50_000) {
    try {
      const text = (node.textContent || "").trim();
      if (text.length <= maxBytes) return text;
      return text.slice(0, maxBytes) + " […ELY truncated]";
    } catch { return ""; }
  }

  function querySelectorOrBody(selector) {
    if (!selector) return document.body;
    try { return document.querySelector(selector); }
    catch { return null; }
  }

  // ── Command handlers ────────────────────────────────────────────────
  const handlers = {
    read_dom({ selector } = {}) {
      const node = querySelectorOrBody(selector);
      if (!node) return { ok: false, error: "selector_not_found" };
      return {
        ok: true,
        url: location.href,
        title: document.title,
        selector: selector || "body",
        html: safeOuterHTML(node),
      };
    },

    read_text({ selector } = {}) {
      const node = querySelectorOrBody(selector);
      if (!node) return { ok: false, error: "selector_not_found" };
      return {
        ok: true,
        url: location.href,
        title: document.title,
        selector: selector || "body",
        text: safeText(node),
      };
    },

    wait_for({ selector, timeout_ms = 5000 } = {}) {
      return new Promise((resolve) => {
        const existing = querySelectorOrBody(selector);
        if (existing) return resolve({ ok: true, found: true });

        const start = Date.now();
        const observer = new MutationObserver(() => {
          if (querySelectorOrBody(selector)) {
            observer.disconnect();
            resolve({ ok: true, found: true, waited_ms: Date.now() - start });
          }
        });
        observer.observe(document.body, { childList: true, subtree: true });
        setTimeout(() => {
          observer.disconnect();
          resolve({ ok: false, error: "timeout", waited_ms: Date.now() - start });
        }, timeout_ms);
      });
    },

    // Sprint 1 will replace these stubs with HITL-gated implementations.
    click() { return { ok: false, error: "not_implemented_yet_sprint1" }; },
    fill()  { return { ok: false, error: "not_implemented_yet_sprint1" }; },
    navigate() { return { ok: false, error: "not_implemented_yet_sprint1" }; },
  };

  // ── Service worker bridge ───────────────────────────────────────────
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.kind !== "ely:cmd") return false;
    const env = msg.envelope;
    const handler = handlers[env.type];
    if (!handler) {
      sendResponse({ ok: false, error: "unknown_command", type: env.type });
      return false;
    }
    try {
      const result = handler(env.payload || {});
      if (result instanceof Promise) {
        result.then(sendResponse).catch((e) => sendResponse({ ok: false, error: String(e) }));
        return true; // keep the message channel open for async response
      }
      sendResponse(result);
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
    return false;
  });

  // Hint that the content script is alive (debug).
  console.info("[ELY-EXT] content script ready on", location.href);
})();
