# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_memory_recall.py
# @brief      Unit tests for Sprint 2.5 Jalon 3 — MemoryType, MemoryHit,
#             MemoryRecallService.recall(), and the LangChain memory_recall tool.
# @license    Elastic License 2.0
# =============================================================================
"""Sprint 2.5 Jalon 3 — recall surface tests.

Covers:
  - MemoryType.parse() lenience
  - MemoryHit.to_dict() shape
  - MemoryRecallService input guards (empty user_id, empty query)
  - MemoryRecallService.recall() correctly dispatches to the right store
  - AUTO fan-out merges and de-duplicates
  - ERROR type raises UnreadableMemoryType (write-only)
  - PROCEDURAL reads the tool registry (02/08) and stays out of the fan-out
  - LangChain tool input validation
  - LangChain tool composes a prose digest from MemoryHits

The store layer itself is mocked — these tests pin the contract of the
service, not Qdrant/SQL behaviour. Integration tests against real stores
land in Jalon 8 with the migration script.
"""
from __future__ import annotations

import pytest

from app.services.memory.recall_service import MemoryRecallService
from app.services.memory.types import MemoryHit, MemoryType


# ── MemoryType.parse() ────────────────────────────────────────────────


def test_memory_type_parse_lowercase_value_returns_enum_member() -> None:
    assert MemoryType.parse("episodic") == MemoryType.EPISODIC
    assert MemoryType.parse("semantic_user") == MemoryType.SEMANTIC_USER
    assert MemoryType.parse("procedural") == MemoryType.PROCEDURAL
    assert MemoryType.parse("error") == MemoryType.ERROR
    assert MemoryType.parse("constraint") == MemoryType.CONSTRAINT
    assert MemoryType.parse("auto") == MemoryType.AUTO


def test_memory_type_parse_uppercase_normalises_to_lowercase() -> None:
    assert MemoryType.parse("EPISODIC") == MemoryType.EPISODIC
    assert MemoryType.parse("Semantic_User") == MemoryType.SEMANTIC_USER


def test_memory_type_parse_passthrough_for_enum_instance() -> None:
    assert MemoryType.parse(MemoryType.AUTO) is MemoryType.AUTO


def test_memory_type_parse_invalid_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown MemoryType"):
        MemoryType.parse("not-a-memory-type")


# ── MemoryHit.to_dict() ───────────────────────────────────────────────


def test_memory_hit_to_dict_includes_all_fields() -> None:
    hit = MemoryHit(
        type=MemoryType.EPISODIC,
        content="hello world",
        score=0.876543,
        metadata={"user_message": "ping"},
        created_at="2026-05-21T10:00:00+00:00",
    )
    d = hit.to_dict()
    assert d == {
        "type": "episodic",
        "content": "hello world",
        "score": 0.8765,  # rounded to 4 decimals
        "metadata": {"user_message": "ping"},
        "created_at": "2026-05-21T10:00:00+00:00",
    }


def test_memory_hit_defaults_are_safe() -> None:
    hit = MemoryHit(type=MemoryType.SEMANTIC_USER, content="x")
    assert hit.score == 1.0
    assert hit.metadata == {}
    assert hit.created_at is None


# ── MemoryRecallService input guards ──────────────────────────────────


@pytest.mark.asyncio
async def test_recall_empty_user_id_returns_empty_list() -> None:
    svc = MemoryRecallService()
    result = await svc.recall(MemoryType.AUTO, "hello", user_id="", limit=5)
    assert result == []


@pytest.mark.asyncio
async def test_recall_empty_query_returns_empty_list() -> None:
    svc = MemoryRecallService()
    assert await svc.recall(MemoryType.AUTO, "", user_id="u1") == []
    assert await svc.recall(MemoryType.AUTO, "   ", user_id="u1") == []


@pytest.mark.asyncio
async def test_recall_error_type_raises_unreadable() -> None:
    """CONTRAT MODIFIÉ EN V0-5 : écriture seule ne veut pas dire « vide ».
    Rendre `[]` faisait lire au modèle « rien en mémoire » là où la vérité est
    « pas de lecture implémentée »."""
    from app.services.memory.recall_service import UnreadableMemoryType

    svc = MemoryRecallService()
    with pytest.raises(UnreadableMemoryType):
        await svc.recall(MemoryType.ERROR, "anything", user_id="u1", limit=5)


