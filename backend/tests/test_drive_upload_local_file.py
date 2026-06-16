# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_drive_upload_local_file.py
# @brief      Tests du tool drive_upload_local_file (téléversement d'un fichier
#             LOCAL/binaire vers Drive — ex. une capture d'écran PNG).
# =============================================================================
"""drive_upload_local_file : téléverse un fichier local binaire vers Drive.

Comble le trou de capacité « impossible d'enregistrer un PNG sur Drive » :
drive_create_file n'écrit que du texte (content.encode utf-8). Ce tool lit les
octets bruts d'un fichier local (chemin retourné par browser_screenshot /
browser_tab_screenshot) et l'envoie via MediaFileUpload.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.agent.tools import drive_tool
from app.agent.tools.drive_tool import (
    _assert_upload_path_allowed,
    drive_upload_local_file,
)


# ── Fakes Drive service ──────────────────────────────────────────────────────
class _FakeExec:
    def __init__(self, result: dict) -> None:
        self._r = result

    def execute(self) -> dict:
        return self._r


class _FakeFiles:
    def __init__(self, recorder: dict) -> None:
        self.recorder = recorder

    def create(self, body=None, media_body=None, fields=None):
        self.recorder["body"] = body
        self.recorder["media_body"] = media_body
        self.recorder["fields"] = fields
        return _FakeExec(
            {"id": "FILE123", "name": body["name"], "webViewLink": "https://drive/x"}
        )


class _FakeService:
    def __init__(self, recorder: dict) -> None:
        self.recorder = recorder

    def files(self):
        return _FakeFiles(self.recorder)


def _mock_service(monkeypatch, recorder: dict) -> None:
    async def _fake_get_service(_creds):
        return _FakeService(recorder)

    monkeypatch.setattr(drive_tool, "_get_drive_service", _fake_get_service)


def _tmp_file(content: bytes = b"\x89PNG\r\n\x1a\n", suffix: str = ".png") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


# ── Validation de chemin ─────────────────────────────────────────────────────
def test_path_validation_accepts_tmpfile():
    path = _tmp_file()
    try:
        resolved = _assert_upload_path_allowed(path)
        assert str(resolved).endswith(".png")
    finally:
        os.unlink(path)


def test_path_validation_rejects_outside_allowlist():
    with pytest.raises(PermissionError):
        _assert_upload_path_allowed("/etc/passwd")


def test_path_validation_rejects_traversal():
    with pytest.raises(PermissionError):
        _assert_upload_path_allowed("/tmp/../etc/shadow")


# ── Garde-fous du tool ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_empty_path_errors():
    out = await drive_upload_local_file.ainvoke({"local_path": ""})
    assert "vide" in out.lower()


@pytest.mark.asyncio
async def test_outside_allowlist_refused():
    out = await drive_upload_local_file.ainvoke({"local_path": "/etc/passwd"})
    assert "refusé" in out.lower() or "refus" in out.lower()


@pytest.mark.asyncio
async def test_missing_file_errors():
    out = await drive_upload_local_file.ainvoke(
        {"local_path": os.path.join(tempfile.gettempdir(), "nope-does-not-exist.png")}
    )
    assert "introuvable" in out.lower()


@pytest.mark.asyncio
async def test_zero_byte_file_errors():
    path = _tmp_file(content=b"")
    try:
        out = await drive_upload_local_file.ainvoke({"local_path": path})
        assert "vide" in out.lower() and "octet" in out.lower()
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_oversized_file_errors(monkeypatch):
    monkeypatch.setattr(drive_tool, "_UPLOAD_MAX_SIZE", 4)
    path = _tmp_file(content=b"0123456789")  # 10 octets > 4
    try:
        out = await drive_upload_local_file.ainvoke({"local_path": path})
        assert "volumineux" in out.lower()
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_not_connected_returns_clean_message(monkeypatch):
    async def _none(_creds):
        return None

    monkeypatch.setattr(drive_tool, "_get_drive_service", _none)
    path = _tmp_file()
    try:
        out = await drive_upload_local_file.ainvoke({"local_path": path})
        assert "Google non connecté" in out
    finally:
        os.unlink(path)


# ── Chemin nominal ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_successful_upload_returns_link(monkeypatch):
    recorder: dict = {}
    _mock_service(monkeypatch, recorder)
    path = _tmp_file(suffix=".png")
    try:
        out = await drive_upload_local_file.ainvoke(
            {
                "local_path": path,
                "name": "capture.png",
                "user_google_credentials_json": "creds",
            }
        )
        assert "téléversé" in out.lower()
        assert "https://drive/x" in out
        assert recorder["body"]["name"] == "capture.png"
        # mime auto-déduit du .png
        assert recorder["media_body"].mimetype() == "image/png"
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_default_name_is_file_basename(monkeypatch):
    recorder: dict = {}
    _mock_service(monkeypatch, recorder)
    path = _tmp_file(suffix=".png")
    try:
        await drive_upload_local_file.ainvoke(
            {"local_path": path, "user_google_credentials_json": "creds"}
        )
        assert recorder["body"]["name"] == os.path.basename(path)
        # pas de parent_id → pas de clé "parents"
        assert "parents" not in recorder["body"]
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_parent_id_sets_parents(monkeypatch):
    recorder: dict = {}
    _mock_service(monkeypatch, recorder)
    path = _tmp_file(suffix=".png")
    try:
        await drive_upload_local_file.ainvoke(
            {
                "local_path": path,
                "parent_id": "FOLDER42",
                "user_google_credentials_json": "creds",
            }
        )
        assert recorder["body"]["parents"] == ["FOLDER42"]
    finally:
        os.unlink(path)
