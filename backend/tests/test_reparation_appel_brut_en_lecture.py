# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reparation_appel_brut_en_lecture.py
# @brief      Un appel brut à l'API Google qui LIT n'est ni un acte engageant
#             ni une action à confirmer ; un appel brut qui ÉCRIT le reste.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Réparation post-audit (03/09/2026).

Le 02/09 (``3fb4c6c``), les sept ``*_raw_api_call`` sont devenus non
dispensables : ni « Toujours autoriser », ni « Pour cette tâche » ne les
éteignent. Juste pour ``users.messages.modify`` ou ``users.settings.*`` —
un passe-plat refait tout ce que font les autres outils Google.

Mais la production du 03/09 montre ce que ça coûte quand l'appel LIT :

    06:17:36  HITL required: gmail_raw_api_call users.messages.get
    06:17:41  POST /api/validation/…/allow_always → « dispense refusée »
    06:17:51  HITL required: gmail_raw_api_call users.messages.get
    06:19:41  HITL required: gmail_raw_api_call users.messages.get   …

Le nettoyage Gmail de Franck enchaîne des dizaines de ``messages.list`` et
``messages.get`` : chacun redemande un clic, et le clic « toujours » est
refusé. Pire, la garde anti-rejeu (#321) classe l'outil ENGAGEANT par son
NOM : après une relance de conformité, elle retirait ``gmail_raw_api_call``
du branchement alors qu'il n'avait fait que lire — le modèle ne pouvait
plus analyser les catégories qu'on lui reprochait d'avoir sautées.

La règle : la nature d'un passe-plat est celle de la MÉTHODE qu'il appelle.
Une lecture (``list``, ``get``, ``search``, ``export``…) ne demande rien et
se rejoue sans risque ; tout le reste garde exactement le régime du 02/09.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.services.security_filter import SecurityFilter
from app.services.tool_gateway import GatewayContext, _decide_hitl


# ── La méthode dit la nature ─────────────────────────────────────────────────

@pytest.mark.parametrize("methode", [
    "users.messages.list", "users.messages.get", "users.labels.list",
    "users.getProfile", "users.threads.get", "events.list", "events.instances",
    "freebusy.query", "files.list", "files.get", "files.export",
    "spreadsheets.values.get", "spreadsheets.values.batchGet",
    "people.searchContacts", "people.connections.list", "tasks.list",
    "documents.get",
])
def test_une_methode_qui_lit_est_reconnue(methode):
    from app.services.google_raw_api import est_une_lecture

    assert est_une_lecture(methode) is True


@pytest.mark.parametrize("methode", [
    "users.messages.modify", "users.messages.trash", "users.messages.delete",
    "users.messages.send", "users.messages.batchModify", "users.labels.create",
    "users.settings.filters.create", "users.settings.updateVacation",
    "events.insert", "events.delete", "files.create", "files.update",
    "permissions.create", "spreadsheets.values.update",
    "spreadsheets.values.append", "people.deleteContact", "tasks.patch",
    "documents.batchUpdate", "", "   ", "list",
])
def test_tout_le_reste_est_une_ecriture(methode):
    from app.services.google_raw_api import est_une_lecture

    assert est_une_lecture(methode) is False


# ── La passerelle : pas de confirmation pour une lecture ─────────────────────

def _ctx(conv: str) -> GatewayContext:
    return GatewayContext(
        user_id="user-lecture",
        conversation_id=conv,
        pii_filter=None,
        criticality_filter=SecurityFilter(),
        hitl=None,
        memory=None,
    )


@pytest.mark.asyncio
async def test_un_appel_brut_qui_lit_ne_demande_pas_confirmation():
    args = {"method_path": "users.messages.list",
            "params_json": '{"userId":"me","q":"in:spam -in:trash","maxResults":500}'}
    assert await _decide_hitl(_ctx("conv-lecture"), "gmail_raw_api_call", args, args) is False


@pytest.mark.asyncio
async def test_un_appel_brut_qui_ecrit_demande_toujours_confirmation():
    args = {"method_path": "users.messages.batchModify",
            "params_json": '{"userId":"me"}'}
    assert await _decide_hitl(_ctx("conv-ecriture"), "gmail_raw_api_call", args, args) is True


@pytest.mark.asyncio
async def test_sans_methode_lisible_l_appel_brut_reste_confirme():
    """Un passe-plat sans ``method_path`` (ou avec un chemin illisible) ne
    bénéficie d'aucune exemption : l'incertitude se paie d'un clic."""
    assert await _decide_hitl(_ctx("conv-vide"), "gmail_raw_api_call", {}, {}) is True
    args = {"method_path": 42}
    assert await _decide_hitl(_ctx("conv-vide"), "gmail_raw_api_call", args, args) is True


# ── La garde anti-rejeu : une lecture n'est pas un acte ──────────────────────

def _appel(nom: str, cid: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": nom, "args": args, "id": cid}])


def _retour(cid: str, texte: str = "✓ ok") -> ToolMessage:
    return ToolMessage(content=texte, tool_call_id=cid, status="success")


def test_un_appel_brut_qui_a_lu_n_est_pas_un_acte_accompli():
    from app.agent.replay_guard import engaging_actions_done

    messages = [
        _appel("gmail_raw_api_call", "c1", method_path="users.messages.list"),
        _retour("c1"),
        _appel("gmail_raw_api_call", "c2", method_path="users.messages.get"),
        _retour("c2"),
    ]
    assert engaging_actions_done(messages) == set()


def test_un_appel_brut_qui_a_ecrit_reste_un_acte_accompli():
    from app.agent.replay_guard import engaging_actions_done

    messages = [
        _appel("gmail_raw_api_call", "c1", method_path="users.messages.list"),
        _retour("c1"),
        _appel("gmail_raw_api_call", "c2", method_path="users.messages.trash"),
        _retour("c2"),
    ]
    assert engaging_actions_done(messages) == {"gmail_raw_api_call"}


def test_un_appel_brut_sans_methode_reste_un_acte_accompli():
    from app.agent.replay_guard import engaging_actions_done

    messages = [_appel("gmail_raw_api_call", "c1"), _retour("c1")]
    assert engaging_actions_done(messages) == {"gmail_raw_api_call"}


# ── Le chemin des MISSIONS court-circuite la passerelle : même règle ─────────
#
# ``missions/nodes.dispatch_tool`` calcule son propre ``needs_hitl`` et le
# passe en ``needs_hitl_final`` à la passerelle, qui ne redécide rien. La
# règle doit donc y vivre aussi (relecture du 03/09/2026 : elle n'y était pas).

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


def _patch_mission(monkeypatch, tool_name: str, *, hitl_doit_etre_appele: bool):
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
                raise AssertionError("la confirmation ne devait PAS être demandée")
            return "allow", None

    monkeypatch.setattr(hm, "get_hitl_manager", lambda: _FakeHitl())

    async def _fake_human(**kwargs):  # noqa: ARG001
        return "description lisible"

    monkeypatch.setattr(hd, "build_human_hitl_description", _fake_human)

    async def _no_acl(_uid, _tool):  # noqa: ARG001
        return None

    monkeypatch.setattr(ta, "check_tool_access", _no_acl)
    return vu


@pytest.mark.asyncio
async def test_mission_un_appel_brut_qui_lit_ne_demande_pas_confirmation(monkeypatch):
    from app.agent.missions import nodes as mnodes

    vu = _patch_mission(monkeypatch, "gmail_raw_api_call", hitl_doit_etre_appele=False)
    out, ok = await mnodes.dispatch_tool(
        "gmail_raw_api_call",
        {"method_path": "users.messages.list", "params_json": '{"userId":"me"}'},
        "tc1", "user-lecture", mission_id="m-lecture",
    )
    assert vu["demande"] is False
    assert ok is True and out == "EXECUTED"


@pytest.mark.asyncio
async def test_mission_un_appel_brut_qui_ecrit_demande_confirmation(monkeypatch):
    from app.agent.missions import nodes as mnodes

    vu = _patch_mission(monkeypatch, "gmail_raw_api_call", hitl_doit_etre_appele=True)
    out, ok = await mnodes.dispatch_tool(
        "gmail_raw_api_call",
        {"method_path": "users.messages.trash", "params_json": '{"userId":"me"}'},
        "tc2", "user-ecriture", mission_id="m-ecriture",
    )
    assert vu["demande"] is True
    assert ok is True and out == "EXECUTED"
