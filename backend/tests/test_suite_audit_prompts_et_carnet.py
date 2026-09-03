# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_suite_audit_prompts_et_carnet.py
# @brief      Suite de l'audit (03/09) : la mémoire ne retient pas l'état des
#             tâches, le juge exige la relecture, le carnet survit à la
#             compaction.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Trois restes du plan « Modifier / Ajouter » de l'audit, vérifiés absents
le 03/09/2026 :

- item 6 : « état des tâches interdit en mémoire » — aucune clause dans les
  prompts d'extraction et de consolidation ;
- item 12 : « relecture après écriture, dans le prompt ET dans le juge » —
  le prompt l'avait, le juge non ;
- item 13 : « outil todo réinjecté quand le contexte est réduit » — le
  module l'annonçait comme non livré.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.tool_context import CURRENT_CONVERSATION_ID


# ── La mémoire retient qui est l'utilisateur, pas où en est le travail ───────

@pytest.mark.parametrize("module, nom", [
    ("app.services.memory_service", "_EXTRACTION_PROMPT"),
    ("app.services.memory_service", "_CONSOLIDATION_PROMPT"),
    ("app.services.memory.maintenance_rapid", "_EXTRACTION_PROMPT"),
])
def test_les_prompts_de_memoire_interdisent_l_etat_des_taches(module, nom):
    import importlib

    prompt = getattr(importlib.import_module(module), nom)
    bas = prompt.lower()
    assert "état d'une tâche" in bas or "etat d'une tache" in bas, nom
    assert "avancement" in bas, nom


# ── Le juge demande si la cible a été relue ──────────────────────────────────

def test_le_juge_exige_la_relecture_apres_une_ecriture_externe():
    from app.agent.conformity import _JUDGE_PROMPT

    bas = _JUDGE_PROMPT.lower()
    assert "relu" in bas or "relue" in bas
    assert "appel d'outil" in bas


# ── Le carnet survit à la compaction ─────────────────────────────────────────

@pytest.fixture
def _conv():
    token = CURRENT_CONVERSATION_ID.set("conv-compaction")
    try:
        yield "conv-compaction"
    finally:
        CURRENT_CONVERSATION_ID.reset(token)


@pytest.mark.asyncio
async def test_les_etapes_restantes_sont_rendues_sans_les_faites(_conv):
    from app.agent.tools.todo_tool import etapes_restantes, session_todo

    await session_todo.ainvoke({"taches": ["Lister", "Trier", "Archiver"]})
    await session_todo.ainvoke({"faites": [1], "en_cours": 2})

    rendu = etapes_restantes(_conv)
    assert "Lister" not in rendu
    assert "2. [>] Trier" in rendu
    assert "3. [ ] Archiver" in rendu


def test_sans_plan_rien_n_est_rendu():
    from app.agent.tools.todo_tool import etapes_restantes

    assert etapes_restantes("conv-inconnue") == ""
    assert etapes_restantes("") == ""


@pytest.mark.asyncio
async def test_le_plan_est_reinjecte_quand_le_contexte_est_tronque(_conv, monkeypatch):
    from app.agent.tools.todo_tool import session_todo
    from app.services import context_manager as cm

    await session_todo.ainvoke({"taches": ["Lister les factures", "Les ranger dans Drive"]})
    await session_todo.ainvoke({"faites": [1], "en_cours": 2})

    # Fenêtre minuscule : les premiers messages sont forcément tronqués. Le
    # résumé local des messages perdus est neutralisé pour isoler ce qu'on
    # teste : le plan, lui, doit tenir et arriver.
    monkeypatch.setattr(cm, "get_context_window", lambda model: 700)
    monkeypatch.setattr(cm, "_summarise_dropped", lambda dropped: "")
    messages = []
    for i in range(12):
        messages.append(HumanMessage(content=f"message {i} " + "blabla " * 40))
        messages.append(AIMessage(content=f"réponse {i} " + "ok " * 40))

    # Comme le nœud agent : l'identifiant est PASSÉ. LangGraph exécute chaque
    # nœud dans sa propre tâche, la ContextVar posée dans le nœud d'outils
    # n'y est pas visible (relecture du 03/09/2026).
    CURRENT_CONVERSATION_ID.set("")
    garde = cm.fit_messages_to_context(messages, "système", model="test-model",
                                       reserve_for_response=100,
                                       conversation_id=_conv)

    assert len(garde) < len(messages)
    texte = " ".join(
        str(m.content) for m in garde if isinstance(m, HumanMessage)
    )
    assert "Les ranger dans Drive" in texte
    assert "Lister les factures" not in texte, "une étape faite ne doit pas être refaite"


@pytest.mark.asyncio
async def test_sans_troncature_le_plan_n_est_pas_injecte(_conv):
    from app.agent.tools.todo_tool import session_todo
    from app.services import context_manager as cm

    await session_todo.ainvoke({"taches": ["Une étape"]})
    messages = [HumanMessage(content="salut"), AIMessage(content="bonjour")]

    garde = cm.fit_messages_to_context(messages, "système", model="test-model")

    assert [m.content for m in garde] == ["salut", "bonjour"]


def test_le_noeud_agent_passe_l_identifiant_a_la_compaction():
    """``CURRENT_CONVERSATION_ID`` n'est posée que dans le nœud d'outils ; le
    nœud agent doit donc PASSER ``conversation_id`` aux deux appels de
    ``fit_messages_to_context`` (chemin SLM et chemin général)."""
    import inspect

    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    debuts = [i for i in range(len(src)) if src.startswith("fit_messages_to_context(", i)]
    assert len(debuts) == 2, "deux appels attendus (chemin SLM, chemin général)"
    for i in debuts:
        appel = src[i:src.index(")\n", i) + 1]
        assert "conversation_id=_conv_id_fb" in appel, appel
