# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_approbation_de_tache_hors_passe_plats.py
# @brief      « Autoriser pour cette tâche » ne dispense pas un *_raw_api_call.
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Audit sécurité 02/09/2026, second tour — la porte voisine.

Le premier correctif a rendu les sept ``*_raw_api_call`` non dispensables par
la préférence permanente (« Toujours autoriser »). Mais l'approbation PAR
TÂCHE est évaluée AVANT elle, dans les deux appelants (chat et missions), et
elle ignorait délibérément la nature de l'outil. Un clic sur « Autoriser pour
cette tâche » éteignait donc encore la confirmation d'un passe-plat pour tout
le reste de la conversation.

Côté missions c'est pire : la clé de tâche est le ``mission_id``, et rien en
production n'appelle ``clear_task_approvals`` — la dispense survivait à tous
les ticks suivants, y compris ceux de 3 h du matin.

Ces tests exercent les DEUX chemins de décision réels (le pipeline de la
passerelle et ``dispatch_tool`` des missions), pas la fonction de registre.
"""
from __future__ import annotations

import pytest

from app.agent.missions import nodes as mnodes
from app.services import task_approvals
from app.services.security_filter import SecurityFilter
from app.services.tool_gateway import GatewayContext, _decide_hitl

# Passe-plat vers l'API Google entière : jamais dispensable.
_PASSE_PLAT = "gmail_raw_api_call"
# Dangereux mais ORDINAIRE : la dispense par tâche doit continuer d'y marcher
# (c'est le confort de 2026-06-03 — 11 suppressions, 1 seul clic).
_DANGEREUX_ORDINAIRE = "drive_delete_file"


def _ctx(conversation_id: str) -> GatewayContext:
    return GatewayContext(
        user_id="user-approb",
        conversation_id=conversation_id,
        pii_filter=None,
        criticality_filter=SecurityFilter(),
        hitl=None,
        memory=None,
    )


# ── Chemin CHAT : le pipeline de décision de la passerelle ───────────────────
@pytest.mark.asyncio
async def test_chat_une_approbation_de_tache_ne_dispense_pas_un_passe_plat():
    conv = "conv-passe-plat"
    task_approvals.clear_task_approvals(conv)
    task_approvals.approve_tool_for_task(conv, _PASSE_PLAT)
    try:
        assert await _decide_hitl(_ctx(conv), _PASSE_PLAT, {}, {}) is True
    finally:
        task_approvals.clear_task_approvals(conv)


@pytest.mark.asyncio
async def test_chat_une_approbation_de_tache_dispense_un_dangereux_ordinaire():
    conv = "conv-ordinaire"
    task_approvals.clear_task_approvals(conv)
    task_approvals.approve_tool_for_task(conv, _DANGEREUX_ORDINAIRE)
    try:
        assert await _decide_hitl(_ctx(conv), _DANGEREUX_ORDINAIRE, {}, {}) is False
    finally:
        task_approvals.clear_task_approvals(conv)


# ── Chemin MISSIONS : dispatch_tool ──────────────────────────────────────────
class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name

    async def ainvoke(self, args):  # noqa: ARG002
        return "EXECUTED"


class _FakeRegistry:
    def __init__(self, tools):
        self._tools = tools

    @property
    def all_tools(self):
        return self._tools


def _patch_mission(monkeypatch, tool_name: str, *, decision: str | None,
                   hitl_doit_etre_appele: bool):
    """Câble le dispatch missions ; le faux HITL note s'il a été sollicité."""
    import app.services.hitl_descriptions as hd
    import app.services.hitl_manager as hm
    import app.services.tool_acl as ta
    import app.skills as skills_mod

    monkeypatch.setattr(
        skills_mod, "get_skill_registry",
        lambda: _FakeRegistry([_FakeTool(tool_name)]),
    )
    vu = {"demande": False}

    class _FakeHitl:
        async def request_validation(self, description, user_id):  # noqa: ARG002
            vu["demande"] = True
            if not hitl_doit_etre_appele:
                raise AssertionError(
                    "la confirmation ne devait PAS être redemandée"
                )
            return decision, None

    monkeypatch.setattr(hm, "get_hitl_manager", lambda: _FakeHitl())

    async def _fake_human(**kwargs):  # noqa: ARG001
        return "description lisible"

    monkeypatch.setattr(hd, "build_human_hitl_description", _fake_human)

    async def _no_acl(_uid, _tool):  # noqa: ARG001
        return None

    monkeypatch.setattr(ta, "check_tool_access", _no_acl)
    return vu


@pytest.mark.asyncio
async def test_mission_une_approbation_de_tache_ne_dispense_pas_un_passe_plat(
    monkeypatch,
):
    """La clé de tâche est le mission_id : sans cette garde, un seul clic au
    premier tick dispensait tous les suivants, y compris non supervisés."""
    mission_id = "m-passe-plat"
    task_approvals.clear_task_approvals(mission_id)
    task_approvals.approve_tool_for_task(mission_id, _PASSE_PLAT)
    vu = _patch_mission(
        monkeypatch, _PASSE_PLAT, decision="allow", hitl_doit_etre_appele=True,
    )
    try:
        out, ok = await mnodes.dispatch_tool(
            _PASSE_PLAT, {}, "tc1", "user-approb", mission_id=mission_id,
        )
        assert vu["demande"] is True, (
            "la confirmation doit être redemandée malgré l'approbation de tâche"
        )
        assert ok is True and out == "EXECUTED"
    finally:
        task_approvals.clear_task_approvals(mission_id)


