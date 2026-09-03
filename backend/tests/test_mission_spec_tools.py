# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_spec_tools.py
# @brief      Une spec doit pouvoir NOMMER l'outil d'une étape. Sans ça,
#             `build_plan_from_spec` posait `tool_hint: None` en dur et la
#             mission structurée perdait le signal le plus précis de la
#             sélection d'outil — celui dont les missions libres disposent.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""`tools:` dans une spec de mission (28/08/2026).

Mesuré sur la mission « Prospection Calameo-LinkedIn », en exécutant la
vraie sélection sur les descriptions de la spec :

    étape « Crée un Google Sheet … »  -> sheets_batch_update, docs_batch_update,
                                          os_click, trainer_start…
                                          PAS sheets_create_spreadsheet
    étape « Lis un .md sur mon Drive » -> desktop_*, smart_knowledge_query…
                                          AUCUN drive_*

L'agent n'a pas mal choisi : il a pris le moins mauvais de ce qu'on lui
donnait. Plus la mission était structurée, moins elle savait quoi appeler —
exactement l'inverse de ce qu'on attend d'une spec.
"""
from __future__ import annotations

import textwrap

import pytest


def _spec(corps: str) -> str:
    return textwrap.dedent(corps).strip()


def test_une_etape_peut_nommer_ses_outils() -> None:
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(_spec("""
        version: 1
        steps:
          - id: tableur
            do: "Crée le Google Sheet du jour."
            tools: [sheets_create_spreadsheet, sheets_append_rows]
    """))

    assert spec.steps[0].tools == ("sheets_create_spreadsheet", "sheets_append_rows")


def test_un_outil_seul_s_ecrit_sans_liste() -> None:
    """`tools: drive_read_file` doit passer comme `tools: [drive_read_file]`."""
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(_spec("""
        version: 1
        steps:
          - id: historique
            do: "Lis le fichier d'historique sur le Drive."
            tools: drive_read_file
    """))

    assert spec.steps[0].tools == ("drive_read_file",)


def test_une_etape_sans_tools_reste_valide() -> None:
    """Le champ est optionnel — les specs existantes ne bougent pas."""
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(_spec("""
        version: 1
        steps:
          - id: cherche
            do: "Cherche des sociétés."
    """))

    assert spec.steps[0].tools == ()


def test_un_nom_d_outil_inconnu_est_refuse_a_la_creation() -> None:
    """Mieux vaut un refus à la création qu'une mission qui part de travers.

    Le parser liste TOUTES les erreurs d'un coup (contrat du Sprint 4c) :
    l'utilisateur corrige sa spec en une passe.
    """
    from app.services.mission_spec import MissionSpecError, parse_mission_spec
    from app.skills.builtin import register_all

    # En production l'app tourne, donc le registre est peuplé. Sans lui la
    # validation est volontairement permissive — refuser une spec correcte
    # parce qu'un registre n'est pas encore chargé coûterait plus cher qu'un
    # nom d'outil qui se signale à l'exécution.
    register_all()

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(_spec("""
            version: 1
            steps:
              - id: tableur
                do: "Crée le tableur."
                tools: [sheets_create_spreadsheat]
        """))

    assert "sheets_create_spreadsheat" in str(exc.value)


def test_le_plan_transporte_les_outils_jusqu_a_la_selection() -> None:
    """Le `tool_hint` du plan est CE que lit `_filter_tools_for_step`."""
    from app.services.mission_spec import parse_mission_spec
    from app.services.mission_spec_runtime import build_plan_from_spec

    spec = parse_mission_spec(_spec("""
        version: 1
        steps:
          - id: tableur
            do: "Crée le Google Sheet du jour."
            tools: [sheets_create_spreadsheet]
    """))
    _texte, plan_json = build_plan_from_spec(spec)

    etape = plan_json["steps"][0]
    assert etape["tool_hint"] == "sheets_create_spreadsheet", (
        "sans ce report, la spec nomme un outil que personne ne lit"
    )


@pytest.mark.asyncio
async def test_l_outil_nomme_est_reellement_lie_a_l_etape() -> None:
    """Bout en bout : ce que la spec nomme arrive dans la liaison.

    C'est le test qui compte — les précédents vérifient le transport, celui-ci
    vérifie l'effet : `sheets_create_spreadsheet` ne remontait PAS pour cette
    description avant le correctif.
    """
    import app.agent.missions.nodes as mn
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    outils = await mn._filter_tools_for_step(
        get_skill_registry().all_tools,
        "sheets_create_spreadsheet",
        "Trouver des sociétés et les enregistrer dans un Google Sheet.",
        "Crée sur mon Google Drive un Google Sheet nommé prospection du jour.",
    )

    assert "sheets_create_spreadsheet" in [t.name for t in outils]


@pytest.mark.asyncio
async def test_tous_les_outils_nommes_sont_lies_pas_seulement_le_premier() -> None:
    """Une étape qui nomme deux outils doit recevoir les deux.

    L'étape `contacts` de la mission réelle en demande deux : lire LinkedIn
    dans le navigateur, puis écrire la ligne dans le tableur. N'en lier qu'un
    la rendrait impossible à accomplir.
    """
    import app.agent.missions.nodes as mn
    from app.services.mission_spec import parse_mission_spec
    from app.services.mission_spec_runtime import build_plan_from_spec
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    spec = parse_mission_spec(_spec("""
        version: 1
        steps:
          - id: contacts
            do: "Relève les décideurs puis écris-les dans le tableur."
            tools: [browser_tab_read_text, sheets_append_rows]
    """))
    _texte, plan_json = build_plan_from_spec(spec)
    etape = plan_json["steps"][0]

    outils = await mn._filter_tools_for_step(
        get_skill_registry().all_tools,
        etape.get("tool_hint"),
        "Prospection.",
        etape["description"],
        step_tools=tuple(etape.get("tools") or ()),
    )
    noms = [t.name for t in outils]

    assert "browser_tab_read_text" in noms
    assert "sheets_append_rows" in noms
