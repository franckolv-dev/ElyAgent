"""Exercise the Desktop v1 list_dir protocol and the complete folder scan."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.watched_folder import WatchedFolder
from app.services import auto_indexer as indexer
from app.services.desktop_registry import DesktopCommandError


@pytest.mark.asyncio
@pytest.mark.parametrize("recursive", [False, True])
async def test_walk_uses_typed_entries_and_absolute_paths(monkeypatch, recursive):
    responses = {
        "/docs": {"entries": [
            {"name": "projet.md", "type": "file"},
            {"name": "archive", "type": "dir"},
            {"name": "node_modules", "type": "dir"},
            {"name": "outside", "type": "symlink"},
        ]},
        "/docs/archive": {"entries": [{"name": "dépenses.csv", "type": "file"}]},
    }

    async def send(uid, command, args):
        assert uid == "owner"
        assert command == "list_dir"
        return responses[args["path"]]

    mocked = AsyncMock(side_effect=send)
    monkeypatch.setattr(indexer.desktop_registry, "send_command", mocked)
    found = await indexer._daemon_walk("owner", "/docs", recursive, ["node_modules"])
    assert found == (["/docs/projet.md", "/docs/archive/dépenses.csv"]
                     if recursive else ["/docs/projet.md"])
    assert mocked.await_count == (2 if recursive else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("entries", [[], None])
async def test_empty_directory_is_valid(monkeypatch, entries):
    monkeypatch.setattr(indexer.desktop_registry, "send_command",
                        AsyncMock(return_value={"entries": entries}))
    assert await indexer._daemon_walk("owner", "/empty", True) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"entries": "bad"},
    {"entries": [None]}, {"entries": [{"name": "../secret", "type": "file"}]},
    {"entries": [{"name": "/secret", "type": "file"}]}])
async def test_invalid_listing_is_not_reported_as_an_empty_success(monkeypatch, response):
    monkeypatch.setattr(indexer.desktop_registry, "send_command",
                        AsyncMock(return_value=response))
    with pytest.raises(ValueError, match="invalide"):
        await indexer._daemon_walk("owner", "/docs", True)


@pytest.mark.asyncio
async def test_windows_paths_are_not_joined_with_linux_separators(monkeypatch):
    send = AsyncMock(side_effect=[
        {"entries": [{"name": "nested", "type": "dir"}]},
        {"entries": [{"name": "test.md", "type": "file"}]},
    ])
    monkeypatch.setattr(indexer.desktop_registry, "send_command", send)
    assert await indexer._daemon_walk("owner", r"C:\Docs", True) == [
        r"C:\Docs\nested\test.md"]
    assert send.call_args.args[2] == {"path": r"C:\Docs\nested"}


@pytest.mark.asyncio
async def test_excessive_directory_walk_reports_limit(monkeypatch):
    monkeypatch.setattr(indexer, "_MAX_DIRECTORIES_PER_SCAN", 1)
    monkeypatch.setattr(indexer.desktop_registry, "send_command", AsyncMock(
        return_value={"entries": [{"name": "nested", "type": "dir"}]}))
    with pytest.raises(ValueError, match="Trop de sous-dossiers"):
        await indexer._daemon_walk("owner", "/docs", True)


@pytest_asyncio.fixture
async def scan_env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(WatchedFolder.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(indexer, "async_session", sessions)
    monkeypatch.setattr(indexer, "_mode_de_lecture", lambda *_: "daemon")
    async with sessions() as db:
        folder = WatchedFolder(user_id="owner", path="/docs")
        db.add(folder)
        await db.commit()
        folder_id = folder.id
    documents = []
    contents = {}

    async def ingest(**kwargs):
        assert kwargs["user_id"] == "owner"
        contents[kwargs["source_file"]] = kwargs["file_path"].read_bytes()
        documents.append({"source_file": kwargs["source_file"]})
        return {"status": "ingested", "chunk_count": 1}

    rag = SimpleNamespace(list_documents=AsyncMock(return_value=documents),
                          ingest_document=AsyncMock(side_effect=ingest))
    monkeypatch.setattr(indexer, "get_rag_service", lambda: rag)
    try:
        yield SimpleNamespace(id=folder_id, sessions=sessions, rag=rag,
                              documents=documents, contents=contents)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_scan_reads_three_files_and_next_scan_deduplicates(monkeypatch, scan_env):
    files = {"projet.md": "# Projet Orion", "projet-v2.md": "# Version 2",
             "depenses.csv": "libelle,montant\nTest,400"}

    async def send(uid, cmd, args):
        assert uid == "owner"
        if cmd == "list_dir":
            assert args == {"path": "/docs"}
            return {"entries": [{"name": name, "type": "file"} for name in files]}
        assert cmd == "read_file"
        assert args["path"].startswith("/docs/")
        text = files[args["path"].removeprefix("/docs/")]
        return {"content": text, "encoding": "utf-8", "size": len(text.encode())}

    monkeypatch.setattr(indexer.desktop_registry, "send_command", AsyncMock(side_effect=send))
    first = await indexer.scan_folder(scan_env.id)
    assert (first["status"], first["indexed"], first["errors"]) == ("ok", 3, 0)
    assert scan_env.contents == {f"/docs/{k}": v.encode() for k, v in files.items()}
    for call in scan_env.rag.ingest_document.call_args_list:
        assert not call.kwargs["file_path"].exists()  # temporary copies cleaned up
    second = await indexer.scan_folder(scan_env.id)
    assert (second["status"], second["indexed"], second["skipped"]) == ("ok", 0, 3)
    assert scan_env.rag.ingest_document.await_count == 3
    async with scan_env.sessions() as db:
        folder = await db.get(WatchedFolder, scan_env.id)
        assert folder.last_scan_status == "ok" and folder.files_indexed == 3


@pytest.mark.asyncio
async def test_later_scan_progresses_past_batch_cap(monkeypatch, scan_env):
    monkeypatch.setattr(indexer, "_MAX_FILES_PER_SCAN", 2)
    monkeypatch.setattr(indexer, "_daemon_walk", AsyncMock(return_value=[
        "/docs/1.md", "/docs/2.md", "/docs/3.md"]))
    monkeypatch.setattr(indexer, "_daemon_read", AsyncMock(return_value=(b"content", "utf-8")))
    first = await indexer.scan_folder(scan_env.id)
    assert first["status"] == "partial" and first["indexed"] == 2
    assert "1 fichier(s) restant(s)" in first["message"]
    second = await indexer.scan_folder(scan_env.id)
    assert second["status"] == "ok" and second["indexed"] == 1
    assert second["skipped"] == 2


@pytest.mark.asyncio
async def test_denied_directory_persists_error_and_releases_scan(monkeypatch, scan_env):
    monkeypatch.setattr(indexer.desktop_registry, "send_command",
                        AsyncMock(side_effect=DesktopCommandError("access denied")))
    summary = await indexer.scan_folder(scan_env.id)
    assert summary["status"] == "error" and "access denied" in summary["message"]
    async with scan_env.sessions() as db:
        folder = await db.get(WatchedFolder, scan_env.id)
        assert folder.last_scan_status == "error" and folder.files_indexed == 0
    assert scan_env.id not in indexer._running_scans
    scan_env.rag.ingest_document.assert_not_awaited()
