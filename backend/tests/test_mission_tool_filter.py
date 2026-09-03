# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_tool_filter.py
# @brief      Missions — filtre d'outils par step : matching lexical
#             accent-insensible + re-rank sémantique hybride (RAG d'outils).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du filtre `_filter_tools_for_step` (missions/nodes.py).

Deux fragilités historiques couvertes ici :
  - accents : « ajoute un evenement » (sans accent) ne matchait pas le
    mot-clé « ajoute un événement » → mauvais outil bindé (incident
    scheduler du 31 mai 2026) ;
  - paraphrases : « préviens-moi sur mon téléphone » ne contient aucun
    mot-clé telegram_* → le step partait sans le bon outil.

Les embeddings sont mockés (vecteurs orthogonaux) pour des cosines exacts —
même pattern que test_find_tool. Aucun modèle FastEmbed réel n'est chargé.
"""
from __future__ import annotations

import pytest

import app.agent.missions.nodes as mn


class _T:
    """Outil minimal — le filtre ne lit que .name et .description."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


def _catalog() -> list[_T]:
    return [
        _T("telegram_send_message", "Envoyer un message Telegram instantane a l'utilisateur."),
        _T("calendar_create_event", "Creer un evenement dans Google Calendar."),
        _T("gmail_send_email", "Envoyer un e-mail via Gmail."),
        _T("drive_list_files", "Lister les fichiers Google Drive."),
        _T("web_search", "Recherche internet."),
        _T("web_extract", "Lire le texte visible d'une page internet."),
        _T("smart_knowledge_query", "Interroger la base documentaire."),
        _T("find_tool", "Trouver un outil ELY pour une capacite manquante."),
    ]


def _mock_semantic(monkeypatch, vectors: dict[str, list[float]], query_vec: list[float]):
    """Court-circuite le build du catalogue + l'embed de la requête."""

    async def _noop(all_tools):  # noqa: ARG001
        return

    monkeypatch.setattr(mn, "_ensure_tool_embeddings", _noop)
    monkeypatch.setattr(mn, "_tool_vectors", vectors)
    monkeypatch.setattr(
        mn, "_tool_text_norm",
        {name: mn._norm(name) for name in vectors},
    )

    class _FakeInfra:
        async def embed(self, text):  # noqa: ARG002
            return query_vec

    monkeypatch.setattr("app.services.memory.get_memory_infra", lambda: _FakeInfra())


# ── _norm — la normalisation qui fixe la fragilité aux accents ───────────────


def test_norm_strips_accents_and_case():
    assert mn._norm("Événement Créé À 9h") == "evenement cree a 9h"
    assert mn._norm("") == ""
    assert mn._norm(None) == ""


# ── lexical accent-insensible (sémantique coupé via kill-switch) ─────────────


@pytest.mark.asyncio
async def test_action_keywords_match_without_accents(monkeypatch):
    """« ajoute un evenement » (sans accent) doit booster calendar_create_event.

    Avant le fix, le mot-clé déclaré « ajoute un événement » (accentué) ne
    matchait pas ce goal — c'est la classe de bug du briefing du 31 mai.
    """
    monkeypatch.setenv("MISSION_SEMANTIC_TOOLS_DISABLED", "1")
    tools = await mn._filter_tools_for_step(
        _catalog(), tool_hint=None,
        goal="Ajoute un evenement demain matin pour le dentiste",
    )
    assert tools[0].name == "calendar_create_event"


@pytest.mark.asyncio
async def test_action_keywords_match_with_accents(monkeypatch):
    """Sens inverse : goal accentué sur mot-clé déclaré sans accent."""
    monkeypatch.setenv("MISSION_SEMANTIC_TOOLS_DISABLED", "1")
    tools = await mn._filter_tools_for_step(
        _catalog(), tool_hint=None, goal="Crée un rendez-vous vendredi",
    )
    assert tools[0].name == "calendar_create_event"


@pytest.mark.asyncio
async def test_kill_switch_skips_semantic_stage(monkeypatch):
    """Avec le kill-switch, l'étage sémantique n'est jamais tenté."""
    monkeypatch.setenv("MISSION_SEMANTIC_TOOLS_DISABLED", "1")

    async def _boom(all_tools):  # noqa: ARG001
        raise AssertionError("semantic stage must not run when disabled")

    monkeypatch.setattr(mn, "_ensure_tool_embeddings", _boom)
    tools = await mn._filter_tools_for_step(
        _catalog(), tool_hint=None, goal="objectif sans aucun mot-cle connu",
    )
    # Aucun signal lexical → il reste le filet générique, et `find_tool`
    # pour réclamer ce qui manque (30/08/2026).
    assert {t.name for t in tools} == mn._RESERVES


# ── re-rank sémantique hybride ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_semantic_fill_surfaces_paraphrase_tool(monkeypatch):
    """« préviens-moi sur mon téléphone » → telegram_send_message remonte.

    Zéro recouvrement lexical avec le nom/description de l'outil : seul le
    cosine (mocké aligné) peut le faire entrer dans les candidats.
    """
    _mock_semantic(
        monkeypatch,
        vectors={
            "telegram_send_message": [1.0, 0.0, 0.0],
            "calendar_create_event": [0.0, 1.0, 0.0],
            "gmail_send_email": [0.0, 1.0, 0.0],
            "drive_list_files": [0.0, 0.0, 1.0],
        },
        query_vec=[1.0, 0.0, 0.0],
    )
    tools = await mn._filter_tools_for_step(
        _catalog(), tool_hint=None,
        goal="Préviens-moi sur mon téléphone quand c'est terminé",
    )
    names = [t.name for t in tools]
    assert names[0] == "telegram_send_message"
    # Les outils orthogonaux à la requête (score < plancher) ne rentrent pas.
    assert "drive_list_files" not in names
    # Le filet générique reste présent.
    assert mn._GENERIC_TOOLS <= set(names)


