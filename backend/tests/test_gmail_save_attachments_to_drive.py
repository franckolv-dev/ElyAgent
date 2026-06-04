# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_gmail_save_attachments_to_drive.py
# @brief      2026-06-04 — gmail_save_attachments_to_drive: download a message's
#             attachments and upload them (binary) to a Drive folder.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for the new attachment→Drive tool (Franck's invoice mission needed it:
there was no path from a Gmail attachment to a binary file on Drive —
drive_create_file is text-only). Gmail + Drive services are faked.
"""
from __future__ import annotations

import base64

import pytest

from app.agent.tools import drive_tool, gmail_tool


# ── fakes ──────────────────────────────────────────────────────────────────────


class _Exec:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _Attachments:
    def __init__(self, data_map):
        self._data_map = data_map

    def get(self, userId, messageId, id):  # noqa: A002,N803
        raw = self._data_map[id]
        return _Exec({"data": base64.urlsafe_b64encode(raw).decode()})


class _Messages:
    def __init__(self, message, data_map):
        self._message = message
        self._att = _Attachments(data_map)

    def get(self, userId, id, format):  # noqa: A002,N803
        return _Exec(self._message)

    def attachments(self):
        return self._att


class _FakeGmail:
    def __init__(self, message, data_map):
        self._messages = _Messages(message, data_map)

    def users(self):
        return self

    def messages(self):
        return self._messages


class _DFiles:
    def __init__(self, existing):
        self._existing = list(existing)
        self.created: list[str] = []

    def list(self, **kwargs):
        return _Exec({"files": [{"name": n} for n in self._existing]})

    def create(self, body, media_body, fields):  # noqa: ARG002
        self.created.append(body["name"])
        return _Exec({"id": "id-" + body["name"], "name": body["name"]})


class _FakeDrive:
    def __init__(self, existing):
        self._files = _DFiles(existing)

    def files(self):
        return self._files


_MESSAGE = {
    "payload": {
        "parts": [
            {"filename": "facture1.pdf", "mimeType": "application/pdf",
             "body": {"attachmentId": "att1"}},
            {"filename": "", "mimeType": "text/plain", "body": {"data": "aGVsbG8="}},
            {"filename": "logo.png", "mimeType": "image/png",
             "body": {"attachmentId": "att2"}},
        ]
    }
}
_DATA = {"att1": b"%PDF-1.4 fake", "att2": b"\x89PNG fake"}


def _patch(monkeypatch, *, gmail=True, drive_existing=()):
    fake_drive = _FakeDrive(drive_existing)

    async def _fake_gmail_getter(_creds):
        return _FakeGmail(_MESSAGE, _DATA) if gmail else None

    async def _fake_drive_getter(_creds):
        return fake_drive

    monkeypatch.setattr(gmail_tool, "_get_gmail_service", _fake_gmail_getter)
    monkeypatch.setattr(drive_tool, "_get_drive_service", _fake_drive_getter)
    return fake_drive


async def _call(**kwargs):
    kwargs.setdefault("user_google_credentials_json", "x")
    return await gmail_tool.gmail_save_attachments_to_drive.coroutine(**kwargs)


# ── tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_saves_all_attachments(monkeypatch):
    drive = _patch(monkeypatch)
    out = await _call(message_id="m1", drive_folder_id="F")
    assert "Enregistrées (2)" in out
    assert set(drive.files().created) == {"facture1.pdf", "logo.png"}


@pytest.mark.asyncio
async def test_skips_already_present(monkeypatch):
    drive = _patch(monkeypatch, drive_existing=["facture1.pdf"])
    out = await _call(message_id="m1", drive_folder_id="F")
    assert "Déjà présentes" in out and "facture1.pdf" in out
    # only the new one is actually uploaded → no duplicate
    assert drive.files().created == ["logo.png"]


@pytest.mark.asyncio
async def test_filename_filter(monkeypatch):
    drive = _patch(monkeypatch)
    out = await _call(message_id="m1", drive_folder_id="F", filename_filter=".pdf")
    assert drive.files().created == ["facture1.pdf"]
    assert "logo.png" not in out


@pytest.mark.asyncio
async def test_no_attachments(monkeypatch):
    monkeypatch.setattr(gmail_tool, "_get_gmail_service",
                        lambda _c: _async_value(_FakeGmail({"payload": {"parts": []}}, {})))
    monkeypatch.setattr(drive_tool, "_get_drive_service",
                        lambda _c: _async_value(_FakeDrive([])))
    out = await _call(message_id="m1", drive_folder_id="F")
    assert "Aucune pièce jointe" in out


@pytest.mark.asyncio
async def test_google_not_connected(monkeypatch):
    _patch(monkeypatch, gmail=False)
    out = await _call(message_id="m1", drive_folder_id="F")
    assert "non connecté" in out.lower()


async def _async_value(v):
    return v