@pytest.mark.asyncio
async def test_recall_procedural_is_readable_again(monkeypatch) -> None:
    """PIN 02/08 — `procedural` a cessé d'être « non consultable ».

    Il l'était parce qu'aucun magasin ne le servait. Sa source est désormais le
    registre d'outils, via la même voie que `find_tool`. Ce test échoue si
    quelqu'un le remet dans `_UNREADABLE_TYPES` sans retirer la lecture.
    """
    import app.skills.builtin.find_tool_skill as fts

    async def fake_rank(capability: str, k: int = 5) -> list[tuple[str, str]]:
        return [("gmail_send_email", "Envoyer un email")]

    monkeypatch.setattr(fts, "rank_tools_for_capability", fake_rank)

    svc = MemoryRecallService()
    hits = await svc.recall(MemoryType.PROCEDURAL, "envoyer un mail", user_id="u1")
    assert [h.type for h in hits] == [MemoryType.PROCEDURAL]
    assert hits[0].metadata["tool_name"] == "gmail_send_email"
    assert "gmail_send_email" in hits[0].content


@pytest.mark.asyncio
async def test_recall_procedural_reflects_the_registry_without_a_store() -> None:
    """Le livrable mesurable du §2.5.2 : ajouter un outil au CODE suffit.

    Aucun magasin, aucune écriture, aucune migration — la procédurale lit le
    registre. Un outil qui vient d'être enregistré doit donc pouvoir sortir
    d'un recall sans qu'on ait rien stocké.
    """
    from app.skills.builtin import register_all

    register_all()
    svc = MemoryRecallService()
    hits = await svc.recall(
        MemoryType.PROCEDURAL, "chercher sur le web", user_id="u1", limit=5
    )
    # Best-effort sur le classement (encodeur/sélecteur peuvent manquer en
    # test) — ce qui est épinglé, c'est que la voie RÉPOND au lieu de lever.
    assert isinstance(hits, list)
    assert all(h.type == MemoryType.PROCEDURAL for h in hits)
    assert all("tool_name" in h.metadata for h in hits)


@pytest.mark.asyncio
async def test_recall_invalid_memory_type_string_raises_value_error() -> None:
    """The service rejects unknown types loudly. The tool layer above
    catches this and returns a user-friendly error to the LLM."""
    svc = MemoryRecallService()
    with pytest.raises(ValueError):
        await svc.recall("not-a-type", "hello", user_id="u1")


# ── MemoryRecallService dispatch (with mocked stores) ─────────────────


@pytest.mark.asyncio
async def test_recall_constraint_dispatches_to_constraint_store(monkeypatch) -> None:
    svc = MemoryRecallService()

    async def fake_get_relevant(query, user_id, limit):
        return ["never delete without asking"]

    monkeypatch.setattr(svc.constraints, "get_relevant", fake_get_relevant)

    hits = await svc.recall(MemoryType.CONSTRAINT, "delete", user_id="u1", limit=5)
    assert len(hits) == 1
    assert hits[0].type == MemoryType.CONSTRAINT
    assert hits[0].content == "never delete without asking"
    assert hits[0].metadata == {"priority": "high"}


@pytest.mark.asyncio
async def test_recall_semantic_user_merges_facts_and_preferences(monkeypatch) -> None:
    svc = MemoryRecallService()

    async def fake_facts(query, user_id, limit):
        return ["user works on ELY"]

    async def fake_prefs(user_id, limit):
        return ["responds in French"]

    monkeypatch.setattr(svc.semantic, "get_relevant_facts", fake_facts)
    monkeypatch.setattr(svc.semantic, "get_preferences", fake_prefs)

    hits = await svc.recall(MemoryType.SEMANTIC_USER, "ELY", user_id="u1", limit=10)
    kinds = {h.metadata["kind"] for h in hits}
    assert kinds == {"fact", "preference"}
    assert all(h.type == MemoryType.SEMANTIC_USER for h in hits)


