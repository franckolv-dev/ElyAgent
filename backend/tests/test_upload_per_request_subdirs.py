# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_upload_per_request_subdirs.py
# @brief      Tests — un sous-dossier par upload (isolation des pièces jointes)
# @license    Elastic License 2.0
# =============================================================================
"""Chaque upload va dans SON sous-dossier `uploads/<user>/<uuid8>/<nom>`.

Contexte (incident 17/07) : les uploads étaient stockés à plat dans
`uploads/<user>/` qui accumule tout l'historique. Quand Ely passe le dossier
parent d'une pièce jointe à un outil « dossier » (ex. MCP
`translate_pdf_folder(input_dir=…)`), elle traitait TOUT l'historique :
un manuscrit de 400 pages uploadé 3 fois a été mis en traduction 3 fois,
plus 4 PDF sans rapport. Avec un sous-dossier par upload, le parent d'une
pièce jointe ne contient que le(s) fichier(s) de la demande en cours.
"""
from __future__ import annotations

import io
import os
import time

import pytest
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.routers import upload as upload_module
from app.routers.upload import purge_old_uploads, upload_file


@pytest.fixture
def uploads_root(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_module, "UPLOADS_DIR", tmp_path)
    return tmp_path


def _upload(name: str, content: bytes = b"%PDF-1.4 fake"):
    return StarletteUploadFile(filename=name, file=io.BytesIO(content))


@pytest.mark.asyncio
async def test_upload_goes_into_own_subdir(uploads_root):
    resp = await upload_file(file=_upload("manuscrit.pdf"), user_id="u1")
    path = uploads_root / "u1"
    subdirs = [d for d in path.iterdir() if d.is_dir()]
    assert len(subdirs) == 1
    stored = subdirs[0] / "manuscrit.pdf"
    assert stored.is_file()
    assert resp["path"] == str(stored)
    assert resp["filename"] == "manuscrit.pdf"


@pytest.mark.asyncio
async def test_parent_dir_of_attachment_contains_only_this_upload(uploads_root):
    """LE contrat de l'incident : un outil « dossier » qui reçoit le parent
    de la pièce jointe ne doit voir que cette pièce jointe — pas les
    uploads des demandes précédentes."""
    import pathlib

    r1 = await upload_file(file=_upload("manuscrit.pdf"), user_id="u1")
    r2 = await upload_file(file=_upload("manuscrit.pdf"), user_id="u1")
    r3 = await upload_file(file=_upload("autre_doc.pdf"), user_id="u1")

    parent3 = pathlib.Path(r3["path"]).parent
    assert [f.name for f in parent3.iterdir()] == ["autre_doc.pdf"]

    # Les 3 uploads coexistent sans collision (même nom compris)
    assert len({r1["path"], r2["path"], r3["path"]}) == 3
    for r in (r1, r2, r3):
        assert pathlib.Path(r["path"]).is_file()


@pytest.mark.asyncio
async def test_dotdot_filename_cannot_escape_subdir(uploads_root):
    """`..` sanitizé ne doit pas remonter hors du sous-dossier d'upload."""
    resp = await upload_file(
        file=_upload("...pdf"), user_id="u1"
    )
    import pathlib

    stored = pathlib.Path(resp["path"])
    assert stored.is_file()
    assert uploads_root / "u1" in stored.parents


@pytest.mark.asyncio
async def test_purge_prunes_empty_upload_subdirs(uploads_root, monkeypatch):
    monkeypatch.setattr(upload_module, "UPLOADS_RETENTION_DAYS", 30)
    resp = await upload_file(file=_upload("vieux.pdf"), user_id="u1")

    import pathlib

    stored = pathlib.Path(resp["path"])
    old = time.time() - 40 * 86400
    os.utime(stored, (old, old))

    removed = await purge_old_uploads()
    assert removed == 1
    assert not stored.exists()
    # Le sous-dossier d'upload vidé est élagué aussi (sinon des milliers
    # de dossiers vides s'accumulent au rythme des captures d'écran)
    assert not stored.parent.exists()