@pytest.mark.asyncio
async def test_tool_hint_keeps_priority_over_semantic(monkeypatch):
    """Le tool_hint du plan reste devant les ajouts sémantiques."""
    _mock_semantic(
        monkeypatch,
        vectors={"telegram_send_message": [1.0, 0.0, 0.0]},
        query_vec=[1.0, 0.0, 0.0],
    )
    tools = await mn._filter_tools_for_step(
        _catalog(), tool_hint="gmail_send_email",
        goal="Préviens-moi sur mon téléphone quand c'est terminé",
    )
    names = [t.name for t in tools]
    assert "gmail_send_email" in names
    assert "telegram_send_message" in names
    assert names.index("gmail_send_email") < names.index("telegram_send_message")


@pytest.mark.asyncio
async def test_semantic_failure_degrades_to_lexical(monkeypatch):
    """Encodeur cassé → comportement legacy, jamais d'exception."""

    async def _boom(all_tools):  # noqa: ARG001
        raise RuntimeError("encoder unavailable")

    monkeypatch.setattr(mn, "_ensure_tool_embeddings", _boom)
    tools = await mn._filter_tools_for_step(
        _catalog(), tool_hint=None, goal="cherche sur internet les actualités",
    )
    names = [t.name for t in tools]
    assert "web_search" in names  # le boost lexical continue de fonctionner
    assert len(names) <= mn._TOOL_CAP


@pytest.mark.asyncio
async def test_cap_respected_and_generic_net_reserved(monkeypatch):
    """40 matches sémantiques → cap à 15 ET filet générique préservé."""
    fillers = [_T(f"filler_{i:02d}", "outil de remplissage") for i in range(40)]
    catalog = fillers + [
        _T("web_search", "Recherche internet."),
        _T("web_extract", "Lire le texte visible d'une page internet."),
        _T("smart_knowledge_query", "Interroger la base documentaire."),
        _T("find_tool", "Trouver un outil ELY pour une capacite manquante."),
    ]
    _mock_semantic(
        monkeypatch,
        vectors={t.name: [1.0, 0.0, 0.0] for t in fillers},
        query_vec=[1.0, 0.0, 0.0],
    )
    tools = await mn._filter_tools_for_step(
        catalog, tool_hint=None, goal="objectif vague sans mot-cle",
    )
    names = [t.name for t in tools]
    assert len(names) == mn._TOOL_CAP
    assert mn._GENERIC_TOOLS <= set(names)


# ── cache d'embeddings — invalidation sur tools_version ─────────────────────


class _Vec:
    def __init__(self, v):
        self._v = v

    def tolist(self):
        return self._v


@pytest.mark.asyncio
async def test_embeddings_cache_invalidated_on_tools_version(monkeypatch):
    calls = {"n": 0}

    class _FakeEncoder:
        def embed(self, texts):
            calls["n"] += 1
            return [_Vec([1.0, 0.0]) for _ in texts]

    class _FakeInfra:
        encoder = _FakeEncoder()

    class _FakeRegistry:
        def __init__(self):
            self._v = 7

        @property
        def tools_version(self):
            return self._v

    reg = _FakeRegistry()
    monkeypatch.setattr("app.skills.get_skill_registry", lambda: reg)
    monkeypatch.setattr("app.services.memory.get_memory_infra", lambda: _FakeInfra())
    monkeypatch.setattr(mn, "_tool_vec_version", -1)
    monkeypatch.setattr(mn, "_tool_vectors", {})
    monkeypatch.setattr(mn, "_tool_text_norm", {})

    tools = _catalog()
    await mn._ensure_tool_embeddings(tools)
    assert calls["n"] == 1
    assert set(mn._tool_vectors) == {t.name for t in tools}

    await mn._ensure_tool_embeddings(tools)
    assert calls["n"] == 1  # même version → cache, pas de re-embed

    reg._v = 8  # register/unregister (ex. hot-reload MCP) → bump
    await mn._ensure_tool_embeddings(tools)
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_embeddings_failure_marks_version_no_retry_storm(monkeypatch):
    """Encodeur KO → lexical-only ET pas de retry au step suivant."""
    calls = {"n": 0}

    class _FakeRegistry:
        tools_version = 3

    def _broken_infra():
        calls["n"] += 1
        raise RuntimeError("no encoder in this env")

    monkeypatch.setattr("app.skills.get_skill_registry", lambda: _FakeRegistry())
    monkeypatch.setattr("app.services.memory.get_memory_infra", _broken_infra)
    monkeypatch.setattr(mn, "_tool_vec_version", -1)
    monkeypatch.setattr(mn, "_tool_vectors", {})
    monkeypatch.setattr(mn, "_tool_text_norm", {})

    tools = _catalog()
    await mn._ensure_tool_embeddings(tools)
    assert mn._tool_vectors == {}
    assert mn._tool_text_norm  # le cache lexical, lui, est construit
    assert mn._tool_vec_version == 3

    await mn._ensure_tool_embeddings(tools)
    assert calls["n"] == 1  # version marquée malgré l'échec → un seul essai