@pytest.mark.asyncio
async def test_recall_auto_fans_out_to_all_stores_and_merges(monkeypatch) -> None:
    svc = MemoryRecallService()

    async def fake_episodic(query, user_id, limit):
        return [{"content": "Q&A pair", "user_message": "hi", "assistant_message": "ho"}]

    async def fake_facts(query, user_id, limit):
        return ["fact"]

    async def fake_prefs(user_id, limit):
        return ["pref"]

    async def fake_constraint(query, user_id, limit):
        return ["never X"]

    monkeypatch.setattr(svc.episodic, "get_relevant", fake_episodic)
    monkeypatch.setattr(svc.semantic, "get_relevant_facts", fake_facts)
    monkeypatch.setattr(svc.semantic, "get_preferences", fake_prefs)
    monkeypatch.setattr(svc.constraints, "get_relevant", fake_constraint)

    hits = await svc.recall(MemoryType.AUTO, "anything", user_id="u1", limit=20)
    types_returned = {h.type for h in hits}
    # 3 types dans le fan-out. ERROR n'y a jamais été (écriture seule).
    # PROCEDURAL est lisible depuis le 02/08 mais reste DEHORS, exprès : « de
    # quoi te souviens-tu à propos de X » ne doit pas rendre des noms d'outils
    # au milieu des souvenirs. L'y remettre casse ce test — c'est voulu.
    assert types_returned == {
        MemoryType.EPISODIC,
        MemoryType.SEMANTIC_USER,
        MemoryType.CONSTRAINT,
    }


@pytest.mark.asyncio
async def test_recall_auto_respects_limit_after_merge(monkeypatch) -> None:
    svc = MemoryRecallService()

    async def fake_many_facts(query, user_id, limit):
        return [f"fact{i}" for i in range(10)]

    async def fake_empty(*a, **kw):
        return []

    monkeypatch.setattr(svc.semantic, "get_relevant_facts", fake_many_facts)
    monkeypatch.setattr(svc.semantic, "get_preferences", fake_empty)
    monkeypatch.setattr(svc.episodic, "get_relevant", fake_empty)
    monkeypatch.setattr(svc.constraints, "get_relevant", fake_empty)

    hits = await svc.recall(MemoryType.AUTO, "fact", user_id="u1", limit=3)
    assert len(hits) == 3


@pytest.mark.asyncio
async def test_recall_auto_survives_one_store_failing(monkeypatch) -> None:
    """If one fan-out branch raises, others must still return."""
    svc = MemoryRecallService()

    async def fake_facts(query, user_id, limit):
        return ["fact"]

    async def fake_prefs(*a, **kw):
        return []

    async def boom(*a, **kw):
        raise RuntimeError("Qdrant exploded")

    async def fake_empty(*a, **kw):
        return []

    monkeypatch.setattr(svc.semantic, "get_relevant_facts", fake_facts)
    monkeypatch.setattr(svc.semantic, "get_preferences", fake_prefs)
    monkeypatch.setattr(svc.episodic, "get_relevant", boom)
    monkeypatch.setattr(svc.constraints, "get_relevant", fake_empty)

    hits = await svc.recall(MemoryType.AUTO, "x", user_id="u1", limit=5)
    # Despite episodic blowing up, the semantic-user fact still surfaces.
    assert any(h.content == "fact" for h in hits)


# ── LangChain tool layer ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_rejects_empty_user_id() -> None:
    from app.agent.tools.memory_recall_tool import memory_recall
    out = await memory_recall.ainvoke({"query": "anything", "user_id": ""})
    assert "user_id manquant" in out


@pytest.mark.asyncio
async def test_tool_rejects_empty_query() -> None:
    from app.agent.tools.memory_recall_tool import memory_recall
    out = await memory_recall.ainvoke({"query": "   ", "user_id": "u1"})
    assert "requête est vide" in out


@pytest.mark.asyncio
async def test_tool_rejects_invalid_memory_type() -> None:
    from app.agent.tools.memory_recall_tool import memory_recall
    out = await memory_recall.ainvoke({
        "query": "x", "user_id": "u1", "memory_type": "potato",
    })
    assert "memory_type" in out and "invalide" in out


@pytest.mark.asyncio
async def test_tool_returns_friendly_message_when_no_hits(monkeypatch) -> None:
    """When the service returns [], the user-facing tool returns a polite
    explanation rather than an empty string the LLM would have to interpret."""
    from app.agent.tools import memory_recall_tool

    async def fake_recall(*a, **kw):
        return []

    fake_service = type("S", (), {"recall": fake_recall})()
    monkeypatch.setattr(
        memory_recall_tool, "get_memory_recall_service", lambda: fake_service
    )

    out = await memory_recall_tool.memory_recall.ainvoke({
        "query": "doctolib", "user_id": "u1",
    })
    assert "Aucun souvenir" in out


