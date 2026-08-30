# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_can_always_ask_for_a_tool.py
# @brief      `find_tool` doit TOUJOURS etre lie : c'est le seul moyen qu'a
#             Ely de reclamer un outil absent de sa selection.
# @license    Elastic License 2.0
# =============================================================================
"""Demander un outil ne doit pas dépendre d'un tirage sémantique (30/08/2026).

Le catalogue compte ~200 outils, dont 15 au plus sont liés par étape. Le
mécanisme prévu pour combler l'écart est `find_tool` : le modèle décrit la
capacité qui lui manque, `find_tool` nomme l'outil, et
`app.agent.discovered_tools` le lie en tête au tick suivant.

Encore faut-il que `find_tool` soit lui-même lié. Il ne l'était pas : le
filet générique se limite à `web_search`, `web_browse` et
`smart_knowledge_query`, et `find_tool` n'arrivait que si le re-rank
sémantique le pêchait par hasard.

Reproduit sur la mission « Prospection Print LinkedIn », étape `memoire`
(hint `drive_read_file`, spec `[drive_read_file, drive_update_file]`) : le
préfixe `drive` a rempli les 15 places à lui seul. Ni `find_tool`, ni un
seul des trois outils du filet. Ely ne pouvait ni agir autrement, ni le dire.

Second défaut du même endroit : le code réserve des places au filet
générique (`fill_budget = _TOOL_CAP - len(candidates) - len(_GENERIC_TOOLS)`)
mais uniquement face au remplissage sémantique. La troncature finale
`candidates[:_TOOL_CAP]` les reprenait. Une réservation qu'une autre ligne
peut annuler n'est pas une réservation.
"""
from __future__ import annotations

import pytest

# L'étape réelle, mot pour mot : c'est son texte qui a saturé la sélection.
_ETAPE_MEMOIRE = (
    "Ajoute au fichier historique_Prospection_Print.md sur mon Drive les "
    "sociétés pour lesquelles au moins un contact a été enregistré "
    "aujourd'hui, avec la date du jour."
)


@pytest.fixture(scope="module")
def catalogue():
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    outils = get_skill_registry().all_tools
    assert len(outils) > 100, "sans registre chargé, ce test ne prouve rien"
    return outils


async def _selection(catalogue, **kw) -> list[str]:
    import app.agent.missions.nodes as mn

    retenus = await mn._filter_tools_for_step(catalogue, **kw)
    return [t.name for t in retenus]


@pytest.mark.asyncio
async def test_find_tool_survit_a_une_famille_qui_sature_la_selection(
    catalogue, monkeypatch,
) -> None:
    """Le cas réel : 14 outils `drive_*` occupaient toute la place."""
    monkeypatch.setenv("MISSION_SEMANTIC_TOOLS_DISABLED", "1")

    noms = await _selection(
        catalogue,
        tool_hint="drive_read_file",
        goal="Prospection Print LinkedIn",
        current_step_desc=_ETAPE_MEMOIRE,
        step_tools=("drive_read_file", "drive_update_file"),
    )

    assert "find_tool" in noms, (
        "sans lui, Ely ne peut pas réclamer l'outil qui lui manque — elle "
        "ne peut que se tromper d'outil, puis se faire refuser l'étape"
    )


@pytest.mark.asyncio
async def test_le_filet_generique_survit_a_la_troncature(
    catalogue, monkeypatch,
) -> None:
    """Ses places étaient dites « réservées » et ne l'étaient pas."""
    import app.agent.missions.nodes as mn

    monkeypatch.setenv("MISSION_SEMANTIC_TOOLS_DISABLED", "1")

    noms = await _selection(
        catalogue,
        tool_hint="drive_read_file",
        goal="Prospection Print LinkedIn",
        current_step_desc=_ETAPE_MEMOIRE,
        step_tools=("drive_read_file", "drive_update_file"),
    )

    absents = sorted(mn._GENERIC_TOOLS - set(noms))
    assert not absents, f"filet de secours emporté par le cap : {absents}"


def test_le_filet_ne_nomme_que_des_outils_qui_existent(catalogue) -> None:
    """`web_browse` y figurait — introuvable partout ailleurs dans le dépôt.

    Un nom qui ne correspond à rien ne lève pas : la boucle qui l'ajoute ne
    le trouve jamais, et c'est tout. Le filet annonçait trois outils et n'en
    livrait que deux, en silence, depuis sa création.
    """
    import app.agent.missions.nodes as mn

    connus = {t.name for t in catalogue}
    assert not (mn._RESERVES - connus)


@pytest.mark.asyncio
async def test_les_outils_de_la_spec_restent_en_tete(
    catalogue, monkeypatch,
) -> None:
    """Garde-fou : le filet ne doit déloger aucun outil nommé par l'auteur."""
    monkeypatch.setenv("MISSION_SEMANTIC_TOOLS_DISABLED", "1")

    noms = await _selection(
        catalogue,
        tool_hint="drive_read_file",
        goal="Prospection Print LinkedIn",
        current_step_desc=_ETAPE_MEMOIRE,
        step_tools=("drive_read_file", "drive_update_file"),
    )

    assert noms[:2] == ["drive_read_file", "drive_update_file"]


@pytest.mark.asyncio
async def test_une_spec_bavarde_garde_tous_ses_outils(
    catalogue, monkeypatch,
) -> None:
    """Une spec qui nomme beaucoup d'outils l'emporte sur le cap.

    L'auteur a écrit son intention à la main : c'est le seul signal du lot
    qui ne soit pas une heuristique.
    """
    monkeypatch.setenv("MISSION_SEMANTIC_TOOLS_DISABLED", "1")
    voulus = tuple(
        t.name for t in catalogue if t.name.startswith("drive_")
    )[:14]

    noms = await _selection(
        catalogue,
        tool_hint="drive_read_file",
        goal="Prospection Print LinkedIn",
        current_step_desc=_ETAPE_MEMOIRE,
        step_tools=voulus,
    )

    assert set(voulus).issubset(set(noms))
    assert "find_tool" in noms
