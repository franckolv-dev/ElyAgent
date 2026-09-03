# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_drive_create_folder_idempotent.py
# @brief      2026-06-04 — drive_create_folder must reuse an existing same-name
#             folder instead of creating a duplicate (recurring-mission bug).
# @license    MIT
# =============================================================================
"""Tests for drive_create_folder idempotence (Franck, 2026-06-03).

A recurring invoice mission re-created its monthly "06_2026" folder on
every run because Drive allows multiple same-name folders in a parent.
The tool now searches first and reuses an existing one. The Drive service
is faked (no real Google call); the tool's async impl is invoked directly.
"""
from __future__ import annotations

import pytest

from app.agent.tools import drive_tool


class _Exec:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _FakeFiles:
    def __init__(self, existing):
        self._existing = existing
        self.create_calls: list[dict] = []
        self.last_query: str | None = None

    def list(self, **kwargs):
        self.last_query = kwargs.get("q")
        return _Exec({"files": self._existing})

    def create(self, **kwargs):
        body = kwargs.get("body", {})
        self.create_calls.append(body)
        return _Exec({"id": "new-folder-id", "name": body.get("name"), "webViewLink": "http://x"})


class _FakeService:
    def __init__(self, existing):
        self._files = _FakeFiles(existing)

    def files(self):
        return self._files


def _patch_service(monkeypatch, existing):
    svc = _FakeService(existing)

    async def _fake_get_service(_creds):
        return svc

    monkeypatch.setattr(drive_tool, "_get_drive_service", _fake_get_service)
    return svc


async def _call(**kwargs):
    # async @tool → invoke its underlying coroutine directly
    return await drive_tool.drive_create_folder.coroutine(**kwargs)


@pytest.mark.asyncio
async def test_creates_when_no_existing_folder(monkeypatch):
    svc = _patch_service(monkeypatch, existing=[])
    out = await _call(name="06_2026", parent_id="PARENT", user_google_credentials_json="x")
    assert "Dossier créé" in out
    assert len(svc.files().create_calls) == 1  # actually created


@pytest.mark.asyncio
async def test_reuses_existing_folder_no_duplicate(monkeypatch):
    svc = _patch_service(
        monkeypatch,
        existing=[{"id": "f1", "name": "06_2026", "webViewLink": "http://drive/f1"}],
    )
    out = await _call(name="06_2026", parent_id="PARENT", user_google_credentials_json="x")
    assert "réutilisé" in out
    assert "f1" in out
    # crucially: NO create call → no duplicate folder
    assert svc.files().create_calls == []


@pytest.mark.asyncio
async def test_query_scopes_to_parent_name_and_not_trashed(monkeypatch):
    svc = _patch_service(monkeypatch, existing=[])
    await _call(name="06_2026", parent_id="PARENT", user_google_credentials_json="x")
    q = svc.files().last_query
    assert "name = '06_2026'" in q
    assert "trashed = false" in q
    assert "'PARENT' in parents" in q
    assert "application/vnd.google-apps.folder" in q


@pytest.mark.asyncio
async def test_query_uses_root_when_no_parent(monkeypatch):
    svc = _patch_service(monkeypatch, existing=[])
    await _call(name="Factures", user_google_credentials_json="x")
    assert "'root' in parents" in svc.files().last_query


@pytest.mark.asyncio
async def test_apostrophe_in_name_is_escaped(monkeypatch):
    svc = _patch_service(monkeypatch, existing=[])
    await _call(name="Jean's docs", parent_id="P", user_google_credentials_json="x")
    # the single quote must be escaped so the Drive query stays valid
    assert r"name = 'Jean\'s docs'" in svc.files().last_query
