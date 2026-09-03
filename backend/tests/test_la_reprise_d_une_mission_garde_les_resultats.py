# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_la_reprise_d_une_mission_garde_les_resultats.py
# @brief      Quand une mission repart après une coupure, son carnet dit ce
#             qui EXISTE (fichiers créés, dernières lectures), pas seulement
#             quels outils ont tourné.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « test2 », 03/09/2026. Le backend a été recréé en plein passage
(un ``docker compose up`` sans ``--no-deps``). Au réveil, le carnet portait :

    **Passage 0** — actions déjà jouées : drive_list_files ✓, web_search ✓,
    …, drive_create_file ✓, … Vérifie ce qui existe déjà avant de le refaire.

Des NOMS d'outils. Le passage suivant a recréé le tableur (deux Sheets
homonymes et un CSV vide), relu les mêmes pages, et conclu « historique
inchangé » alors qu'il venait d'être mis à jour. Le carnet doit porter les
RÉSULTATS : ce que les outils créateurs ont rendu (identifiants, liens), et
un extrait des dernières lectures.

Et sur la boucle du chat une page LinkedIn vaut cinq actions ; 100
itérations n'ont pas suffi. Le plafond passe à 1 000, le défaut à 100.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _etape(nom: str, sortie: str, ok: bool = True, phase: str = "act"):
    return SimpleNamespace(phase=phase, tool_name=nom, success=ok, tool_output=sortie)


def test_les_extraits_gardent_ce_qui_a_ete_cree_et_les_dernieres_lectures():
    from app.agent.missions.chat_loop import _extraits_de_trace

    steps = [
        _etape("drive_read_file", "Contenu du fichier historique : Négoce Drouillet — 31/08/2026"),
        _etape("sheets_create_spreadsheet", "✓ Tableur créé : prospection_catalogue-2026_09_03 (id 1AbC, https://docs.google.com/spreadsheets/d/1AbC)"),
    ] + [_etape("web_search", f"Résultats de la recherche n°{i}") for i in range(30)] + [
        _etape("browser_tab_read_text", "URL : https://www.linkedin.com/search … Lise Buret • Chargée de Marketing chez Groupe Barillet"),
        _etape("sheets_update_cells", "Erreur : plage invalide", ok=False),
        _etape("plan", "…", phase="plan"),
    ]

    texte = _extraits_de_trace(steps, recents=5)

    # Ce qui a été créé survit, même loin dans la trace.
    assert "sheets_create_spreadsheet ✓" in texte and "1AbC" in texte
    # Les dernières lectures aussi, avec leur extrait.
    assert "browser_tab_read_text ✓" in texte and "Lise Buret" in texte
    assert "sheets_update_cells ✗" in texte and "plage invalide" in texte
    # Les vieilles recherches sans portée ne sont pas recopiées.
    assert "Résultats de la recherche n°0" not in texte
    # La phase de planification n'est pas une action.
    assert "plan" not in texte.split("\n")[0]


def test_les_extraits_sont_bornes_et_sur_une_ligne():
    from app.agent.missions.chat_loop import _extraits_de_trace

    steps = [_etape("drive_create_file", "ligne 1\nligne 2\n" + "x" * 5000)] * 40
    texte = _extraits_de_trace(steps, recents=10, maxi=1500)

    assert len(texte) <= 1500
    assert "\nligne 2" not in texte.replace("- ", "")  # les sauts de ligne de la sortie sont écrasés
    assert "…" in texte


def test_sans_action_les_extraits_sont_vides():
    from app.agent.missions.chat_loop import _extraits_de_trace

    assert _extraits_de_trace([]) == ""
    assert _extraits_de_trace([_etape("plan", "x", phase="plan")]) == ""


@pytest.mark.asyncio
async def test_l_amorce_depuis_la_trace_recopie_les_resultats(monkeypatch):
    from app.agent.missions import chat_loop
    from app.services import mission_service, mission_workspace

    steps = [
        _etape("drive_create_file", "✓ Fichier créé : historique_Prospection_Print.md (id 191Er)"),
        _etape("web_search", "10 résultats"),
    ]

    async def _steps(mission_id):
        return steps

    ecrits: list[tuple] = []
    monkeypatch.setattr(mission_service, "list_steps", _steps)
    monkeypatch.setattr(mission_workspace, "read_carnet", lambda mid: "# Carnet\n")
    monkeypatch.setattr(mission_workspace, "carnet_append_section", lambda mid, sec, txt: ecrits.append((sec, txt)))

    await chat_loop._amorcer_depuis_la_trace("m-reprise")

    assert len(ecrits) == 1
    section, texte = ecrits[0]
    assert section == "Passages"
    assert "191Er" in texte
    assert "Vérifie ce qui existe déjà" in texte


def test_les_plafonds_d_iterations_suivent_la_boucle_du_chat():
    from app.routers.missions import MissionCreate, MissionUpdate

    assert MissionCreate(title="t", goal="un objectif").budget_iterations == 100
    assert MissionCreate(title="t", goal="un objectif", budget_iterations=1000).budget_iterations == 1000
    assert MissionUpdate(budget_iterations=1000).budget_iterations == 1000


def test_le_formulaire_web_suit_les_memes_plafonds():
    from pathlib import Path

    page = Path(__file__).resolve().parents[2] / "frontend/src/app/missions/page.tsx"
    src = page.read_text(encoding="utf-8")
    assert "budget_iterations ?? 100" in src
    assert "max={1000}" in src
    assert "Math.min(1000" in src
