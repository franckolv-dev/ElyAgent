# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_hint_prefers_its_own_skill.py
# @brief      Quand l'indice d'outil d'une etape appartient a une competence,
#             la famille de CETTE competence passe avant les homonymes.
# @license    Elastic License 2.0
# =============================================================================
"""Deux navigateurs portent le meme prefixe (31/08/2026).

`browser_navigate`, `browser_get_text`… sont le Chromium jetable de
Playwright — sans session. `browser_open_tab`, `browser_tab_wait_loaded`,
`browser_tab_read_text`… sont le Chrome de l'utilisateur — avec ses cookies,
donc LinkedIn ouvert. La #260 a corrige les DESCRIPTIONS pour que le chat
ne confonde plus les deux ; la selection d'outils des missions, elle, ne les
lit pas : elle etend l'indice `browser_tab_read_text` a son prefixe
`browser`, dans l'ordre d'enregistrement du registre — et le navigateur sans
session est enregistre AVANT l'autre. Avec 11 places pour 23 outils, les
huit outils Playwright entraient, `browser_open_tab` et
`browser_tab_wait_loaded` restaient dehors.

La regle : l'outil vise appartient a une competence ; les outils de cette
competence sont servis d'abord, les homonymes d'une autre competence
ensuite. L'ordre d'enregistrement ne departage plus que les egaux.
"""
from __future__ import annotations

import pytest

import app.agent.missions.nodes as mn


class _T:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


_SANS_SESSION = [
    "browser_navigate", "browser_search_web", "browser_search_images",
    "browser_get_text", "browser_screenshot", "browser_click", "browser_fill",
    "browser_close",
]
_CHROME_UTILISATEUR = [
    "browser_list_tabs", "browser_tab_get_url", "browser_tab_read_text",
    "browser_tab_read_html", "browser_tab_screenshot", "browser_open_tab",
    "browser_tab_wait_loaded", "browser_tab_wait_for_selector",
    "browser_close_tab", "browser_tab_click", "browser_tab_fill",
    "browser_tab_navigate", "browser_history_search",
    "browser_bookmarks_search", "browser_downloads_search",
]
_FILET = ["web_search", "web_extract", "smart_knowledge_query", "find_tool"]


def _catalogue() -> list[_T]:
    # Meme ordre que le registre : Playwright d'abord, l'extension ensuite.
    return [_T(n) for n in _SANS_SESSION + _CHROME_UTILISATEUR + _FILET]


def _competences() -> dict[str, str]:
    return {**{n: "browser" for n in _SANS_SESSION},
            **{n: "browser_extension" for n in _CHROME_UTILISATEUR}}


@pytest.mark.asyncio
async def test_la_famille_de_la_competence_visee_passe_avant_les_homonymes(monkeypatch):
    monkeypatch.setattr(mn, "_semantic_rank_disabled", lambda: True)
    monkeypatch.setattr(mn, "_skill_map", lambda: _competences())

    retenus = await mn._filter_tools_for_step(
        _catalogue(), "browser_tab_read_text", "prospecter",
        "Relève les décideurs sur LinkedIn.",
    )
    noms = [t.name for t in retenus]

    # La sequence LinkedIn entiere tient dans la selection…
    for outil in ("browser_open_tab", "browser_tab_wait_loaded",
                  "browser_tab_read_text", "browser_close_tab"):
        assert outil in noms, f"{outil} manque : {noms}"
    # …et le navigateur sans session n'est plus servi devant elle.
    assert "browser_navigate" not in noms, noms


@pytest.mark.asyncio
async def test_sans_competence_connue_l_ordre_du_registre_reste_la_regle(monkeypatch):
    """Pin : un catalogue sans competences (tests, registre muet) ne change pas."""
    monkeypatch.setattr(mn, "_semantic_rank_disabled", lambda: True)
    monkeypatch.setattr(mn, "_skill_map", lambda: {})

    retenus = await mn._filter_tools_for_step(
        _catalogue(), "browser_tab_read_text", "prospecter",
        "Relève les décideurs sur LinkedIn.",
    )
    noms = [t.name for t in retenus]
    assert noms[0] == "browser_tab_read_text"
    assert noms[1] == "browser_navigate"
