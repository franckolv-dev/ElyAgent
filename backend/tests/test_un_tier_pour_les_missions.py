# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_un_tier_pour_les_missions.py
# @brief      Un niveau de routage « Missions » dédié : l'admin choisit la
#             chaîne de modèles des missions sans toucher au chat.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « Plateformes littéraires » (07/09/2026) : 5,17 M tokens sur trois
modèles que Franck n'avait pas choisis pour ça — le primaire du niveau C
était invalide, le repli a pris ChatGPT Plus jusqu'au quota, puis Kimi K3
facturé. Une mission est un travail long, à plusieurs millions de tokens :
elle mérite sa propre chaîne.

Le niveau « mission » existe dans la config de routage et l'onglet Routage.
Tant qu'il est VIDE, les missions tournent sur le niveau C, comme avant :
aucun changement silencieux pour une installation qui ne le configure pas.

Run with:  cd backend && python -m pytest tests/test_un_tier_pour_les_missions.py -v
"""
from __future__ import annotations

import pytest


def test_le_niveau_mission_existe_vide_par_defaut():
    from app.services.llm_provider import DEFAULT_TIER_CONFIG, ComplexityTier

    assert ComplexityTier.MISSION.value == "mission"
    assert DEFAULT_TIER_CONFIG["mission"]["providers"] == [], (
        "vide = non configuré = les missions restent sur le niveau C"
    )


def test_l_onglet_routage_presente_le_niveau_mission():
    from app.routers.settings_llm import TIER_META

    meta = {m["id"]: m for m in TIER_META}
    assert "mission" in meta
    assert meta["mission"]["badge"] == "M"
    assert "niveau C" in meta["mission"]["description"]
    assert "local" in meta["mission"]["description"].lower()


def test_sans_chaine_configuree_les_missions_restent_sur_le_niveau_c():
    from app.agent.missions.nodes import tier_des_missions
    from app.services.llm_provider import ComplexityTier

    assert tier_des_missions({}) is ComplexityTier.COMPLEX
    assert tier_des_missions({"mission": {"providers": []}}) is ComplexityTier.COMPLEX
    assert tier_des_missions({"complex": {"providers": ["a"]}}) is ComplexityTier.COMPLEX


def test_avec_une_chaine_les_missions_prennent_leur_niveau():
    from app.agent.missions.nodes import tier_des_missions
    from app.services.llm_provider import ComplexityTier

    assert tier_des_missions({"mission": {"providers": ["uuid-1"]}}) is ComplexityTier.MISSION


@pytest.mark.asyncio
async def test_le_tier_d_une_mission_libre_suit_la_config(monkeypatch):
    import app.services.llm_provider as lp
    from app.agent.missions.nodes import _mission_llm_tier

    monkeypatch.setattr(lp, "get_tier_config", lambda: {"mission": {"providers": ["uuid-1"]}})
    assert (await _mission_llm_tier("mission-sans-mandat")) is lp.ComplexityTier.MISSION

    monkeypatch.setattr(lp, "get_tier_config", lambda: {"complex": {"providers": ["uuid-1"]}})
    assert (await _mission_llm_tier("mission-sans-mandat")) is lp.ComplexityTier.COMPLEX


def test_le_noeud_agent_honore_l_epingle_mission():
    from app.agent.nodes import tier_du_tour
    from app.services.llm_provider import ComplexityTier

    assert tier_du_tour("mission", "bonjour") is ComplexityTier.MISSION
    assert tier_du_tour("complex", "bonjour") is ComplexityTier.COMPLEX
    # Sans épingle, le classement ordinaire décide.
    assert tier_du_tour("", "bonjour") in (ComplexityTier.SIMPLE, ComplexityTier.MEDIUM, ComplexityTier.COMPLEX)


def test_le_passage_de_mission_epingle_le_tier_resolu():
    """Le passage ne code plus « complex » en dur : il épingle le tier rendu
    par `_mission_llm_tier`, donc « mission » dès que la chaîne existe."""
    import inspect

    from app.agent.missions import chat_loop

    src = inspect.getsource(chat_loop.run_mission_chat_passage)
    assert '"tier_pin": "complex"' not in src
    assert "_mission_llm_tier" in src


def test_la_config_de_routage_accepte_le_niveau_mission():
    from app.routers.settings_llm import TierConfigUpdate

    body = TierConfigUpdate(config={"mission": {"providers": [], "fallback_enabled": True}})
    assert "mission" in body.config
