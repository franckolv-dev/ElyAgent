# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/browser_extension_tool.py
# @brief      Tools that act in the user's REAL Chrome tab via the ELY
#             browser extension (Sprint 2: read-only — read_text, read_html,
#             get_url, screenshot). Click/fill/navigate come in Sprint 1
#             once the in-page HITL overlay lands.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Use the connected ELY browser extension to act on the user's own Chrome.

Why this exists
---------------
Without the extension, the agent navigates with a server-side Playwright
that has no cookies, no logged-in sessions, no user context. Anything
behind auth (LinkedIn, Gmail UI, Amazon orders, X) returns the login page.

With the extension, the agent commands the user's actual Chrome tab,
which holds the user's real cookies and sessions. The agent never sees
those cookies — it just asks "read the text of the active tab" and
gets the post-login content the user is looking at.

Operational notes
-----------------
- Every tool checks `browser_extension_registry.get(user_id)` first.
  If the extension is not connected, the tool returns a clear message
  inviting the user to install/connect it, rather than silently failing.
- Round-trip works via an `asyncio.Future` stored in the connection's
  `pending` dict, keyed by the envelope id. The browser_extension
  router resolves the future when a matching `result` envelope arrives.
- Timeout is 15 s for reads — generous because some pages take time to
  finish their async rendering, but short enough to avoid hanging the
  agent on a stuck tab.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services import browser_extension_registry as bext_registry
from app.services.chrome_privacy_filter import filter_rows as _privacy_filter_rows

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 15.0
_PROTOCOL_VERSION = "0.1.0"


def _not_connected_msg() -> str:
    return (
        "⚠️ L'extension navigateur ELY n'est pas connectée pour cet utilisateur.\n"
        "Pour utiliser ce type de capacité, installer l'extension Chrome depuis "
        "https://github.com/franckolv-dev/ElyAgent/tree/main/extension/chrome "
        "et la connecter via Options → token JWT."
    )


async def _send_and_wait(user_id: str, command_type: str, payload: dict) -> dict:
    """Send a command envelope to the user's extension and await the result.

    Returns the result payload as a dict (with `ok` + `data`/`error`).
    Raises TimeoutError if no answer comes within _DEFAULT_TIMEOUT_S.
    """
    # Normalise to str — the registry keys are always str, but the agent
    # state may pass a UUID object, which would silently miss the lookup.
    key = str(user_id) if user_id is not None else ""
    conn = bext_registry.get(key)
    if conn is None:
        # Diagnostic log so we can tell the difference between
        # "extension truly not connected" and "user_id mismatch".
        known = list(getattr(bext_registry, "_connections", {}).keys())
        logger.warning(
            "[browser-ext-tool] no connection for user_id=%r (cmd=%s). "
            "Registry currently has %d connection(s): %s",
            key, command_type, len(known), known,
        )
        return {"ok": False, "error": "extension_not_connected", "hint": _not_connected_msg()}

    envelope_id = f"backend-{uuid.uuid4().hex[:12]}"
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    conn.pending[envelope_id] = fut

    envelope = {
        "v": _PROTOCOL_VERSION,
        "id": envelope_id,
        "type": command_type,
        "payload": payload,
        "ts": int(time.time() * 1000),
    }

    try:
        await conn.websocket.send_text(json.dumps(envelope))
    except Exception as e:
        conn.pending.pop(envelope_id, None)
        return {"ok": False, "error": f"send_failed: {e}"}

    try:
        result_envelope = await asyncio.wait_for(fut, timeout=_DEFAULT_TIMEOUT_S)
    except asyncio.TimeoutError:
        conn.pending.pop(envelope_id, None)
        return {"ok": False, "error": f"timeout after {_DEFAULT_TIMEOUT_S}s"}

    # Result envelope shape:
    #   { ok: bool, data: <handler_response>, error: str | null }
    # where `data` is whatever the SW/content-script handler returned.
    # We FLATTEN so tools can do `res.get("tab_id")` directly without
    # having to navigate `res["data"]["tab_id"]`.
    #
    # If the handler itself returned an `{ok: false, error}` dict, we
    # propagate that as the source-of-truth (the transport delivered the
    # message OK, but the operation failed).
    if isinstance(result_envelope, dict):
        ok = result_envelope.get("ok", True)
        error = result_envelope.get("error")
        data = result_envelope.get("data")
        merged: dict = {"ok": bool(ok)}
        if error is not None:
            merged["error"] = error
        if isinstance(data, dict):
            # Handler's `ok`/`error` (if any) override the envelope's.
            merged.update(data)
        elif data is not None:
            merged["data"] = data
        return merged
    return {"ok": True, "data": result_envelope}


