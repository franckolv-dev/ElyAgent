# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_scheduled_task_tool_binding.py
# @brief      Regression: a multi-domain scheduled task (calendar + gmail +
#             system) must be able to bind every tool its prompt names.
# @license    MIT
# =============================================================================
"""Pin the scheduled-task multi-domain tool-binding fix (2026-05-31).

Bug
---
« Briefing quotidien 9h » (prod task f3a63395) reported every morning that
the calendar and inbox were « non disponible pour cet agent » while the
scheduled-tasks section worked fine. Root cause: the scheduler ran the
prompt through the multi-agent **supervisor**, which routes a whole prompt
to ONE sub-agent. The phrase « mes taches planifiees » tripped the ``diag``
route, so the briefing executed inside the diag sub-agent, which only binds
``system_*`` tools — every ``calendar_*`` / ``gmail_*`` call the prompt
asked for hit the « outil non disponible » branch.

Fix (Option 1) — scheduled tasks now run on the FLAT graph with
``automated_task=True``, and ``create_agent_node`` unions in every tool
whose exact name appears in the prompt. The naive « just use the flat
graph » idea was NOT enough: the flat graph's legacy keyword filter
(``filter_tools_by_query``) is accent/word-boundary fragile and, on this
very prompt, drops ``calendar_list_events`` and ``system_list_scheduled_tasks``
while keeping ``gmail_list_emails``. These tests pin both halves: the filter
gap (so we don't « fix » it by accident and forget why) and the union that
closes it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tool_filter import filter_tools_by_query, tools_named_in_text

_REPO = Path(__file__).resolve().parents[1]
_NODES_PY = (_REPO / "app" / "agent" / "nodes.py").read_text(encoding="utf-8")
_SCHEDULER_PY = (_REPO / "app" / "services" / "scheduler.py").read_text(encoding="utf-8")


# The EXACT prod prompt of task f3a63395 (accent-less, as the user wrote it).
_BRIEFING_PROMPT = (
    "Genere mon briefing du matin. APPELLE ces tools DANS L'ORDRE et rapporte "
    "UNIQUEMENT ce qu'ils retournent (pas d'invention) :\n"
    "1. calendar_list_events pour les evenements du jour\n"
    "2. gmail_list_emails pour les mails non lus recus depuis hier soir\n"
    "3. system_list_scheduled_tasks pour mes taches planifiees du jour\n"
    "Si un tool n'est pas disponible OU retourne vide, dis-le clairement "
    '("aucun evenement", "boite vide").'
)

_NAMED_TOOLS = (
    "calendar_list_events",
    "gmail_list_emails",
    "system_list_scheduled_tasks",
)


@pytest.fixture(scope="module", autouse=True)
def _registry():
    """Populate the global SkillRegistry once for this module."""
    from app.skills.builtin import register_all

    register_all()
    from app.skills import get_skill_registry

    return get_skill_registry()


# ─────────────────────────────────────────────────────────────────────────
# tools_named_in_text — the literal-name matcher
# ─────────────────────────────────────────────────────────────────────────


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_named_matcher_picks_exact_names():
    tools = [_FakeTool(n) for n in _NAMED_TOOLS] + [_FakeTool("drive_list_files")]
    got = {t.name for t in tools_named_in_text(tools, _BRIEFING_PROMPT)}
    assert got == set(_NAMED_TOOLS)  # drive_list_files is not named → excluded


def test_named_matcher_respects_underscore_boundaries():
    """A tool name must not match when it is only a PREFIX of the token in
    the text (underscore is a word char, so plain \\b would be wrong)."""
    tools = [_FakeTool("calendar_list"), _FakeTool("calendar_list_events")]
    # Text only contains the longer name.
    got = {t.name for t in tools_named_in_text(tools, "appelle calendar_list_events")}
    assert got == {"calendar_list_events"}


def test_named_matcher_is_accent_and_case_insensitive_on_name():
    tools = [_FakeTool("Gmail_List_Emails")]
    got = tools_named_in_text(tools, "lance gmail_list_emails stp")
    assert [t.name for t in got] == ["Gmail_List_Emails"]


def test_named_matcher_empty_text():
    assert tools_named_in_text([_FakeTool("x")], "") == []


# ─────────────────────────────────────────────────────────────────────────
# Regression — the filter gap and the union that closes it
# ─────────────────────────────────────────────────────────────────────────


def test_keyword_filter_alone_drops_calendar_and_system(_registry):
    """Documents WHY the naive 'route via flat graph' fix is insufficient:
    the legacy keyword filter silently loses 2 of the 3 named tools."""
    tools = _registry.all_tools
    filtered = {t.name for t in filter_tools_by_query(tools, _BRIEFING_PROMPT)}
    # gmail survives (matched via "mails")…
    assert "gmail_list_emails" in filtered
    # …but calendar and system are dropped — this is the bug.
    assert "calendar_list_events" not in filtered
    assert "system_list_scheduled_tasks" not in filtered


def test_named_union_binds_all_three_domains(_registry):
    """The fix: filter ∪ named-in-prompt binds every tool the briefing asks
    for, across all three domains (workspace + workspace + diag)."""
    tools = _registry.all_tools
    filtered = filter_tools_by_query(tools, _BRIEFING_PROMPT)
    named = tools_named_in_text(tools, _BRIEFING_PROMPT)
    have = {t.name for t in filtered}
    have |= {t.name for t in named}
    for name in _NAMED_TOOLS:
        assert name in have, f"{name} must be bound for the briefing to work"


def test_named_tools_actually_exist_in_registry(_registry):
    """Guard: if a future rename breaks one of these tool names, the union
    can't bind it — fail loudly here rather than silently in prod."""
    all_names = {t.name for t in _registry.all_tools}
    for name in _NAMED_TOOLS:
        assert name in all_names, f"{name} no longer registered"