@pytest.mark.asyncio
async def test_mission_une_approbation_de_tache_dispense_un_dangereux_ordinaire(
    monkeypatch,
):
    mission_id = "m-ordinaire"
    task_approvals.clear_task_approvals(mission_id)
    task_approvals.approve_tool_for_task(mission_id, _DANGEREUX_ORDINAIRE)
    _patch_mission(
        monkeypatch, _DANGEREUX_ORDINAIRE, decision=None,
        hitl_doit_etre_appele=False,
    )
    try:
        out, ok = await mnodes.dispatch_tool(
            _DANGEREUX_ORDINAIRE, {}, "tc1", "user-approb", mission_id=mission_id,
        )
        assert ok is True and out == "EXECUTED"
    finally:
        task_approvals.clear_task_approvals(mission_id)


# ── « Toujours autoriser » : le journal suit l'écriture réelle ───────────────
@pytest.mark.asyncio
async def test_le_journal_de_toujours_autoriser_consulte_le_retour_de_l_ecriture(
    monkeypatch, caplog,
):
    """Le refus d'écriture ne doit pas être journalisé « now always-allowed ».

    On teste le COMPORTEMENT : le retour de ``set_user_preference`` est
    consulté. Le faux service renvoie False (dispense refusée) alors que
    l'appel réussit — un journal qui ignore ce retour dirait quand même que
    l'outil est désormais toujours autorisé, c'est-à-dire l'inverse.
    """
    import logging

    import app.services.hitl_preferences as hp

    async def _refuse(user_id, tool_name, *, requires_confirmation):  # noqa: ARG001
        return False

    monkeypatch.setattr(hp, "set_user_preference", _refuse)
    _patch_mission(
        monkeypatch, _PASSE_PLAT, decision="allow_always",
        hitl_doit_etre_appele=True,
    )
    with caplog.at_level(logging.INFO, logger="app.services.tool_gateway"):
        out, ok = await mnodes.dispatch_tool(
            _PASSE_PLAT, {}, "tc1", "user-approb", mission_id="m-journal",
        )
    assert ok is True and out == "EXECUTED"
    messages = [r.getMessage() for r in caplog.records]
    assert not any("now always-allowed" in m for m in messages), (
        "rien n'a été écrit : le journal ne doit pas affirmer le contraire"
    )
    assert any("NON enregistree" in m for m in messages), (
        "le refus d'écriture doit laisser une trace"
    )


# ── Le refus du noyau ne conseille plus un geste impossible ─────────────────
def _patch_mission_autonome(monkeypatch, tool_name: str):
    """Mission autonome SANS mandat : le plancher NEVER_AUTONOMOUS s'applique."""
    import app.services.mission_service as ms

    _patch_mission(monkeypatch, tool_name, decision=None, hitl_doit_etre_appele=False)

    async def _pas_de_mandat(_mid):  # noqa: ARG001
        return None

    class _MissionAutonome:
        autonomous = True

    async def _get_mission(_mid):  # noqa: ARG001
        return _MissionAutonome()

    monkeypatch.setattr(ms, "load_active_mandate", _pas_de_mandat)
    monkeypatch.setattr(ms, "get_mission", _get_mission)


@pytest.mark.asyncio
async def test_le_refus_autonome_ne_conseille_pas_la_pre_autorisation_impossible(
    monkeypatch,
):
    """Depuis le 02/09, l'API répond 403 sur cette dispense : la conseiller
    envoyait l'utilisateur (et le modèle qui lit ce refus) dans une impasse."""
    _patch_mission_autonome(monkeypatch, _PASSE_PLAT)
    out, ok = await mnodes.dispatch_tool(
        _PASSE_PLAT, {}, "tc1", "user-approb", mission_id="m-autonome-raw",
    )
    assert ok is False
    assert "Toujours autoriser" not in out
    assert "Tick supervisé" in out


@pytest.mark.asyncio
async def test_le_refus_autonome_conseille_encore_la_pre_autorisation_possible(
    monkeypatch,
):
    _patch_mission_autonome(monkeypatch, _DANGEREUX_ORDINAIRE)
    out, ok = await mnodes.dispatch_tool(
        _DANGEREUX_ORDINAIRE, {}, "tc1", "user-approb", mission_id="m-autonome-ord",
    )
    assert ok is False
    assert "Toujours autoriser" in out


# ── L'écriture : « Autoriser pour cette tâche » n'enregistre rien ────────────
@pytest.mark.asyncio
async def test_mission_le_choix_pour_cette_tache_n_enregistre_pas_un_passe_plat(
    monkeypatch,
):
    """Refuser à l'écriture évite de laisser croire que c'est réglé : sans ça,
    le registre garderait une entrée que la lecture ignore de toute façon."""
    mission_id = "m-ecriture"
    task_approvals.clear_task_approvals(mission_id)
    _patch_mission(
        monkeypatch, _PASSE_PLAT, decision="allow_for_task",
        hitl_doit_etre_appele=True,
    )
    try:
        out, ok = await mnodes.dispatch_tool(
            _PASSE_PLAT, {}, "tc1", "user-approb", mission_id=mission_id,
        )
        assert ok is True and out == "EXECUTED"
        assert task_approvals.is_tool_approved_for_task(
            mission_id, _PASSE_PLAT
        ) is False
    finally:
        task_approvals.clear_task_approvals(mission_id)