# ─────────────────────────────────────────────────────────────────────
# Tools exposed to the agent
# ─────────────────────────────────────────────────────────────────────

@tool
async def browser_list_tabs(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List every Chrome tab currently open in the user's browser.

    CALL THIS FIRST when the user asks to look at "their LinkedIn", "their
    Gmail", "this article", or any specific tab — because the conversation
    with ELY is itself running in a Chrome tab, so "the active tab" is
    almost always ELY's chat itself, not the page the user wants you to
    read. Use this list to pick the right tab_id, then pass it to the
    other browser_tab_* tools.

    Returns: a numbered list of open tabs with their tab_id, URL and title.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    res = await _send_and_wait(user_id, "list_tabs", {})
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    tabs = res.get("tabs", []) or []
    if not tabs:
        return "Aucun onglet web ouvert (seules les pages http(s) sont listées)."
    lines = [f"{len(tabs)} onglet(s) Chrome ouvert(s) :"]
    for t in tabs:
        active_marker = " ← onglet actif" if t.get("active") else ""
        lines.append(
            f"  - tab_id={t.get('tab_id')} | {t.get('title', '')[:80]}"
            f"\n      url: {t.get('url', '')}{active_marker}"
        )
    return "\n".join(lines)


@tool
async def browser_tab_get_url(
    tab_id: int = 0,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Return the URL and title of a specific Chrome tab.

    Args:
        tab_id: the numeric ID returned by browser_list_tabs. Use 0
            (or omit) to target the active tab — but remember that's
            usually the ELY chat tab itself, so prefer an explicit id.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    payload = {"tab_id": tab_id} if tab_id else {}
    res = await _send_and_wait(user_id, "get_url", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    return (
        f"URL : {res.get('url', 'inconnue')}\n"
        f"Titre : {res.get('title', 'inconnu')}\n"
        f"Tab ID : {res.get('tab_id', 'n/a')}"
    )


@tool
async def browser_tab_read_text(
    tab_id: int = 0,
    selector: str = "",
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read the visible TEXT content of a specific Chrome tab.

    USE THIS for anything behind authentication: LinkedIn profile, post
    impressions, Gmail UI, Amazon orders, X timeline, Discord messages, etc.
    The user's real session is used — no separate login needed.

    Args:
        tab_id: the numeric ID returned by browser_list_tabs. Required
            in most real cases — without it the tool falls back to the
            currently active tab, which is usually ELY's chat itself.
        selector: optional CSS selector to scope the read (e.g. "main",
            "#main-content", ".post-stats"). When empty, reads `body`.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    payload = {"selector": selector or ""}
    if tab_id:
        payload["tab_id"] = tab_id
    res = await _send_and_wait(user_id, "read_text", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    text = res.get("text", "")
    return (
        f"URL : {res.get('url', '')}\n"
        f"Titre : {res.get('title', '')}\n"
        f"Sélecteur : {res.get('selector', 'body')}\n"
        f"Contenu ({len(text)} caractères) :\n{text}"
    )


@tool
async def browser_tab_read_html(
    tab_id: int = 0,
    selector: str = "",
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read the HTML (outerHTML) of a specific Chrome tab.

    Prefer browser_tab_read_text when you only need the visible text.
    Use this when you need to inspect DOM structure, attributes, or
    specific elements (data-* attributes, hidden values, link href, etc.).

    Args:
        tab_id: the numeric ID returned by browser_list_tabs. Required
            in most real cases.
        selector: optional CSS selector to scope the read. Output is
            automatically truncated to 200 kB.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    payload = {"selector": selector or ""}
    if tab_id:
        payload["tab_id"] = tab_id
    res = await _send_and_wait(user_id, "read_dom", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    html = res.get("html", "")
    return (
        f"URL : {res.get('url', '')}\n"
        f"Sélecteur : {res.get('selector', 'body')}\n"
        f"HTML ({len(html)} caractères) :\n{html}"
    )


@tool
async def browser_tab_screenshot(
    tab_id: int = 0,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Capture a PNG screenshot of the visible viewport of a specific Chrome tab.

    The screenshot is stashed to a local backend path and returned as such
    so you can pass it directly to `vision_analyze_image(image_path=...)`
    when the page DOM is anti-bot-protected (e.g. Amazon) and
    `browser_tab_read_text` returns near-empty content.

    Usage pattern for anti-bot sites:
      1. browser_open_tab(...)
      2. browser_tab_wait_loaded(tab_id)
      3. browser_tab_screenshot(tab_id) → returns a local path
      4. vision_analyze_image(image_path=<that path>, question="...")
      5. browser_close_tab(tab_id)

    Args:
        tab_id: the numeric ID returned by browser_list_tabs.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    payload = {"tab_id": tab_id} if tab_id else {}
    res = await _send_and_wait(user_id, "screenshot", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    data_url = res.get("data_url", "")
    if not data_url:
        return "Erreur : capture sans données."

    # Stash the PNG to a local path so vision_analyze_image can pick it up
    # without dragging the full base64 through the LLM context window.
    try:
        import base64 as _b64
        import pathlib as _pl
        import uuid as _uuid

        if not data_url.startswith("data:"):
            return f"Erreur : format inattendu (data_url ne commence pas par 'data:'): {data_url[:60]}…"
        _, _payload = data_url.split(",", 1)
        _raw = _b64.b64decode(_payload)
        _dir = _pl.Path("/tmp/ely-screenshots")
        _dir.mkdir(parents=True, exist_ok=True)
        _path = _dir / f"tab-{res.get('tab_id', 'x')}-{_uuid.uuid4().hex[:8]}.png"
        _path.write_bytes(_raw)
        return (
            f"Capture prête ({len(_raw)} bytes, tab_id={res.get('tab_id', 'n/a')}).\n"
            f"\n"
            f"⚠️ ÉTAPE SUIVANTE OBLIGATOIRE — appelle DIRECTEMENT :\n"
            f"    vision_analyze_image(image_path='{_path}', question='<question_utilisateur>')\n"
            f"\n"
            f"NE PAS utiliser desktop_write_file, desktop_read_file, ou tout autre outil pour "
            f"manipuler ce chemin. Il vit dans le backend Python, pas sur la machine de l'utilisateur. "
            f"vision_analyze_image sait lire ce chemin sans intermédiaire."
        )
    except Exception as e:
        return f"Erreur lors de la sauvegarde du screenshot : {e}"


@tool
async def browser_open_tab(
    url: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Open a URL in a NEW Chrome tab in the user's browser, in the background.

    The new tab inherits the user's Chrome profile, including their cookies
    and authenticated sessions. So if the user is logged into LinkedIn /
    Gmail / Amazon in Chrome, the new tab is automatically logged in too —
    no fresh login required.

    This is the **idiomatic way to autonomously visit a page on behalf of
    the user**:
        1. browser_open_tab("https://www.linkedin.com/in/me/recent-activity/")
        2. browser_tab_wait_loaded(tab_id=<id from step 1>)
        3. browser_tab_read_text(tab_id=...)
        4. browser_close_tab(tab_id=...)  — clean up

    The tab opens in the BACKGROUND (does not steal focus), so the user
    keeps doing what they were doing in their current tab.

    Args:
        url: must start with http:// or https://. No about:, chrome:, file:.

    Returns:
        Tab id, final URL after redirects, and title. Pass tab_id to
        browser_tab_wait_loaded next.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Erreur : l'URL doit commencer par http:// ou https://."
    res = await _send_and_wait(user_id, "open_tab", {"url": url, "active": False})
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    return (
        f"Nouvel onglet ouvert en arrière-plan :\n"
        f"  tab_id : {res.get('tab_id')}\n"
        f"  URL    : {res.get('url')}\n"
        f"  Titre  : {res.get('title')}\n"
        f"→ appeler browser_tab_wait_loaded(tab_id={res.get('tab_id')}) avant de lire."
    )


@tool
async def browser_tab_wait_loaded(
    tab_id: int,
    timeout_s: int = 15,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Wait until a Chrome tab finishes loading (`document.readyState=complete`).

    Call this RIGHT AFTER browser_open_tab. It blocks for up to
    `timeout_s` seconds. Returns the final URL (after redirects) and title.

    Args:
        tab_id: the tab id returned by browser_open_tab.
        timeout_s: max wait, 15 s by default. Increase to 30 for slow pages.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    res = await _send_and_wait(user_id, "wait_loaded", {
        "tab_id": tab_id, "timeout_s": timeout_s,
    })
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    return (
        f"Onglet {res.get('tab_id')} chargé en {res.get('waited_ms', 0)} ms :\n"
        f"  URL final : {res.get('url')}\n"
        f"  Titre     : {res.get('title')}"
    )


@tool
async def browser_tab_wait_for_selector(
    tab_id: int,
    selector: str,
    timeout_s: int = 10,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Wait until a CSS selector becomes present in the target tab's DOM.

    USE THIS FOR SPAs (Amazon, LinkedIn, X, Gmail, Notion…) where
    `browser_tab_wait_loaded` returns immediately but the page content
    is still being rendered by JavaScript afterwards. Without this,
    `browser_tab_read_text` returns a near-empty DOM and you'll think
    the page is broken.

    Tip — common selectors per site:
      • Amazon orders list   : `.order-card, .a-box-group, [data-component=orderCard]`
      • LinkedIn feed        : `main, [role=main]`
      • Gmail inbox          : `.AO, [role=main]`
      • X timeline           : `[data-testid=primaryColumn]`

    Args:
        tab_id: target Chrome tab.
        selector: CSS selector to wait for (e.g. `.order-card`).
        timeout_s: max wait, 10 s default. Bump to 20-30 for heavy SPAs.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    res = await _send_and_wait(user_id, "wait_for", {
        "tab_id": tab_id, "selector": selector, "timeout_ms": timeout_s * 1000,
    })
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    return (
        f"Selector '{selector}' trouvé dans l'onglet {tab_id} en "
        f"{res.get('waited_ms', 0)} ms. Tu peux maintenant lire le contenu."
    )


@tool
async def browser_close_tab(
    tab_id: int,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Close a Chrome tab. Use this to clean up after reading an autonomous tab.

    Refuses to close the ELY chat tab itself (safety).

    Args:
        tab_id: the tab id to close.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    res = await _send_and_wait(user_id, "close_tab", {"tab_id": tab_id})
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    return f"Onglet {tab_id} fermé."


@tool
async def browser_tab_click(
    selector: str,
    tab_id: int = 0,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Click an element in a Chrome tab using a CSS selector.

    USE THIS to drive multi-step web flows: Doctolib (click "Prendre
    rendez-vous", pick a consultation reason, choose a slot), SNCF Connect,
    Booking, forms on .gouv.fr, any React/SPA where a button must be
    pressed before the next data is visible.

    Best practices:
        - First call browser_tab_read_html with a tight selector (e.g.
          "main", "[role=main]") and locate the button/link you want to
          click. Pick a selector specific enough to match a SINGLE
          element — class names with hash suffixes (.dl-button-primary,
          .btn-r2x9fp) often work better than generic [role=button].
        - The tool auto-picks the first VISIBLE match when several
          elements match (mobile/desktop dupes are common in React apps).
        - After click, ALWAYS call browser_tab_wait_for_selector for the
          NEXT page's expected element before reading — React rerenders
          asynchronously and a fast read_text right after click will
          return the OLD content.

    Args:
        selector: CSS selector of the element to click. Required.
        tab_id: the tab id from browser_list_tabs. Defaults to the active
            tab — usually NOT what you want (that's the ELY chat tab).

    Returns: confirmation + the matched element's tag + first 200 chars
        of its visible text, so you can sanity-check you clicked the
        right thing before continuing.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    if not selector:
        return "Erreur : selector requis."
    payload = {"selector": selector}
    if tab_id:
        payload["tab_id"] = tab_id
    res = await _send_and_wait(user_id, "click", payload)
    if not res.get("ok"):
        return (
            f"Erreur : {res.get('error', 'inconnue')}. "
            f"Détail : {res.get('detail', '')} {res.get('hint', '')}"
        )
    return (
        f"Clic exécuté sur '{selector}' (matched={res.get('matched', '?')}).\n"
        f"Élément : <{res.get('tag', '?')}> | Texte : {res.get('text', '')!r}\n"
        f"URL après clic : {res.get('url', '')}\n"
        "⚠️ Pour les SPA (React, Vue), appelle browser_tab_wait_for_selector "
        "avant de lire la page suivante : le rendu est asynchrone."
    )


@tool
async def browser_tab_fill(
    selector: str,
    value: str,
    tab_id: int = 0,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Fill an <input> or <textarea> with a given value.

    Handles React-controlled inputs correctly (uses the native setter +
    dispatches `input`/`change` events — a plain ``element.value = …``
    would be silently ignored by frameworks like React).

    Args:
        selector: CSS selector of the input/textarea. Must match exactly
            one element.
        value: text to type in.
        tab_id: target tab; defaults to the active tab.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    if not selector:
        return "Erreur : selector requis."
    payload = {"selector": selector, "value": value}
    if tab_id:
        payload["tab_id"] = tab_id
    res = await _send_and_wait(user_id, "fill", payload)
    if not res.get("ok"):
        return (
            f"Erreur : {res.get('error', 'inconnue')}. "
            f"Détail : {res.get('detail', '')} {res.get('hint', '')}"
        )
    return (
        f"Champ '{selector}' rempli avec {res.get('value_length', 0)} caractères."
    )


@tool
async def browser_tab_navigate(
    url: str,
    tab_id: int = 0,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Navigate an existing tab to a new URL.

    Prefer browser_open_tab when you want a fresh tab; use this only
    when you want to keep the same tab (e.g. multi-step flow where
    closing/reopening would reset auth state in the page's memory).

    Args:
        url: must start with http:// or https://.
        tab_id: target tab; defaults to active tab.
    """
    if not user_id:
        return "Erreur : user_id manquant."
    if not url:
        return "Erreur : url requise."
    payload = {"url": url}
    if tab_id:
        payload["tab_id"] = tab_id
    res = await _send_and_wait(user_id, "navigate", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    return (
        f"Navigation : {res.get('from', '')} → {res.get('navigated_to', url)}.\n"
        "Appelle ensuite browser_tab_wait_loaded puis "
        "browser_tab_wait_for_selector avant de lire le contenu."
    )


# ─────────────────────────────────────────────────────────────────────
# Sprint 0.7 — Chrome v2: history / bookmarks / downloads
# ─────────────────────────────────────────────────────────────────────
#
# These three tools are READ-ONLY and never write to the user's browser.
# Defence-in-depth privacy controls applied here (all server-side, the
# agent cannot bypass them):
#   1. Inputs are clamped:
#        - days_back  ∈ [1, 30]
#        - max_results ∈ [1, 20]
#   2. URLs are passed through `chrome_privacy_filter.filter_rows()`
#      which drops rows whose host matches the V2.0 hardcoded blacklist
#      (banking / health / adult / sensitive gov).
#   3. Result rows are formatted as compact text — no JSON dump that
#      could exfiltrate fields the LLM didn't ask for.
#
# Why we clamp INSIDE the tool instead of trusting the SW: the SW
# clamps too (cheap defence), but the cloud LLM provider only ever
# sees what the tool returns — so the authoritative clamp must live
# server-side, not in user-controlled JS.

_MAX_DAYS_BACK = 30
_MAX_RESULTS = 20


def _clamp(value, lo: int, hi: int, default: int) -> int:
    """Coerce value to int in [lo, hi]; fall back to default on garbage."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _format_ts(ms: float | int | None) -> str:
    """Format epoch-ms timestamp as a short ISO string. Empty if 0/None."""
    if not ms:
        return ""
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
    except (OSError, ValueError, OverflowError):
        return ""


@tool
async def browser_history_search(
    query: str = "",
    days_back: int = 7,
    max_results: int = 20,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search the user's Chrome visit history (READ-ONLY).

    Use this when the user asks "what did I read about X yesterday?",
    "give me my recent visits to GitHub", or "what was that article on
    LLM evals I saw last week?". Requires the ELY Chrome extension to
    be connected (extension/chrome/, Sprint 0.7).

    Privacy:
        Visits to banking, health, adult, and sensitive gov domains are
        filtered out server-side before the agent sees them, regardless
        of what the user asks. This is a hardcoded V2.0 list.

    Args:
        query: text search inside title/URL (empty = all recent visits).
        days_back: how far back to look. Clamped to [1, 30].
        max_results: cap on returned rows. Clamped to [1, 20].
    """
    if not user_id:
        return "Erreur : user_id manquant."
    days_back = _clamp(days_back, 1, _MAX_DAYS_BACK, 7)
    max_results = _clamp(max_results, 1, _MAX_RESULTS, 20)
    payload = {
        "query": query or "",
        "days_back": days_back,
        "max_results": max_results,
    }
    res = await _send_and_wait(user_id, "get_history", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    raw = res.get("items") or []
    items = _privacy_filter_rows(raw, url_key="url")
    if not items:
        if raw and not items:
            return (
                f"Aucun résultat publiable pour « {query} » sur les {days_back} "
                "derniers jours (visites filtrées par le garde-fou privacy : "
                "banking/santé/adulte/gov sensibles)."
            )
        return f"Aucune visite trouvée pour « {query} » sur les {days_back} derniers jours."
    lines = [
        f"{len(items)} visite(s) Chrome (≤ {days_back} jours, filtré privacy) :"
    ]
    for it in items:
        ts = _format_ts(it.get("last_visit_time"))
        vc = it.get("visit_count", 0)
        title = (it.get("title") or "").strip()[:90]
        lines.append(
            f"  - {ts}  ({vc}×) {title}\n      {it.get('url', '')}"
        )
    return "\n".join(lines)


@tool
async def browser_bookmarks_search(
    query: str = "",
    max_results: int = 20,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search the user's Chrome bookmarks (READ-ONLY).

    Use this when the user asks "find me that React tutorial I bookmarked",
    "what's in my Recettes folder?", or "list my dev bookmarks". An empty
    query returns the first `max_results` bookmarks of the full tree.

    Privacy:
        Bookmarks on banking, health, adult, and sensitive gov domains
        are filtered out server-side.

    Args:
        query: text search inside title or URL (empty = full bookmark list).
        max_results: cap on returned rows. Clamped to [1, 20].
    """
    if not user_id:
        return "Erreur : user_id manquant."
    max_results = _clamp(max_results, 1, _MAX_RESULTS, 20)
    payload = {"query": query or ""}
    res = await _send_and_wait(user_id, "get_bookmarks", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    raw = res.get("items") or []
    items = _privacy_filter_rows(raw, url_key="url")
    # Drop folder-only entries (no url) when no query — keeps the output
    # focused on actionable bookmarks. With a query, chrome.bookmarks.search
    # already returns only matching leaves.
    items = [it for it in items if it.get("url")]
    items = items[:max_results]
    if not items:
        return f"Aucun signet trouvé pour « {query} »."
    lines = [f"{len(items)} signet(s) Chrome :"]
    for it in items:
        title = (it.get("title") or "").strip()[:90]
        folder = it.get("folder_path", "")
        folder_hint = f"  [{folder.strip('/')}]" if folder and folder != "/" else ""
        lines.append(f"  - {title}{folder_hint}\n      {it.get('url', '')}")
    return "\n".join(lines)


@tool
async def browser_downloads_search(
    query: str = "",
    state: str = "",
    max_results: int = 20,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List the user's recent Chrome downloads (READ-ONLY).

    Use this when the user asks "what did I download yesterday?", "find
    my Excel files in downloads", or "show me my recent PDFs". By default
    returns the most recent downloads first.

    Privacy:
        Downloads from banking, health, adult, and sensitive gov domains
        are filtered out server-side (URL of the source page is checked,
        not the local filename — sensitive content lands in the same
        bucket regardless of where the file lives on disk).

    Args:
        query: text search inside filename/URL (empty = all recent).
        state: filter by state — "" (any), "in_progress", "interrupted",
            or "complete".
        max_results: cap on returned rows. Clamped to [1, 20].
    """
    if not user_id:
        return "Erreur : user_id manquant."
    max_results = _clamp(max_results, 1, _MAX_RESULTS, 20)
    payload: dict = {"query": query or "", "max_results": max_results}
    if state in {"in_progress", "interrupted", "complete"}:
        payload["state"] = state
    res = await _send_and_wait(user_id, "get_downloads", payload)
    if not res.get("ok"):
        return f"Erreur : {res.get('error', 'inconnue')}. {res.get('hint', '')}"
    raw = res.get("items") or []
    # We check BOTH the source URL and the final URL — a redirect can
    # bounce off a non-blacklisted host but still originate sensitive
    # content. Either match drops the row.
    items: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        from app.services.chrome_privacy_filter import is_blacklisted_url
        if is_blacklisted_url(row.get("url")) or is_blacklisted_url(row.get("final_url")):
            continue
        items.append(row)
    items = items[:max_results]
    if not items:
        return f"Aucun téléchargement trouvé pour « {query} »."
    lines = [f"{len(items)} téléchargement(s) Chrome (filtré privacy) :"]
    for it in items:
        ts = _format_ts(_parse_iso_to_ms(it.get("start_time", "")))
        fname = (it.get("filename") or "").split("/")[-1][:80]
        size = it.get("total_bytes") or it.get("bytes_received") or 0
        size_hint = f" ({_human_size(size)})" if size else ""
        st = it.get("state", "")
        lines.append(
            f"  - {ts}  [{st}] {fname}{size_hint}\n      {it.get('url', '')}"
        )
    return "\n".join(lines)


def _parse_iso_to_ms(iso: str) -> int:
    """Best-effort ISO-8601 → epoch ms. Returns 0 on parse failure."""
    if not iso:
        return 0
    try:
        from datetime import datetime
        # chrome.downloads.search returns ISO with a trailing "Z" or offset.
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _human_size(n: int) -> str:
    """Pretty byte size, e.g. 12.3 MB. Keep tight, the agent quotes verbatim."""
    if n < 1024:
        return f"{n} B"
    units = ("KB", "MB", "GB", "TB")
    v = float(n) / 1024.0
    for u in units:
        if v < 1024:
            return f"{v:.1f} {u}"
        v /= 1024
    return f"{v:.1f} PB"


BROWSER_EXTENSION_TOOLS = [
    browser_list_tabs,
    browser_open_tab,
    browser_tab_wait_loaded,
    browser_tab_wait_for_selector,
    browser_tab_get_url,
    browser_tab_read_text,
    browser_tab_read_html,
    browser_tab_screenshot,
    browser_tab_click,
    browser_tab_fill,
    browser_tab_navigate,
    browser_close_tab,
    # Sprint 0.7 — Chrome v2 read-only inspectors
    browser_history_search,
    browser_bookmarks_search,
    browser_downloads_search,
]