# ─────────────────────────────────────────────────────────────────────────
# Wiring guards — the binding logic lives inside the create_agent_node
# closure (not importable) and across the scheduler. Source-grep pins,
# following the same convention as test_tool_kw_regex.py.
# ─────────────────────────────────────────────────────────────────────────


def test_scheduler_uses_flat_graph_with_automated_flag():
    """The scheduler must drive the FLAT graph and flag the run automated —
    otherwise the supervisor re-routes the whole prompt to one sub-agent."""
    assert "build_simple_agent_graph" in _SCHEDULER_PY
    assert '"automated_task": True' in _SCHEDULER_PY
    # And it must NOT silently fall back to the supervisor builder.
    assert "build_agent_graph()" not in _SCHEDULER_PY


def test_nodes_honours_automated_task_flag():
    """create_agent_node must (1) skip the SLM, (2) force tool binding and
    (3) union in the named tools when automated_task is set."""
    # SLM gate.
    assert 'not state.get("automated_task")' in _NODES_PY
    # Bind-flag gate.
    assert 'bool(state.get("automated_task"))' in _NODES_PY
    # Named-tool union.
    assert "tools_named_in_text" in _NODES_PY


# ─────────────────────────────────────────────────────────────────────────
# Régression 13/06 — l'union doit se baser sur le PROMPT INITIAL, pas sur
# le dernier message (= résultat du tool au tour 2+), et le mode automated
# doit interdire les questions / la re-planification.
# ─────────────────────────────────────────────────────────────────────────


# Prompt « Daily » en LANGAGE NATUREL — ne nomme AUCUN outil (≠ Briefing).
# C'est le cas que l'union seule ne rattrape pas : seul le re-filtrage sur le
# prompt initial à chaque tour le sauve.
_DAILY_PROMPT = (
    "Chaque jour, prépare et envoie-moi sur Telegram un daily contenant :\n"
    "1) Mes rendez-vous Google Calendar du jour.\n"
    "2) Les emails reçus dans les dernières 24h, avec expéditeur et objet.\n"
    "3) Une recherche sur les news IA, LLM et petits modèles locaux du jour.\n"
    "4) L'horoscope du jour.\n"
    "5) La météo du jour à Chasseneuil-du-Poitou."
)


def test_tool_result_text_names_no_tool_hence_the_bug(_registry):
    """Cœur du bug : au tour 2, messages[-1] est le RÉSULTAT du tool du tour
    1. Aucun nom d'outil n'y figure → une union basée dessus retombe à vide
    et les outils du prompt disparaissent du binding. Révélé par codex
    (parallel_tool_calls=False → 1 outil/tour, donc on ATTEINT le tour 2)."""
    tools = _registry.all_tools
    # Ce que calendar_list_events renvoie — devenu le "user_query" buggé :
    tool_result_text = (
        "1 événement(s):\n• Entraînement tennis de table — "
        "2026-06-13T10:00:00+02:00\n  Lieu: Non spécifié"
    )
    named_from_result = {t.name for t in tools_named_in_text(tools, tool_result_text)}
    assert "gmail_list_emails" not in named_from_result
    assert "system_list_scheduled_tasks" not in named_from_result
    # …alors qu'ils SONT nommés dans le prompt initial.
    named_from_prompt = {t.name for t in tools_named_in_text(tools, _BRIEFING_PROMPT)}
    assert {"gmail_list_emails", "system_list_scheduled_tasks"} <= named_from_prompt


def test_keyword_filter_on_prompt_keeps_tools_lost_on_tool_result(_registry):
    """Le FILTRE PRINCIPAL (pas juste l'union) doit repartir du prompt à
    chaque tour. Sur le prompt Daily (langage naturel) il garde gmail + web ;
    sur le RÉSULTAT d'un tool il les perd → d'où « aucun outil pour les
    mails/news » au tour 2 (bug terrain 13/06, prompt sans noms d'outils que
    l'union ne couvre pas)."""
    tools = _registry.all_tools
    from_prompt = {t.name for t in filter_tools_by_query(tools, _DAILY_PROMPT)}
    assert "gmail_list_emails" in from_prompt
    assert ("web_search" in from_prompt or "web_search_news" in from_prompt)

    tool_result = (
        "1 événement(s):\n• Entraînement tennis de table — "
        "2026-06-13T10:00:00+02:00"
    )
    from_result = {t.name for t in filter_tools_by_query(tools, tool_result)}
    assert "gmail_list_emails" not in from_result  # perdu si on filtre sur le résultat
    assert "web_search" not in from_result


def test_nodes_filter_query_bases_on_initial_prompt():
    """Source-grep : en automated_task, le FILTRE principal ET l'union se
    basent sur _filter_query, qui dérive du PREMIER message humain (prompt
    initial) — pas de user_query (= dernier message)."""
    assert 'getattr(m, "type", None) == "human"' in _NODES_PY
    # _filter_query : défini (défaut user_query) puis réutilisé par le filtre
    # ET l'union → au moins 3 occurrences.
    assert "_filter_query = user_query" in _NODES_PY
    assert _NODES_PY.count("_filter_query") >= 3
    # L'union consomme _filter_query (plus _initial_prompt isolé).
    assert "tools_named_in_text(registry.all_tools, _filter_query)" in _NODES_PY


def test_nodes_has_automated_execution_guardrail():
    """Source-grep : en automated_task, le system prompt force l'exécution et
    interdit questions / re-planification (bug 13/06 : daily demandait l'heure
    au lieu d'exécuter, et 2 tâches dupliquées se recréaient)."""
    assert "EXÉCUTION AUTOMATIQUE PROGRAMMÉE" in _NODES_PY
