/**
 * @project    ELY — Exactly Like You
 * @file       extension/chrome/src/content/content-script.js
 * @brief      Injected on every page. Reads the DOM and executes the
 *             clicks/fills the backend has already approved.
 *
 * Trust model (03/09/2026 — no in-page overlay, and none is promised):
 *   - READ_DOM, READ_TEXT, WAIT_FOR — read-only.
 *   - CLICK, FILL, NAVIGATE — executed as received; approval lives
 *     server-side (backend HITL gate, LOCKED_HITL_TOOLS) and the user
 *     watches the tab live in their own Chrome window.
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

    // Sprint 1 implementations.
    //
    // No in-page HITL overlay — the trust model is:
    //   - The agent only emits a click on explicit user request in chat.
    //   - The user sees the tab live in their own Chrome window.
    //   - The backend can lock specific tool names via LOCKED_HITL_TOOLS
    //     if some flow needs server-side confirmation.
    // This is the "the user is watching" version, and it is the model
    // shipped: no overlay is promised anywhere else.
    click({ selector } = {}) {
      if (!selector) return { ok: false, error: "missing_selector" };
      let nodes;
      try { nodes = document.querySelectorAll(selector); }
      catch (e) { return { ok: false, error: "invalid_selector", detail: String(e) }; }
      if (nodes.length === 0) return { ok: false, error: "selector_not_found", selector };

      // Pick the first VISIBLE match — React apps often render duplicate
      // selectors (e.g. mobile + desktop variants both in the DOM) and
      // clicking the hidden one does nothing visible to the user.
      let target = null;
      for (const n of nodes) {
        const r = n.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) { target = n; break; }
      }
      if (!target) target = nodes[0]; // fall back if everything is offscreen

      try {
        // Bring it into view first, otherwise position-fixed overlays can
        // intercept synthetic clicks on long pages.
        target.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
      } catch { /* old browsers ignore options */ }

      // Native .click() is enough for 95 % of cases (React, Vue, Svelte
      // all listen to native click events). For the remaining 5 % we
      // also dispatch a bubbling MouseEvent so frameworks that bind to
      // mousedown/mouseup still fire their handlers.
      try {
        target.focus?.();
        const evt = new MouseEvent("click", {
          bubbles: true, cancelable: true, view: window, button: 0,
        });
        target.dispatchEvent(evt);
        // Belt-and-suspenders: also call the property method, which some
        // React synthetic-event wrappers prefer.
        if (typeof target.click === "function") target.click();
      } catch (e) {
        return { ok: false, error: "click_failed", detail: String(e) };
      }

      return {
        ok: true,
        clicked: true,
        selector,
        matched: nodes.length,
        tag: target.tagName?.toLowerCase() || null,
        text: (target.innerText || target.textContent || "").slice(0, 200).trim(),
        url: location.href,
      };
    },

    fill({ selector, value } = {}) {
      if (!selector) return { ok: false, error: "missing_selector" };
      if (value == null) return { ok: false, error: "missing_value" };
      let element;
      try { element = document.querySelector(selector); }
      catch (e) { return { ok: false, error: "invalid_selector", detail: String(e) }; }
      if (!element) return { ok: false, error: "selector_not_found", selector };

      // React + controlled inputs intercept the native value setter. Going
      // through the prototype's native setter and then dispatching `input`
      // events is the documented workaround (see facebook/react#10135).
      const nativeSetter = Object.getOwnPropertyDescriptor(
        element instanceof HTMLTextAreaElement
          ? window.HTMLTextAreaElement.prototype
          : window.HTMLInputElement.prototype,
        "value"
      )?.set;

      try {
        element.focus?.();
        if (nativeSetter && (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) {
          nativeSetter.call(element, String(value));
        } else {
          element.value = String(value);
        }
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (e) {
        return { ok: false, error: "fill_failed", detail: String(e) };
      }
      return { ok: true, selector, value_length: String(value).length };
    },

    navigate({ url } = {}) {
      if (!url) return { ok: false, error: "missing_url" };
      if (!/^https?:\/\//i.test(url)) {
        return { ok: false, error: "url_must_be_http_or_https" };
      }
      // Use location.assign for proper history entry. Reply BEFORE navigating
      // because the navigation will tear down this content-script context.
      const reply = { ok: true, navigated_to: url, from: location.href };
      setTimeout(() => { location.assign(url); }, 0);
      return reply;
    },
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