@pytest.mark.asyncio
async def test_tool_composes_prose_digest_from_hits(monkeypatch) -> None:
    """Pin the prose format — Markdown-free, one numbered paragraph per hit."""
    from app.agent.tools import memory_recall_tool

    async def fake_recall(*a, **kw):
        return [
            MemoryHit(
                type=MemoryType.SEMANTIC_USER,
                content="user prefers concise answers",
                score=0.9,
                metadata={"kind": "preference"},
                created_at="2026-05-14T10:00:00+00:00",
            ),
            MemoryHit(
                type=MemoryType.EPISODIC,
                content="we discussed Doctolib last week",
                score=0.7,
                metadata={"conversation_id": "c123"},
            ),
        ]

    fake_service = type("S", (), {"recall": fake_recall})()
    monkeypatch.setattr(
        memory_recall_tool, "get_memory_recall_service", lambda: fake_service
    )

    out = await memory_recall_tool.memory_recall.ainvoke({
        "query": "preferences", "user_id": "u1",
    })
    # No raw JSON, no ``` code fences in the response
    assert "```" not in out
    assert "{" not in out
    # Both contents must be quoted in the digest
    assert "concise" in out
    assert "Doctolib" in out
    # Numbered list expected
    assert "1." in out and "2." in out


# ── Procédurale, couche outil (02/08) ─────────────────────────────────


@pytest.mark.asyncio
async def test_tool_procedural_binds_the_tools_it_names(monkeypatch) -> None:
    """PIN anti-façade : nommer un outil doit le rendre APPELABLE.

    Sans ce binding, le modèle lit « gmail_send_email existe », l'appelle, et
    ne le trouve pas dans son profil — l'outil aurait annoncé une capacité que
    le tour suivant dément. `find_tool` enregistre ses trouvailles pour
    qu'`agent_node` les binde ; la procédurale sert le même classement et doit
    donc faire pareil.
    """
    from app.agent import discovered_tools
    from app.agent.tool_context import CURRENT_CONVERSATION_ID
    from app.agent.tools import memory_recall_tool

    async def fake_recall(
        memory_type, query: str, user_id: str, limit: int = 5,
        filter: dict | None = None,
    ) -> list[MemoryHit]:
        return [
            MemoryHit(
                type=MemoryType.PROCEDURAL,
                content="gmail_send_email — Envoyer un email",
                metadata={"tool_name": "gmail_send_email"},
            )
        ]

    # staticmethod : sans lui `recall` devient une méthode liée et `self`
    # passe en 1er positionnel, ce qui casse la signature réelle. Les faux
    # gardent la vraie signature — c'est ce qui fait remarquer un changement
    # de contrat, un `**kwargs` l'avalerait en silence.
    fake_service = type("S", (), {"recall": staticmethod(fake_recall)})()
    monkeypatch.setattr(
        memory_recall_tool, "get_memory_recall_service", lambda: fake_service
    )

    token = CURRENT_CONVERSATION_ID.set("conv-proc-test")
    try:
        await memory_recall_tool.memory_recall.ainvoke({
            "query": "envoyer un mail",
            "memory_type": "procedural",
            "user_id": "u1",
        })
        assert "gmail_send_email" in discovered_tools.get_discovered("conv-proc-test")
    finally:
        CURRENT_CONVERSATION_ID.reset(token)
        discovered_tools.discard_discovered("conv-proc-test")


@pytest.mark.asyncio
async def test_tool_procedural_empty_says_no_tool_not_no_memory(monkeypatch) -> None:
    """Un catalogue muet ne dit pas « on n'en a jamais parlé ».

    Le message générique parle de souvenirs et de formulation d'époque : sur la
    procédurale il enverrait le modèle chercher dans la mauvaise direction, au
    lieu de l'orienter vers report_missing_capability.
    """
    from app.agent.tools import memory_recall_tool

    async def fake_recall(
        memory_type, query: str, user_id: str, limit: int = 5,
        filter: dict | None = None,
    ) -> list[MemoryHit]:
        return []

    fake_service = type("S", (), {"recall": staticmethod(fake_recall)})()
    monkeypatch.setattr(
        memory_recall_tool, "get_memory_recall_service", lambda: fake_service
    )

    out = await memory_recall_tool.memory_recall.ainvoke({
        "query": "piloter un drone",
        "memory_type": "procedural",
        "user_id": "u1",
    })
    assert "Aucun outil du catalogue" in out
    assert "report_missing_capability" in out
    assert "souvenir" not in out.lower()
