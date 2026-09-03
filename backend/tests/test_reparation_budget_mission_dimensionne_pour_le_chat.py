# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reparation_budget_mission_dimensionne_pour_le_chat.py
# @brief      Le budget de tokens d'une mission est dimensionné pour le
#             moteur qui la fait tourner : la boucle du chat.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Réparation post-audit (03/09/2026).

Production, 03/09 entre 05:46 et 05:58, mission ``65b3a146`` :

    passage terminé — 5 action(s), 153504 tokens
    budget exhausted (token budget exhausted (156436/100000)) — failing

Depuis #370, une mission libre est un tour de chat : le catalogue complet
(234 outils) et le prompt système souverain partent à CHAQUE appel, soit
~30 000 tokens par action. Le budget par défaut (50 000, plafond 500 000)
datait du moteur précédent, qui ne liait qu'un outil par tick : il ne
laisse plus qu'une ou deux actions à une mission avant de la faire échouer.

Le compte des tokens ne change pas (il dit ce que le fournisseur facture) ;
c'est la valeur par défaut et le plafond qui suivent le moteur.
"""
from __future__ import annotations

import inspect

BUDGET_PAR_DEFAUT = 500_000
PLAFOND = 5_000_000


def test_le_schema_de_creation_propose_un_budget_pour_la_boucle_du_chat():
    from app.routers.missions import MissionCreate

    m = MissionCreate(title="t", goal="un objectif")
    assert m.budget_tokens == BUDGET_PAR_DEFAUT
    assert MissionCreate(title="t", goal="un objectif", budget_tokens=PLAFOND).budget_tokens == PLAFOND


def test_le_schema_de_mise_a_jour_accepte_le_meme_plafond():
    from app.routers.missions import MissionUpdate

    assert MissionUpdate(budget_tokens=PLAFOND).budget_tokens == PLAFOND


def test_le_modele_et_le_service_partagent_le_defaut():
    from app.models.mission import Mission
    from app.services import mission_service

    assert Mission.__table__.c.budget_tokens.default.arg == BUDGET_PAR_DEFAUT
    sig = inspect.signature(mission_service.create_mission)
    assert sig.parameters["budget_tokens"].default == BUDGET_PAR_DEFAUT


def test_le_formulaire_web_propose_le_meme_defaut():
    from pathlib import Path

    page = Path(__file__).resolve().parents[2] / "frontend/src/app/missions/page.tsx"
    source = page.read_text(encoding="utf-8")
    assert "budget_tokens ?? 500_000" in source
    assert "budget_tokens ?? 50_000" not in source
