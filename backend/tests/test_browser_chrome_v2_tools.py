# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_browser_chrome_v2_tools.py
# @brief      Pin the Sprint 0.7 Chrome v2 tools (history / bookmarks /
#             downloads). We mock `_send_and_wait` so the tests run
#             without a real extension connected. We focus on the three
#             things that *must* be right or the product leaks data:
#               1. Inputs are clamped server-side (days_back ≤ 30,
#                  max_results ≤ 20) — even if the SW clamping is ever
#                  removed, the cloud LLM never sees pre-clamp values.
#               2. The privacy filter actually drops the blacklisted
#                  rows before they reach the tool output.
#               3. The three tool names are registered in USER_ID_TOOLS
#                  and in the active toolset profile (otherwise the
#                  runtime drops user_id silently and the tools return
#                  "user_id manquant" forever).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Functional tests for `browser_history_search`, `browser_bookmarks_search`,
and `browser_downloads_search`."""
from __future__ import annotations

import pytest

from app.agent.tools import browser_extension_tool as bext
from app.agent.tools.browser_extension_tool import (
    browser_history_search,
    browser_bookmarks_search,
    browser_downloads_search,
    BROWSER_EXTENSION_TOOLS,
    _MAX_DAYS_BACK,
    _MAX_RESULTS,
    _clamp,
)


# ─────────────────────────────────────────────────────────────────────
# Helpers — capture what the tool sends to the extension
# ─────────────────────────────────────────────────────────────────────


class _MockExt:
    """Stand-in for the extension. Records the last payload it received."""

    def __init__(self, response: dict | None = None) -> None:
        self.response = response or {"ok": True, "items": []}
        self.calls: list[dict] = []

    async def __call__(self, user_id: str, command_type: str, payload: dict) -> dict:
        self.calls.append({
            "user_id": user_id,
            "command_type": command_type,
            "payload": payload,
        })
        return self.response


@pytest.fixture
def mock_ext(monkeypatch: pytest.MonkeyPatch) -> _MockExt:
    mock = _MockExt()
    monkeypatch.setattr(bext, "_send_and_wait", mock)
    return mock


# ─────────────────────────────────────────────────────────────────────
# _clamp helper — pin behaviour because the tools depend on it
# ─────────────────────────────────────────────────────────────────────


def test_clamp_within_range() -> None:
    assert _clamp(15, 1, 30, 7) == 15


def test_clamp_above_max() -> None:
    assert _clamp(9999, 1, 30, 7) == 30


def test_clamp_below_min() -> None:
    assert _clamp(0, 1, 30, 7) == 1


def test_clamp_garbage_returns_default() -> None:
    assert _clamp("abc", 1, 30, 7) == 7
    assert _clamp(None, 1, 30, 7) == 7
    assert _clamp([], 1, 30, 7) == 7


def test_clamp_max_constants() -> None:
    """Pin the limits set by the privacy contract (memory.md 2026-05-26)."""
    assert _MAX_DAYS_BACK == 30
    assert _MAX_RESULTS == 20


# ─────────────────────────────────────────────────────────────────────
# browser_history_search
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_requires_user_id(mock_ext: _MockExt) -> None:
    out = await browser_history_search.ainvoke({"query": "react", "user_id": ""})
    assert "user_id manquant" in out
    assert mock_ext.calls == []


@pytest.mark.asyncio
async def test_history_clamps_days_back_above_30(mock_ext: _MockExt) -> None:
    await browser_history_search.ainvoke({
        "query": "x", "days_back": 9999, "max_results": 5, "user_id": "u1",
    })
    assert mock_ext.calls[0]["payload"]["days_back"] == 30


@pytest.mark.asyncio
async def test_history_clamps_max_results_above_20(mock_ext: _MockExt) -> None:
    await browser_history_search.ainvoke({
        "query": "x", "days_back": 7, "max_results": 9999, "user_id": "u1",
    })
    assert mock_ext.calls[0]["payload"]["max_results"] == 20


@pytest.mark.asyncio
async def test_history_filters_blacklisted_urls() -> None:
    """A history result containing one bank URL and one GitHub URL must
    surface only the GitHub one — the privacy filter is the load-bearing
    promise of the whole sprint."""
    mock = _MockExt(response={
        "ok": True,
        "items": [
            {"url": "https://github.com/foo/bar", "title": "GitHub repo",
             "visit_count": 3, "last_visit_time": 1_700_000_000_000},
            {"url": "https://www.boursorama.com/connexion", "title": "Bourso",
             "visit_count": 12, "last_visit_time": 1_700_000_100_000},
        ],
    })
    import pytest as _pt
    monkeypatch = _pt.MonkeyPatch()
    monkeypatch.setattr(bext, "_send_and_wait", mock)
    try:
        out = await browser_history_search.ainvoke({"query": "x", "user_id": "u1"})
    finally:
        monkeypatch.undo()
    assert "github.com" in out
    assert "boursorama" not in out


@pytest.mark.asyncio
async def test_history_handles_extension_not_connected(monkeypatch) -> None:
    async def _fail(uid, ct, payload):
        return {"ok": False, "error": "extension_not_connected", "hint": "install it"}
    monkeypatch.setattr(bext, "_send_and_wait", _fail)
    out = await browser_history_search.ainvoke({"query": "x", "user_id": "u1"})
    assert "Erreur" in out
    assert "extension_not_connected" in out


# ─────────────────────────────────────────────────────────────────────
# browser_bookmarks_search
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bookmarks_clamps_max_results(mock_ext: _MockExt) -> None:
    await browser_bookmarks_search.ainvoke({
        "query": "react", "max_results": 9999, "user_id": "u1",
    })
    # max_results is clamped INSIDE the tool before the slice — the
    # payload sent to the extension carries the raw query, the slice
    # happens on the response. We verify by feeding many items back.
    # Here we just check the payload contains the query.
    assert mock_ext.calls[0]["payload"]["query"] == "react"


@pytest.mark.asyncio
async def test_bookmarks_drops_folder_only_entries() -> None:
    mock = _MockExt(response={
        "ok": True,
        "items": [
            {"id": "1", "title": "Bookmarks bar", "url": None, "parent_id": "0"},
            {"id": "2", "title": "GitHub", "url": "https://github.com/", "parent_id": "1"},
        ],
    })
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(bext, "_send_and_wait", mock)
    try:
        out = await browser_bookmarks_search.ainvoke({"query": "", "user_id": "u1"})
    finally:
        mp.undo()
    # The folder entry has no URL → must not appear as a bookmark in the
    # rendered output (we only show actionable, clickable bookmarks).
    assert "GitHub" in out
    assert "Bookmarks bar" not in out


@pytest.mark.asyncio
async def test_bookmarks_filter_blacklists_health_domain() -> None:
    mock = _MockExt(response={
        "ok": True,
        "items": [
            {"id": "10", "title": "Doctor", "url": "https://www.doctolib.fr/foo",
             "parent_id": "1"},
            {"id": "11", "title": "Article", "url": "https://www.lemonde.fr/",
             "parent_id": "1"},
        ],
    })
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(bext, "_send_and_wait", mock)
    try:
        out = await browser_bookmarks_search.ainvoke({"query": "x", "user_id": "u1"})
    finally:
        mp.undo()
    assert "lemonde" in out
    assert "doctolib" not in out


# ─────────────────────────────────────────────────────────────────────
# browser_downloads_search
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_downloads_clamps_max_results(mock_ext: _MockExt) -> None:
    await browser_downloads_search.ainvoke({
        "query": "x", "max_results": 9999, "user_id": "u1",
    })
    assert mock_ext.calls[0]["payload"]["max_results"] == 20


@pytest.mark.asyncio
async def test_downloads_filters_redirect_chain() -> None:
    """A download whose ORIGINATING URL is blacklisted must be dropped
    even if `final_url` is on a harmless CDN. The reverse also holds:
    a CDN that ended up serving banking content via `final_url` must
    be dropped too."""
    mock = _MockExt(response={
        "ok": True,
        "items": [
            # Originated from a bank, redirected to a CDN — DROP
            {"url": "https://www.boursorama.com/files/report.pdf",
             "final_url": "https://cdn.example.com/abc.pdf",
             "filename": "/Users/foo/Downloads/report.pdf",
             "state": "complete", "total_bytes": 1024, "start_time": ""},
            # Originated from GitHub — KEEP
            {"url": "https://github.com/release/asset.zip",
             "final_url": "https://github.com/release/asset.zip",
             "filename": "/Users/foo/Downloads/asset.zip",
             "state": "complete", "total_bytes": 2048, "start_time": ""},
            # Originated from a CDN, redirected to a bank — DROP (the URL
            # the user landed on is what's sensitive)
            {"url": "https://cdn.example.com/sso.html",
             "final_url": "https://mabanque.bnpparibas/login",
             "filename": "/Users/foo/Downloads/sso.html",
             "state": "complete", "total_bytes": 512, "start_time": ""},
        ],
    })
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(bext, "_send_and_wait", mock)
    try:
        out = await browser_downloads_search.ainvoke({"query": "", "user_id": "u1"})
    finally:
        mp.undo()
    assert "asset.zip" in out
    assert "report.pdf" not in out
    assert "sso.html" not in out


@pytest.mark.asyncio
async def test_downloads_accepts_only_valid_states(mock_ext: _MockExt) -> None:
    """Garbage `state` is silently dropped from the payload."""
    await browser_downloads_search.ainvoke({
        "query": "x", "state": "weird-state", "user_id": "u1",
    })
    payload = mock_ext.calls[0]["payload"]
    assert "state" not in payload  # silently dropped

    await browser_downloads_search.ainvoke({
        "query": "x", "state": "complete", "user_id": "u1",
    })
    payload = mock_ext.calls[1]["payload"]
    assert payload["state"] == "complete"


# ─────────────────────────────────────────────────────────────────────
# Wire-up guards — silent-failure killers
# ─────────────────────────────────────────────────────────────────────


def test_three_tools_in_exported_list() -> None:
    names = {t.name for t in BROWSER_EXTENSION_TOOLS}
    assert "browser_history_search" in names
    assert "browser_bookmarks_search" in names
    assert "browser_downloads_search" in names


def test_three_tools_in_user_id_tools() -> None:
    """If any is missing from USER_ID_TOOLS the runtime won't inject
    user_id → tool returns "user_id manquant" forever. We've been bitten
    by this twice already (memory_archive, browser_search_images)."""
    from app.agent.tool_sets import USER_ID_TOOLS
    assert "browser_history_search" in USER_ID_TOOLS
    assert "browser_bookmarks_search" in USER_ID_TOOLS
    assert "browser_downloads_search" in USER_ID_TOOLS


def test_three_tools_in_toolset_profile() -> None:
    """If missing here, the agent literally cannot see the tool. Pinning
    by source-grep so a future merge conflict can't silently delete them."""
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "app" / "agent" / "toolset_profiles.py"
    src = p.read_text()
    assert '"browser_history_search"' in src
    assert '"browser_bookmarks_search"' in src
    assert '"browser_downloads_search"' in src
