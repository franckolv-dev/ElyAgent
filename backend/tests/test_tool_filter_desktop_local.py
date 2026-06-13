# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_filter_desktop_local.py
# @brief      Régression 13/06 : un prompt référençant un fichier LOCAL
#             (chemin absolu /Users/…, ~/, « sur mon mac ») doit binder les
#             outils desktop_* — sinon l'agent ne peut ni lire ni écrire les
#             fichiers du Mac (tâche Prospection : RTF/CSV jamais modifiés).
# @license    Elastic License 2.0
# =============================================================================
"""Run with:  cd backend && python -m pytest tests/test_tool_filter_desktop_local.py -v"""
from __future__ import annotations

import pytest

from app.agent.tool_filter import filter_tools_by_query


@pytest.fixture(scope="module", autouse=True)
def _registry():
    from app.skills.builtin import register_all
    register_all()
    from app.skills import get_skill_registry
    return get_skill_registry()


def _names(registry, query: str) -> set[str]:
    return {t.name for t in filter_tools_by_query(registry.all_tools, query)}


def test_absolute_users_path_binds_desktop_tools(_registry):
    q = ('Ouvre le fichier "/Users/franck/Documents/TravauxELy/prospection.rtf" '
         'et ajoute les lignes au fichier .csv')
    got = _names(_registry, q)
    assert "desktop_read_file" in got
    assert "desktop_write_file" in got


@pytest.mark.parametrize("query", [
    "lis ~/Documents/notes.txt",
    "écris le rapport sur mon mac",
    "sauvegarde ça sur mon disque local",
    "traite les fichiers locaux du dossier",
])
def test_local_file_phrasings_bind_desktop(_registry, query):
    got = _names(_registry, query)
    assert any(n.startswith("desktop_") for n in got), f"desktop_* manquant pour : {query!r}"


def test_plain_cloud_file_word_does_not_force_desktop(_registry):
    # « fichier » seul (sans chemin local) reste un cas Drive/cloud — on ne
    # veut pas binder desktop_* pour tout et n'importe quoi.
    got = _names(_registry, "partage le fichier avec mon collègue sur Drive")
    assert any(n.startswith("drive_") for n in got)
    assert not any(n.startswith("desktop_") for n in got)
