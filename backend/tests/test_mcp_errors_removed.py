# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_errors_removed.py
# @brief      Ménage lot 4 — un module d'erreurs MCP que personne n'a jamais
#             importé, et dont les valeurs vivaient en dur ailleurs.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de suppression de `app/services/mcp_errors.py`.

**Pourquoi.** 48 lignes : un enum `MCPErrorCode`, une exception
`MCPConnectError`, un `RETRYABLE_CODES`. Mesuré le 29/07 : **aucun importeur**
dans `app/`, `tests/` ni `scripts/` — la seule occurrence du nom était sa
propre en-tête de fichier.

**Ce qui rend le constat net** : `mcp_client.py:504` écrit la chaîne
`"MCP_CONNECT_FAILED"` **en dur**, sans passer par l'enum censé la définir. Le
concept est vivant — la valeur part bien en base, colonne
`mcp_servers.last_error_code` — mais le module, lui, était mort.

⚠️ Un `RETRYABLE_CODES` jamais lu est pire qu'absent : il donne à croire qu'une
politique de reprise existe. Elle n'a jamais été branchée. La retirer rend
l'absence visible, ce qui est le but du ménage.

Run with:  cd backend && python -m pytest tests/test_mcp_errors_removed.py -v
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


def test_module_no_longer_importable() -> None:
    """Le module a disparu."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.mcp_errors")


def test_file_no_longer_on_disk() -> None:
    """Le fichier est supprimé, pas seulement vidé."""
    assert not (_BACKEND / "app" / "services" / "mcp_errors.py").exists()


def test_nothing_references_it() -> None:
    """Aucun module ne le référence — la condition qui rend la suppression sûre.

    Le pin regarde le source ici à dessein : il ne cherche pas un comportement
    mais une **absence de lien**, et un import mort ne se voit qu'à la lecture.
    """
    offenders: list[str] = []
    for folder in ("app", "tests", "scripts"):
        for path in (_BACKEND / folder).rglob("*.py"):
            # `test_docs_match_the_code` LISTE volontairement les noms
            # supprimés pour vérifier qu'aucun document ne les cite. Le nommer
            # n'est pas le référencer.
            if "__pycache__" in str(path) or path.name in (
                Path(__file__).name, "test_docs_match_the_code.py",
            ):
                continue
            if "mcp_errors" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(_BACKEND)))
    assert offenders == [], f"référencé par : {offenders}"


def test_mcp_client_still_records_its_error_code() -> None:
    """La chaîne écrite en base ne bouge pas — le concept survit au module.

    `mcp_client` la posait déjà en dur : supprimer l'enum ne change donc rien
    à ce qui atterrit dans `mcp_servers.last_error_code`.
    """
    import app.services.mcp_client  # noqa: F401 — doit s'importer sans l'enum

    src = (_BACKEND / "app" / "services" / "mcp_client.py").read_text(encoding="utf-8")
    assert '"MCP_CONNECT_FAILED"' in src, (
        "le code d'erreur écrit en base a changé — vérifier que rien ne "
        "dépendait de l'ancienne valeur avant de toucher à ce pin"
    )
