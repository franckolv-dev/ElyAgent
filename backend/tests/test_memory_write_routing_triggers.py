# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_memory_write_routing_triggers.py
# @brief      Bug terrain 2026-06-12 — « retiens mes URLs » n'appelait JAMAIS
#             d'outil : memory_archive n'avait pas de phrases déclencheurs et
#             aucun outil ne relisait le profil. Pins des 3 surfaces.
# @license    Elastic License 2.0
# =============================================================================
"""Le LLM choisit ses outils par les DÉCLENCHEURS du docstring, pas par
l'architecture de stockage. 7-8 « enregistre mes profils sociaux » ont produit
7-8 confirmations hallucinées (attrapées par completion_guard) parce que :
(1) memory_archive décrivait le COMMENT (Qdrant, injection) au lieu du QUAND ;
(2) « affiche mes préférences » n'avait aucun outil de lecture.

Run with:  cd backend && python -m pytest tests/test_memory_write_routing_triggers.py -v
"""
from __future__ import annotations

import pytest

from app.agent.tools.memgpt_tool import memory_archive, memory_view_profile
from app.agent.tools.memory_tool import save_user_preference


# ── Pins de déclencheurs (la surface que lit le LLM) ─────────────────────────

class TestArchiveTriggers:
    def test_user_intent_triggers_present(self):
        """Les verbes que l'utilisateur emploie réellement DOIVENT être dans
        la description — c'est par eux que le modèle route."""
        desc = memory_archive.description
        for trigger in ("retiens", "enregistre", "souviens-toi", "mémorise"):
            assert trigger in desc.lower(), f"déclencheur {trigger!r} absent"

    def test_url_example_present(self):
        """Le cas terrain exact (URLs de profils sociaux) doit figurer en
        exemple — c'est lui qui a échoué 8 fois."""
        desc = memory_archive.description
        assert "profils sociaux" in desc and "https://" in desc

    def test_no_lying_rule_present(self):
        """La règle « jamais confirmer sans appel réel » est dans le contrat
        de l'outil, en plus du completion_guard côté sortie."""
        assert "ne JAMAIS confirmer" in memory_archive.description

    def test_cross_reference_from_preference_tool(self):
        """save_user_preference renvoie vers memory_archive pour les FAITS —
        le routage d'écriture est bidirectionnel."""
        assert "memory_archive" in save_user_preference.description


# ── memory_view_profile : la relecture qui manquait ──────────────────────────

class _FakeStore:
    def __init__(self, prefs):
        self._prefs = prefs

    async def get_preferences(self, user_id, limit=10):
        return self._prefs


class TestViewProfile:
    def test_read_triggers_present(self):
        desc = memory_view_profile.description
        assert "affiche mes préférences" in desc
        assert "qu'est-ce que tu sais de moi" in desc

    @pytest.mark.asyncio
    async def test_lists_stored_preferences(self, monkeypatch):
        import app.agent.tools.memgpt_tool as memgpt
        monkeypatch.setattr(
            memgpt, "get_semantic_user_store",
            lambda: _FakeStore(["Tutoyer l'utilisateur", "Réponses concises"]),
        )
        out = await memory_view_profile.coroutine(user_id="u1")
        assert "2" in out
        assert "Tutoyer l'utilisateur" in out and "Réponses concises" in out

    @pytest.mark.asyncio
    async def test_empty_profile_says_so(self, monkeypatch):
        import app.agent.tools.memgpt_tool as memgpt
        monkeypatch.setattr(memgpt, "get_semantic_user_store", lambda: _FakeStore([]))
        out = await memory_view_profile.coroutine(user_id="u1")
        assert "Aucune préférence" in out

    @pytest.mark.asyncio
    async def test_no_user_id_fails_closed(self):
        out = await memory_view_profile.coroutine(user_id="")
        assert "Échec" in out


# ── Câblage : l'outil est réellement exposé ──────────────────────────────────

class TestWiring:
    def test_in_default_profile(self):
        from app.agent.toolset_profiles import _DEFAULT_TOOLS
        assert "memory_view_profile" in _DEFAULT_TOOLS

    def test_in_always_keep(self):
        from app.agent.tool_filter import ALWAYS_KEEP
        assert "memory_view_profile" in ALWAYS_KEEP

    def test_in_memory_skill(self):
        import app.skills.builtin.memory_skill as ms
        assert hasattr(ms, "memory_view_profile") or "memory_view_profile" in open(ms.__file__).read()
