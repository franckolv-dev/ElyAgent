# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_desktop_binary_download.py
# @brief      Tests for GET /api/desktop/binaries/{filename} (forced download)
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for the desktop binary download route — direct-handler style.

Contexte : servis par le mount statique /static/desktop, les binaires sans
extension recevaient un MIME deviné text/plain → Safari/Chrome ajoutaient
`.txt` au fichier enregistré. La route dédiée force application/octet-stream
+ Content-Disposition attachment, avec une allowlist stricte du catalogue.
"""
from __future__ import annotations

import pytest

from app.routers import desktop as desktop_module
from app.routers.desktop import (
    _BINARY_CATALOG,
    desktop_binaries,
    desktop_binary_download,
)


class _FakeRequest:
    """Just enough of starlette.Request for desktop_binaries()."""

    base_url = "http://testserver/"


@pytest.fixture
def fake_dist_dir(tmp_path, monkeypatch):
    """Point _desktop_static_dir() at a tmp dir with one built binary
    (macos-arm64) + its installer. The other catalog entries stay unbuilt."""
    (tmp_path / "ely-desktop-macos-arm64").write_bytes(b"\x00\x01fake-mach-o")
    (tmp_path / "install.sh").write_text("#!/bin/sh\necho install\n")
    monkeypatch.setattr(desktop_module, "_desktop_static_dir", lambda: tmp_path)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────
# GET /desktop/binaries/{filename}
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_binary_pins_octet_stream_and_attachment(fake_dist_dir):
    """Le fix du ticket .txt : Content-Type ET Content-Disposition sont
    pinnés. Si l'un des deux change, Safari/Chrome peuvent recommencer à
    deviner text/plain et suffixer `.txt`."""
    resp = await desktop_binary_download("ely-desktop-macos-arm64")
    assert resp.media_type == "application/octet-stream"
    assert resp.headers["content-type"] == "application/octet-stream"
    assert (
        resp.headers["content-disposition"]
        == 'attachment; filename="ely-desktop-macos-arm64"'
    )


@pytest.mark.asyncio
async def test_download_installer_also_attachment(fake_dist_dir):
    """install.sh / install.bat passent par la même route : attachment
    aussi (pas d'affichage inline du script dans l'onglet)."""
    resp = await desktop_binary_download("install.sh")
    assert resp.media_type == "application/octet-stream"
    assert resp.headers["content-disposition"] == 'attachment; filename="install.sh"'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    ["ely-config.json", ".env", "cyberentity.db", "ely-desktop-macos-arm64.txt"],
)
async def test_download_outside_allowlist_404(fake_dist_dir, filename):
    """Tout nom hors catalogue doit 404 — même si un fichier de ce nom
    existait dans le dossier, la route ne sert QUE l'allowlist."""
    from fastapi import HTTPException

    (fake_dist_dir / filename).write_text("should never be served")
    with pytest.raises(HTTPException) as exc:
        await desktop_binary_download(filename)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_download_known_but_unbuilt_404(fake_dist_dir):
    """Nom du catalogue mais binaire pas buildé → 404 propre (pas de 500)."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await desktop_binary_download("ely-desktop-linux-amd64")
    assert exc.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# GET /desktop/binaries — les URLs du catalogue pointent sur la route dédiée
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_urls_point_to_download_route(fake_dist_dir):
    """Régression : les URLs renvoyées au frontend ne doivent plus pointer
    sur le mount statique (qui sert text/plain pour les sans-extension)."""
    data = await desktop_binaries(_FakeRequest(), current_user=None)

    assert len(data["binaries"]) == 1  # seul macos-arm64 est "buildé"
    entry = data["binaries"][0]
    assert entry["filename"] == "ely-desktop-macos-arm64"
    assert entry["url"].endswith("/api/desktop/binaries/ely-desktop-macos-arm64")
    assert entry["installer"].endswith("/api/desktop/binaries/install.sh")
    assert "/static/desktop/" not in entry["url"]
    assert "/static/desktop/" not in entry["installer"]


def test_allowlist_covers_whole_catalog():
    """Chaque filename + installer_filename du catalogue est téléchargeable
    via la route dédiée (sinon desktop_binaries renverrait des liens 404)."""
    for entry in _BINARY_CATALOG:
        assert entry["filename"] in desktop_module._DOWNLOADABLE_FILENAMES
        assert entry["installer_filename"] in desktop_module._DOWNLOADABLE_FILENAMES
