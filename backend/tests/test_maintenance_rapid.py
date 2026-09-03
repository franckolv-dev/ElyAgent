# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_maintenance_rapid.py
# @brief      Sprint 2.5 Jalon 6 — hermetic tests for the event-driven
#             memory maintenance agent (Ministral 3B local).
# @license    MIT
# =============================================================================
"""Tests for MaintenanceAgentRapid (Sprint 2.5 §4 niveau 1).

The agent is meant to be invoked fire-and-forget after a conversation
ends. These tests pin :

  - Disabled via env var → returns "skipped/disabled", nothing called
  - Missing user_id / conversation_id → "skipped/missing_ids"
  - Conversation too short → "skipped/too_short"
  - Happy path → preferences hit `store_preference`, other types hit
    `store_fact` with category in extra_payload + source tag
  - Robust JSON parsing → markdown fences tolerated, invalid JSON returns []
  - Injection-shaped facts are rejected (reuse memory_service guard)
  - LLM exception → swallowed, returns "failed/llm_failed"
  - `_route_type_to_store_kind` mapping correctness
  - schedule_consolidation is a no-op when disabled or args missing

The LLM and the SQL message-load are monkeypatched ; no Qdrant / no
Ollama / no DB rows are required.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.services.memory import maintenance_rapid


# ── _is_disabled / env handling ───────────────────────────────────────


@pytest.mark.parametrize("value", ["1", "true", "True", "YES", "on"])
def test_is_disabled_recognises_truthy_env_values(monkeypatch, value) -> None:
    monkeypatch.setenv("MAINTENANCE_RAPID_DISABLED", value)
    assert maintenance_rapid._is_disabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_is_disabled_returns_false_for_neutral_env_values(monkeypatch, value) -> None:
    monkeypatch.setenv("MAINTENANCE_RAPID_DISABLED", value)
    assert maintenance_rapid._is_disabled() is False


# ── _strip_json_fences ────────────────────────────────────────────────


def test_strip_json_fences_handles_markdown_with_lang_tag() -> None:
    raw = "```json\n{\"facts\": []}\n```"
    assert maintenance_rapid._strip_json_fences(raw) == '{"facts": []}'


def test_strip_json_fences_handles_bare_backticks() -> None:
    raw = "```\n{\"facts\": []}\n```"
    assert maintenance_rapid._strip_json_fences(raw) == '{"facts": []}'


def test_strip_json_fences_noop_on_clean_json() -> None:
    raw = '{"facts": []}'
    assert maintenance_rapid._strip_json_fences(raw) == raw


# ── _route_type_to_store_kind ─────────────────────────────────────────


@pytest.mark.parametrize("ftype", ["context", "event", "skill", "personal", "unknown"])
def test_non_preference_types_route_to_fact(ftype) -> None:
    assert maintenance_rapid._route_type_to_store_kind(ftype) == "fact"


def test_preference_routes_to_preference() -> None:
    assert maintenance_rapid._route_type_to_store_kind("preference") == "preference"


# ── consolidate() — short-circuits ────────────────────────────────────


@pytest.mark.asyncio
async def test_consolidate_skipped_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MAINTENANCE_RAPID_DISABLED", "true")
    agent = maintenance_rapid.MaintenanceAgentRapid()
    result = await agent.consolidate("c1", "u1")
    assert result == {"status": "skipped", "reason": "disabled"}


@pytest.mark.asyncio
async def test_consolidate_skipped_when_user_id_missing() -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()
    result = await agent.consolidate("c1", "")
    assert result["status"] == "skipped"
    assert result["reason"] == "missing_ids"


@pytest.mark.asyncio
async def test_consolidate_skipped_when_conversation_id_missing() -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()
    result = await agent.consolidate("", "u1")
    assert result["reason"] == "missing_ids"


@pytest.mark.asyncio
async def test_consolidate_skipped_when_conversation_too_short(monkeypatch) -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()

    async def fake_load(self, conversation_id):
        return [_make_msg("user", "hello")]  # only 1 message → below threshold

    monkeypatch.setattr(
        maintenance_rapid.MaintenanceAgentRapid, "_load_recent_messages", fake_load
    )
    result = await agent.consolidate("c1", "u1")
    assert result == {"status": "skipped", "reason": "too_short"}


# ── consolidate() — happy path ────────────────────────────────────────


def _make_msg(role: str, content: str):
    """Build a duck-typed message that the formatter accepts."""
    class _M:
        pass
    m = _M()
    m.role = role
    m.content = content
    return m


@pytest.mark.asyncio
async def test_consolidate_happy_path_dispatches_to_typed_stores(monkeypatch) -> None:
    """Preferences hit store_preference, other types hit store_fact with the
    correct extra_payload (category + source). Pins the Jalon 4 routing."""
    agent = maintenance_rapid.MaintenanceAgentRapid()
    pref_calls: list[tuple] = []
    fact_calls: list[dict] = []

    async def fake_load(self, conversation_id):
        return [
            _make_msg("user", "I prefer concise answers"),
            _make_msg("assistant", "Got it."),
            _make_msg("user", "I work on a project called ELY"),
        ]

    # Signature reelle : `user_id`/`conversation_id` ont ete ajoutes le
    # 05/08 pour que l'appel LLM soit RATTACHABLE a un utilisateur, sans
    # quoi sa consommation n'est pas ecrivable. Ce double les porte —
    # c'est lui qui a signale le changement de contrat.
    async def fake_extract(self, conversation_text, user_id="", conversation_id=None):
        return [
            {"fact": "User prefers concise answers", "type": "preference"},
            {"fact": "User works on a project called ELY", "type": "context"},
            {"fact": "User attended a meeting yesterday", "type": "event"},
        ]

    async def fake_store_pref(self, preference, user_id):
        pref_calls.append((preference, user_id))

    async def fake_store_fact(self, content, user_id, conversation_id="", extra_payload=None):
        fact_calls.append({
            "content": content,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "extra_payload": extra_payload,
        })

    monkeypatch.setattr(maintenance_rapid.MaintenanceAgentRapid, "_load_recent_messages", fake_load)
    monkeypatch.setattr(maintenance_rapid.MaintenanceAgentRapid, "_extract_facts", fake_extract)

    from app.services.memory.semantic_user_store import SemanticUserStore
    monkeypatch.setattr(SemanticUserStore, "store_preference", fake_store_pref)
    monkeypatch.setattr(SemanticUserStore, "store_fact", fake_store_fact)

    result = await agent.consolidate("c1", "u1")

    assert result["status"] == "ok"
    assert result["preferences"] == 1
    assert result["facts"] == 2
    assert "duration_ms" in result

    # Preferences went to the preference store.
    assert pref_calls == [("User prefers concise answers", "u1")]

    # Facts went to store_fact with category + source in payload.
    assert len(fact_calls) == 2
    categories = sorted(c["extra_payload"]["category"] for c in fact_calls)
    assert categories == ["context", "event"]
    for c in fact_calls:
        assert c["extra_payload"]["source"] == "maintenance_rapid"
        assert c["conversation_id"] == "c1"
        assert c["user_id"] == "u1"


@pytest.mark.asyncio
async def test_consolidate_returns_zero_when_llm_extracts_nothing(monkeypatch) -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()

    async def fake_load(self, _):
        return [_make_msg("user", "ok"), _make_msg("assistant", "noted")]

    async def fake_extract(self, _, user_id="", conversation_id=None):
        return []

    # Stub the Sprint 3 Jalon 2 hook so we don't actually hit the LLM
    # for the user_state refresh — that's not what this test is checking.
    async def fake_refresh(self, *_a, **_kw):
        return "skipped"

    monkeypatch.setattr(maintenance_rapid.MaintenanceAgentRapid, "_load_recent_messages", fake_load)
    monkeypatch.setattr(maintenance_rapid.MaintenanceAgentRapid, "_extract_facts", fake_extract)
    monkeypatch.setattr(maintenance_rapid.MaintenanceAgentRapid, "_refresh_user_state", fake_refresh)

    result = await agent.consolidate("c1", "u1")
    # Use a subset assertion so future return-dict extensions don't break
    # this test the way Sprint 3 Jalon 2's new `user_state` key did.
    assert result["status"] == "ok"
    assert result["preferences"] == 0
    assert result["facts"] == 0
    assert "duration_ms" in result
    assert result["user_state"] == "skipped"


# ── _extract_facts JSON robustness ────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_facts_parses_clean_json(monkeypatch) -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()

    class _Response:
        content = json.dumps({"facts": [
            {"fact": "F1", "type": "context"},
            {"fact": "F2", "type": "preference"},
        ]})

    class _LLM:
        async def ainvoke(self, _msgs, config=None):
            return _Response()

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _LLM()
    )

    facts = await agent._extract_facts("dummy conversation")
    assert len(facts) == 2
    assert facts[0]["fact"] == "F1"


@pytest.mark.asyncio
async def test_extract_facts_caps_at_five_even_if_model_spams(monkeypatch) -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()

    class _Response:
        content = json.dumps({"facts": [
            {"fact": f"F{i}", "type": "context"} for i in range(20)
        ]})

    class _LLM:
        async def ainvoke(self, _msgs, config=None):
            return _Response()

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _LLM()
    )

    facts = await agent._extract_facts("x")
    assert len(facts) == 5


@pytest.mark.asyncio
async def test_extract_facts_returns_empty_on_invalid_json(monkeypatch) -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()

    class _Response:
        content = "totally not JSON, sorry."

    class _LLM:
        async def ainvoke(self, _msgs, config=None):
            return _Response()

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _LLM()
    )

    assert await agent._extract_facts("x") == []


# ── _store_facts rejects injection-shaped facts ───────────────────────


@pytest.mark.asyncio
async def test_store_facts_rejects_paragraph_length_facts(monkeypatch) -> None:
    """A fact longer than MAX_FACT_CHARS is the smoking gun of a model
    that packed a conversation summary into one entry (observed with
    Ministral 3B on 2026-05-21). It must be rejected before reaching
    any typed store — paragraphs in user_profile would be useless."""
    agent = maintenance_rapid.MaintenanceAgentRapid()
    fact_calls: list = []

    async def fake_store_fact(self, content, user_id, conversation_id="", extra_payload=None):
        fact_calls.append(content)

    from app.services.memory.semantic_user_store import SemanticUserStore
    monkeypatch.setattr(SemanticUserStore, "store_fact", fake_store_fact)
    monkeypatch.setattr(SemanticUserStore, "store_preference", fake_store_fact)

    paragraph = (
        "Voici un résumé structuré des éléments clés de la conversation : "
        "l'utilisateur s'intéresse aux infusions d'hibiscus et a posé "
        "plusieurs questions sur leurs propriétés, leur goût acidulé, "
        "et leur utilisation traditionnelle. Il évoque aussi son épouse "
        "et un intérêt général pour les plantes médicinales."
    )
    assert len(paragraph) > agent.MAX_FACT_CHARS
    short = "User likes hiking on weekends"

    pref_count, fact_count = await agent._store_facts(
        [
            {"fact": paragraph, "type": "context"},
            {"fact": short, "type": "context"},
        ],
        "u1",
        "c1",
    )
    assert pref_count == 0
    assert fact_count == 1
    assert fact_calls == [short]


@pytest.mark.asyncio
async def test_store_facts_rejects_injection_shaped_strings(monkeypatch) -> None:
    """A fact that triggers `_is_safe_fact` rejection in memory_service
    must NOT reach the store. Pins the safety guard re-use."""
    agent = maintenance_rapid.MaintenanceAgentRapid()
    pref_calls: list = []
    fact_calls: list = []

    async def fake_store_pref(self, preference, user_id):
        pref_calls.append(preference)

    async def fake_store_fact(self, content, user_id, conversation_id="", extra_payload=None):
        fact_calls.append(content)

    from app.services.memory.semantic_user_store import SemanticUserStore
    monkeypatch.setattr(SemanticUserStore, "store_preference", fake_store_pref)
    monkeypatch.setattr(SemanticUserStore, "store_fact", fake_store_fact)

    facts = [
        # A 600-char "fact" — _is_safe_fact rejects len > 500
        {"fact": "x" * 600, "type": "context"},
        # A clean fact — should still go through
        {"fact": "User likes hiking", "type": "context"},
    ]
    pref_count, fact_count = await agent._store_facts(facts, "u1", "c1")

    assert pref_count == 0
    assert fact_count == 1
    assert fact_calls == ["User likes hiking"]


# ── LLM error path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consolidate_returns_failed_on_llm_exception(monkeypatch) -> None:
    agent = maintenance_rapid.MaintenanceAgentRapid()

    async def fake_load(self, _):
        return [_make_msg("user", "ok"), _make_msg("assistant", "noted")]

    async def boom(self, _):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(maintenance_rapid.MaintenanceAgentRapid, "_load_recent_messages", fake_load)
    monkeypatch.setattr(maintenance_rapid.MaintenanceAgentRapid, "_extract_facts", boom)

    result = await agent.consolidate("c1", "u1")
    assert result == {"status": "failed", "reason": "llm_failed"}


# ── schedule_consolidation wrapper ────────────────────────────────────


def test_schedule_consolidation_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MAINTENANCE_RAPID_DISABLED", "true")
    assert maintenance_rapid.schedule_consolidation("c1", "u1") is None


def test_schedule_consolidation_noop_when_ids_missing(monkeypatch) -> None:
    monkeypatch.delenv("MAINTENANCE_RAPID_DISABLED", raising=False)
    assert maintenance_rapid.schedule_consolidation("", "u1") is None
    assert maintenance_rapid.schedule_consolidation("c1", "") is None


@pytest.mark.asyncio
async def test_schedule_consolidation_returns_a_task_we_can_await(monkeypatch) -> None:
    """Verify the wrapper actually runs the consolidate coroutine."""
    monkeypatch.delenv("MAINTENANCE_RAPID_DISABLED", raising=False)

    called: list = []

    async def fake_consolidate(self, conv_id, user_id):
        called.append((conv_id, user_id))
        return {"status": "ok", "preferences": 0, "facts": 0, "duration_ms": 1}

    monkeypatch.setattr(
        maintenance_rapid.MaintenanceAgentRapid, "consolidate", fake_consolidate
    )
    # Force a fresh instance so the monkeypatch on the class takes effect
    # via the lru_cache singleton.
    maintenance_rapid.get_maintenance_agent_rapid.cache_clear()

    task = maintenance_rapid.schedule_consolidation("c1", "u1")
    assert task is not None
    await task
    assert called == [("c1", "u1")]
