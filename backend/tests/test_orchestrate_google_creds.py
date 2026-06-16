# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_google_creds.py
# @brief      Régression : injection des credentials Google dans le dispatcher
#             orchestrate (bug « Google non connecté » dans le sandbox).
# =============================================================================
"""Le dispatcher par défaut d'``orchestrate`` doit injecter les credentials
Google (``user_google_credentials_json``) pour les tools Google de
``GOOGLE_TOOLS`` — sinon ``drive_list_files`` / ``gmail_list_emails`` /
``calendar_list_events`` retournent « Google non connecté » à l'intérieur du
sandbox alors que l'utilisateur EST connecté.

Bug surfacé par GPT-5.5 qui privilégie ``orchestrate`` pour les recherches
Drive multi-requêtes (juin 2026).
"""
from __future__ import annotations

import pytest

from app.services import orchestrate_runner as mod
from app.services.orchestrate_runner import _build_default_dispatcher


class _FakeTool:
    """Stub minimal d'un @tool LangChain : enregistre les args reçus."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.received: dict | None = None

    async def ainvoke(self, args: dict):
        self.received = dict(args)
        return f"called {self.name}"


class _FakeRegistry:
    def __init__(self, tools: list[_FakeTool]) -> None:
        self.all_tools = tools


def _patch_registry(monkeypatch, tools: list[_FakeTool]) -> None:
    # ``_build_default_dispatcher`` importe ces noms à l'exécution depuis
    # ``app.skills`` / ``app.skills.builtin`` → on patche là.
    monkeypatch.setattr("app.skills.builtin.register_all", lambda: None)
    monkeypatch.setattr(
        "app.skills.get_skill_registry", lambda: _FakeRegistry(tools)
    )


@pytest.mark.asyncio
async def test_dispatcher_injects_google_credentials_for_google_tools(monkeypatch):
    drive = _FakeTool("drive_list_files")  # ∈ GOOGLE_TOOLS
    _patch_registry(monkeypatch, [drive])

    dispatch = _build_default_dispatcher("user-123", "CREDS_JSON")
    await dispatch("drive_list_files", {"query": "rapport"})

    assert drive.received is not None
    assert drive.received["user_google_credentials_json"] == "CREDS_JSON"
    assert drive.received["user_id"] == "user-123"
    assert drive.received["query"] == "rapport"


@pytest.mark.asyncio
async def test_dispatcher_does_not_inject_credentials_for_non_google_tools(monkeypatch):
    web = _FakeTool("web_search")  # ∉ GOOGLE_TOOLS
    _patch_registry(monkeypatch, [web])

    dispatch = _build_default_dispatcher("user-123", "CREDS_JSON")
    await dispatch("web_search", {"q": "x"})

    assert web.received is not None
    assert "user_google_credentials_json" not in web.received
    assert web.received["user_id"] == "user-123"


@pytest.mark.asyncio
async def test_dispatcher_injects_empty_string_when_not_connected(monkeypatch):
    """Pas de creds résolus → on injecte "" : le tool répond « non connecté »
    proprement, exactement comme le chemin normal."""
    gmail = _FakeTool("gmail_list_emails")  # ∈ GOOGLE_TOOLS
    _patch_registry(monkeypatch, [gmail])

    dispatch = _build_default_dispatcher("user-123", "")
    await dispatch("gmail_list_emails", {})

    assert gmail.received is not None
    assert gmail.received["user_google_credentials_json"] == ""


@pytest.mark.asyncio
async def test_dispatcher_raises_on_unknown_tool(monkeypatch):
    _patch_registry(monkeypatch, [])
    dispatch = _build_default_dispatcher("user-123", "CREDS_JSON")
    with pytest.raises(LookupError):
        await dispatch("does_not_exist", {})


@pytest.mark.asyncio
async def test_resolve_credentials_uses_store_fast_path(monkeypatch):
    class _Store:
        def get(self, uid):
            return "STORE_CREDS"

        def set(self, uid, value):
            pass

    monkeypatch.setattr(
        "app.services.credential_store.get_credential_store", lambda: _Store()
    )
    creds = await mod._resolve_default_google_credentials("user-1")
    assert creds == "STORE_CREDS"


@pytest.mark.asyncio
async def test_resolve_credentials_empty_user_returns_empty():
    assert await mod._resolve_default_google_credentials("") == ""
