# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_learned_skills_injection.py
# @brief      Sprint 4b Phase 4.b — active_skills + skill_view tool + prompt injection
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for the active-skills injection layer (Phase 4.b).

Three layers :
  1. `active_skills` service — fetch / format / bump usage
  2. `skill_view` tool — found / not found / cross-user isolation
  3. `memory_snapshot` integration — the `<learned_skills>` block
     appears in the snapshot when the user has active playbooks
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.learning.active_skills import (
    MAX_SKILLS_IN_PROMPT,
    bump_skill_usage,
    format_active_skills_block,
    get_active_skill_by_name,
    get_active_skills_for_user,
)


@pytest_asyncio.fixture
async def _seeded_user():
    await init_db()
    from app.models.user import User
    async with async_session() as db:
        existing = (await db.execute(
            select(User).where(User.id == "as1")
        )).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="as1",
                username="active_skills_test",
                email="as1@test.local",
                hashed_password="x",
            ))
            await db.commit()
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == "as1"))
        await db.commit()
    yield "as1"


async def _seed_active_skill(
    user_id: str,
    name: str,
    description: str = "auto-generated playbook for tests",
    content: str = "# Body\nbody content",
    use_count: int = 0,
    promoted_at: datetime | None = None,
    content_format: str | None = None,
) -> str:
    kwargs = {}
    if content_format is not None:
        kwargs["content_format"] = content_format
    async with async_session() as db:
        s = LearnedSkill(
            user_id=user_id,
            name=name,
            description=description,
            content=content,
            frontmatter_json="{}",
            status=SkillStatus.ACTIVE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids="[]",
            use_count=use_count,
            promoted_at=promoted_at,
            **kwargs,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


# ────────────────────────────────────────────────────────────────────────
# get_active_skills_for_user
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_active_skills_empty_when_none(_seeded_user):
    out = await get_active_skills_for_user(_seeded_user)
    assert out == []


async def _ensure_user(uid: str, username: str = None, email: str = None):
    """Idempotent user seed — get or create. Avoids UNIQUE crashes when
    a prior test run left the row behind."""
    from app.models.user import User
    async with async_session() as db:
        existing = (await db.execute(
            select(User).where(User.id == uid)
        )).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id=uid,
                username=username or uid,
                email=email or f"{uid}@test.local",
                hashed_password="x",
            ))
            await db.commit()
        # Also wipe their learned skills (test isolation) — caller
        # generally seeds new ones right after.
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.commit()


@pytest.mark.asyncio
async def test_get_active_skills_filters_by_user_and_status(_seeded_user):
    """Other users' skills + non-active statuses must NOT be returned."""
    await _seed_active_skill(_seeded_user, "mine-active")

    # Seed another user (idempotent) + their active skill — must not leak
    await _ensure_user("as2", username="other-user-as2", email="other@test.local")
    async with async_session() as db:
        db.add(LearnedSkill(
            user_id="as2",
            name="theirs-active",
            description="other user's playbook",
            content="x",
            frontmatter_json="{}",
            status=SkillStatus.ACTIVE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids="[]",
        ))
        # Seed a non-active skill for _seeded_user — must not leak either
        db.add(LearnedSkill(
            user_id=_seeded_user,
            name="mine-candidate",
            description="not promoted yet",
            content="x",
            frontmatter_json="{}",
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids="[]",
        ))
        db.add(LearnedSkill(
            user_id=_seeded_user,
            name="mine-archived",
            description="was active, now archived",
            content="x",
            frontmatter_json="{}",
            status=SkillStatus.ARCHIVED,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids="[]",
        ))
        await db.commit()

    out = await get_active_skills_for_user(_seeded_user)
    names = [s.name for s in out]
    assert names == ["mine-active"]  # only the active, only ours


@pytest.mark.asyncio
async def test_get_active_skills_orders_by_usage(_seeded_user):
    """Most-used skills come first (curator surfaces high-value first
    when we cap at MAX_SKILLS_IN_PROMPT)."""
    await _seed_active_skill(_seeded_user, "low-use", use_count=1)
    await _seed_active_skill(_seeded_user, "high-use", use_count=42)
    await _seed_active_skill(_seeded_user, "medium-use", use_count=5)

    out = await get_active_skills_for_user(_seeded_user)
    names = [s.name for s in out]
    assert names == ["high-use", "medium-use", "low-use"]


@pytest.mark.asyncio
async def test_get_active_skills_respects_limit(_seeded_user):
    for i in range(5):
        await _seed_active_skill(_seeded_user, f"skill-{i}", use_count=i)
    out = await get_active_skills_for_user(_seeded_user, limit=3)
    assert len(out) == 3
    # Top 3 by use_count
    assert [s.name for s in out] == ["skill-4", "skill-3", "skill-2"]


@pytest.mark.asyncio
async def test_get_active_skills_empty_user_id_returns_empty():
    assert await get_active_skills_for_user("") == []


# ────────────────────────────────────────────────────────────────────────
# format_active_skills_block
# ────────────────────────────────────────────────────────────────────────


def test_format_block_empty_returns_empty_string():
    assert format_active_skills_block([]) == ""


def test_format_block_with_one_skill():
    s = SimpleNamespace(name="my-skill", description="A test skill")
    out = format_active_skills_block([s])
    assert out.startswith("<learned_skills>")
    assert out.rstrip().endswith("</learned_skills>")
    # Format changé le 28/07/2026 : la procédure est CHARGÉE sous un titre
    # « ### nom — description », au lieu d'une puce « - nom : description »
    # qui invitait à un `skill_view` que le modèle n'a jamais appelé.
    assert "### my-skill — A test skill" in out
    assert "1 playbook apprise" in out  # singular


def test_format_block_with_many_skills():
    skills = [
        SimpleNamespace(name=f"skill-{i}", description=f"desc {i}")
        for i in range(3)
    ]
    out = format_active_skills_block(skills)
    assert "3 playbooks apprises" in out
    for i in range(3):
        assert f"### skill-{i} — desc {i}" in out


def test_format_block_truncates_long_description():
    long_desc = "X" * 500
    s = SimpleNamespace(name="long-desc", description=long_desc)
    out = format_active_skills_block([s])
    # Single-line description, capped at ~200 chars
    line = [l for l in out.split("\n") if "long-desc" in l][0]
    assert len(line) < 250
    assert "…" in line


def test_format_block_strips_newlines_in_description():
    """A description with embedded newlines (oops in the writer) must
    not break the bullet format."""
    s = SimpleNamespace(name="multi-line", description="line1\nline2\nline3")
    out = format_active_skills_block([s])
    line = [l for l in out.split("\n") if "multi-line" in l][0]
    assert "\n" not in line.replace("\n", "")
    assert "line1 line2 line3" in line


# ────────────────────────────────────────────────────────────────────────
# bump_skill_usage + get_active_skill_by_name
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bump_skill_usage_increments_and_stamps(_seeded_user):
    skill_id = await _seed_active_skill(_seeded_user, "bump-me", use_count=5)
    before_call_ts = datetime.now(timezone.utc) - timedelta(seconds=1)

    ok = await bump_skill_usage(skill_id)
    assert ok is True

    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.use_count == 6
    assert skill.last_used_at is not None
    # Allow naive→aware coercion (sqlite returns naive datetime)
    last_ts = skill.last_used_at
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    assert last_ts >= before_call_ts


@pytest.mark.asyncio
async def test_bump_skill_usage_unknown_id_returns_false(_seeded_user):
    """Unknown id is best-effort no-op, not a crash."""
    ok = await bump_skill_usage("does-not-exist")
    assert ok is False


@pytest.mark.asyncio
async def test_get_active_skill_by_name_found(_seeded_user):
    skill_id = await _seed_active_skill(_seeded_user, "find-me")
    out = await get_active_skill_by_name(_seeded_user, "find-me")
    assert out is not None
    assert out.id == skill_id


@pytest.mark.asyncio
async def test_get_active_skill_by_name_wrong_user_returns_none(_seeded_user):
    """A skill belonging to another user must NEVER be returned to us."""
    skill_id = await _seed_active_skill(_seeded_user, "scoped-skill")
    out = await get_active_skill_by_name("totally-different-user", "scoped-skill")
    assert out is None
    # Sanity: it does exist when asked correctly
    assert (await get_active_skill_by_name(_seeded_user, "scoped-skill")).id == skill_id


@pytest.mark.asyncio
async def test_get_active_skill_by_name_non_active_returns_none(_seeded_user):
    """Candidate / archived / rejected skills must NOT be retrievable
    via the agent's skill_view path."""
    from app.models.user import User
    async with async_session() as db:
        db.add(LearnedSkill(
            user_id=_seeded_user,
            name="candidate-skill",
            description="not promoted",
            content="x",
            frontmatter_json="{}",
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids="[]",
        ))
        await db.commit()
    assert await get_active_skill_by_name(_seeded_user, "candidate-skill") is None


# ────────────────────────────────────────────────────────────────────────
# skill_view tool
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_view_returns_content_and_bumps_usage(_seeded_user):
    from app.agent.tools.learned_skills_tool import skill_view

    skill_id = await _seed_active_skill(
        _seeded_user, "viewable",
        description="A viewable playbook",
        content="# Title\n## Procedure\n1. step",
        use_count=0,
    )
    # The tool is a langchain @tool — call its .ainvoke with the args dict
    out = await skill_view.ainvoke({"name": "viewable", "user_id": _seeded_user})
    assert "viewable" in out
    assert "A viewable playbook" in out
    assert "## Procedure" in out

    # use_count bumped
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.use_count == 1
    assert skill.last_used_at is not None


@pytest.mark.asyncio
async def test_skill_view_not_found_returns_clear_message(_seeded_user):
    from app.agent.tools.learned_skills_tool import skill_view

    out = await skill_view.ainvoke({"name": "ghost-name", "user_id": _seeded_user})
    assert "No active playbook named" in out
    assert "ghost-name" in out


@pytest.mark.asyncio
async def test_skill_view_empty_name_returns_usage(_seeded_user):
    from app.agent.tools.learned_skills_tool import skill_view
    out = await skill_view.ainvoke({"name": "", "user_id": _seeded_user})
    assert "Usage:" in out


@pytest.mark.asyncio
async def test_skill_view_missing_user_id_refuses(_seeded_user):
    """Defensive — if USER_ID_TOOLS wiring regressed and the tool
    received an empty user_id, refuse rather than leak."""
    from app.agent.tools.learned_skills_tool import skill_view
    out = await skill_view.ainvoke({"name": "anything", "user_id": ""})
    assert "Refusing" in out or "Internal error" in out


@pytest.mark.asyncio
async def test_skill_view_cross_user_isolation(_seeded_user):
    """User A's skill_view cannot return user B's playbook content,
    even if user A guesses the exact name."""
    from app.agent.tools.learned_skills_tool import skill_view

    # Seed user B (idempotent) + their skill
    await _ensure_user("as3", username="userB-as3", email="b-test@test.local")
    await _seed_active_skill("as3", "userB-skill", content="SECRET B CONTENT")

    # User A queries with the right name — must NOT get B's content
    out = await skill_view.ainvoke({"name": "userB-skill", "user_id": _seeded_user})
    assert "SECRET B CONTENT" not in out
    assert "No active playbook" in out


# ────────────────────────────────────────────────────────────────────────
# Toolset profile + USER_ID_TOOLS wiring guards (CI regression)
# ────────────────────────────────────────────────────────────────────────


def test_skill_view_in_default_profile():
    """If a future refactor drops skill_view from the default profile,
    the agent never binds the tool and the prompt's <learned_skills>
    block becomes useless. Pin it."""
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all
    from app.agent.toolset_profiles import get_profile_tool_names, resolve_profile_tools

    register_all()
    joignables = {t.name for t in resolve_profile_tools("default", get_skill_registry().all_tools)}
    assert "skill_view" in joignables
    # Et dans la liste restreinte, qui sert aux petites fenêtres (#323) —
    # sinon le bloc <learned_skills> serait mort dès le tier IMAGE.
    assert "skill_view" in get_profile_tool_names("compact")


def test_skill_view_in_user_id_tools():
    """skill_view has user_id as InjectedToolArg — if a refactor drops
    it from USER_ID_TOOLS, the agent calls would silently fan out
    across users. Pin the wiring."""
    from app.agent.tool_sets import USER_ID_TOOLS
    assert "skill_view" in USER_ID_TOOLS


# ────────────────────────────────────────────────────────────────────────
# memory_snapshot integration
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_snapshot_includes_active_skills_block(_seeded_user, monkeypatch):
    """`build_memory_snapshot` must inject the `<learned_skills>`
    block when the user has at least one active playbook."""
    await _seed_active_skill(_seeded_user, "snapshot-skill",
                              description="snapshot integration test")

    # Stub out the memory manager surface so we don't need Qdrant
    class _StubMemory:
        async def get_relevant_constraints(self, q, u): return []
        async def get_relevant_memories(self, q, u): return []
        async def get_relevant_interactions(self, q, u, limit=3): return []
        async def get_user_preferences(self, u): return []

    # Stub get_user_context for memory_snapshot
    async def _fake_user_context(uid): return ""
    monkeypatch.setattr(
        "app.services.memory_service.get_user_context",
        _fake_user_context,
    )

    from app.agent.builders.memory_snapshot import build_memory_snapshot
    snapshot, _ = await build_memory_snapshot(
        messages=[],
        user_id=_seeded_user,
        user_query="anything",
        memory=_StubMemory(),
        use_compact=False,
    )
    assert "<learned_skills>" in snapshot
    assert "snapshot-skill" in snapshot
    assert "snapshot integration test" in snapshot


@pytest.mark.asyncio
async def test_memory_snapshot_no_block_when_user_has_no_active_skills(
    _seeded_user, monkeypatch,
):
    """No active skills → no `<learned_skills>` block (don't waste
    prompt tokens on an empty section)."""
    class _StubMemory:
        async def get_relevant_constraints(self, q, u): return []
        async def get_relevant_memories(self, q, u): return []
        async def get_relevant_interactions(self, q, u, limit=3): return []
        async def get_user_preferences(self, u): return []

    async def _fake_user_context(uid): return ""
    monkeypatch.setattr(
        "app.services.memory_service.get_user_context",
        _fake_user_context,
    )

    from app.agent.builders.memory_snapshot import build_memory_snapshot
    snapshot, _ = await build_memory_snapshot(
        messages=[],
        user_id=_seeded_user,
        user_query="anything",
        memory=_StubMemory(),
        use_compact=False,
    )
    assert "<learned_skills>" not in snapshot


# ────────────────────────────────────────────────────────────────────────
# C4-3 — fenêtre de grâce : un skill fraîchement promu (use_count=0)
# ne doit JAMAIS être coupé du prompt par le tri use_count (cold-start
# vécu en prod le 19/07 : levenshtein_distance promu → dernier au tri →
# hors top-20 → invisible pour le modèle).
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grace_window_includes_fresh_promoted_zero_use_skill(_seeded_user):
    """4 vétérans à fort usage + 1 frais promu, cap 4 : sans la grâce le
    frais (use_count=0) serait coupé. Avec elle, il est inclus ET en tête
    (saillance — c'est le skill que l'utilisateur vient de valider)."""
    for i in range(4):
        await _seed_active_skill(_seeded_user, f"veteran-{i}", use_count=100 + i)
    await _seed_active_skill(
        _seeded_user, "fresh-promoted", use_count=0,
        promoted_at=datetime.now(timezone.utc),
    )
    out = await get_active_skills_for_user(_seeded_user, limit=4)
    names = [s.name for s in out]
    assert len(out) == 4
    assert "fresh-promoted" in names
    assert names[0] == "fresh-promoted"


@pytest.mark.asyncio
async def test_grace_window_expired_returns_to_usage_order(_seeded_user):
    """Grâce expirée (promu il y a 30 jours, jamais utilisé) → le tri
    use_count reprend ses droits, le skill retombe hors du cap."""
    for i in range(4):
        await _seed_active_skill(_seeded_user, f"veteran-{i}", use_count=100 + i)
    await _seed_active_skill(
        _seeded_user, "old-promoted", use_count=0,
        promoted_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    out = await get_active_skills_for_user(_seeded_user, limit=4)
    names = [s.name for s in out]
    assert "old-promoted" not in names


@pytest.mark.asyncio
async def test_promoted_at_null_keeps_legacy_selection(_seeded_user):
    """Rows historiques (promoted_at NULL — seeds bundled, promotions
    antérieures à la migration sans backfill) → aucune grâce, sélection
    100 % legacy par use_count."""
    for i in range(5):
        await _seed_active_skill(_seeded_user, f"legacy-{i}", use_count=i)
    out = await get_active_skills_for_user(_seeded_user, limit=3)
    assert [s.name for s in out] == ["legacy-4", "legacy-3", "legacy-2"]


# ────────────────────────────────────────────────────────────────────────
# C4-3 — pertinence vs requête : quand le cap force un choix, un skill
# qui matche la demande courante bat un skill populaire hors-sujet.
# ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _no_semantic(monkeypatch):
    """Neutralise le cosine (déterminisme + pas de chargement FastEmbed
    en CI) — le lexical est testé seul, le sémantique reste best-effort."""
    from app.services.learning import active_skills as mod

    async def _empty(query, skills):
        return {}

    monkeypatch.setattr(mod, "_semantic_scores", _empty)


@pytest.mark.asyncio
async def test_query_relevance_rescues_matching_skill_on_overflow(
    _seeded_user, _no_semantic,
):
    for i in range(4):
        await _seed_active_skill(
            _seeded_user, f"popular-{i}",
            description="tri de la boîte mail et rangement agenda",
            use_count=50,
        )
    await _seed_active_skill(
        _seeded_user, "levenshtein-tool",
        description="calcule la distance de Levenshtein entre deux chaînes",
        use_count=0,
    )
    out = await get_active_skills_for_user(
        _seeded_user, limit=4,
        query="calcule la distance de levenshtein entre bonjour et bonsoir",
    )
    assert "levenshtein-tool" in [s.name for s in out]


@pytest.mark.asyncio
async def test_query_without_match_keeps_usage_order(_seeded_user, _no_semantic):
    """Requête sans rapport avec aucun skill → zéro score partout → la
    sélection retombe exactement sur le tri legacy par use_count."""
    for i in range(5):
        await _seed_active_skill(
            _seeded_user, f"skill-{i}",
            description="rangement hebdomadaire du bureau",
            use_count=i,
        )
    out = await get_active_skills_for_user(
        _seeded_user, limit=3, query="xyzzy plugh grault",
    )
    assert [s.name for s in out] == ["skill-4", "skill-3", "skill-2"]


def test_lexical_relevance_scoring_unit():
    """Score lexical pur : tokens normalisés (minuscules + accents
    strippés), recouvrement requête→texte."""
    from app.services.learning.active_skills import _lexical_score

    assert _lexical_score(
        "distance de Levenshtein",
        "levenshtein-tool : calcule la distance de levenshtein",
    ) > 0.5
    assert _lexical_score("météo de demain", "distance de levenshtein") == 0.0
    # Accent-insensible dans les DEUX sens (leçon FR cross-lingual)
    assert _lexical_score("créé", "outil cree pour les tests") > 0.0
    assert _lexical_score("", "n'importe quoi") == 0.0


# ────────────────────────────────────────────────────────────────────────
# C4-3 — la promotion pose promoted_at (les 2 chemins : admin + auto)
# ────────────────────────────────────────────────────────────────────────


async def _seed_candidate(user_id: str, name: str, content_format: str = "markdown_playbook") -> str:
    async with async_session() as db:
        s = LearnedSkill(
            user_id=user_id,
            name=name,
            description="candidate for promotion tests",
            content="# body",
            frontmatter_json="{}",
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids="[]",
            content_format=content_format,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


@pytest.mark.asyncio
async def test_admin_transition_to_active_stamps_promoted_at(_seeded_user):
    from app.routers.learning_skills import _transition_status

    skill_id = await _seed_candidate(_seeded_user, "admin-promote-me")
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        await _transition_status(db, skill, SkillStatus.ACTIVE, admin_id="adm")
        await db.commit()

    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert row.status == SkillStatus.ACTIVE
    assert row.promoted_at is not None


@pytest.mark.asyncio
async def test_admin_transition_away_from_active_keeps_promoted_at(_seeded_user):
    """Archiver ne réécrit PAS promoted_at — seule une (re)promotion
    la pose."""
    from app.routers.learning_skills import _transition_status

    stamp = datetime.now(timezone.utc) - timedelta(days=3)
    skill_id = await _seed_active_skill(
        _seeded_user, "archive-me", promoted_at=stamp,
    )
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        await _transition_status(db, skill, SkillStatus.ARCHIVED, admin_id="adm")
        await db.commit()

    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    got = row.promoted_at
    if got is not None and got.tzinfo is None:
        got = got.replace(tzinfo=timezone.utc)
    assert got is not None
    assert abs((got - stamp).total_seconds()) < 2


@pytest.mark.asyncio
async def test_auto_promotion_stamps_promoted_at(_seeded_user):
    from app.services.learning.skill_promotion import promote_candidate_to_active

    skill_id = await _seed_candidate(_seeded_user, "auto-promote-me")
    ok = await promote_candidate_to_active(skill_id, reason="test")
    assert ok is True

    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert row.status == SkillStatus.ACTIVE
    assert row.promoted_at is not None


# ────────────────────────────────────────────────────────────────────────
# C4-3 — le bloc distingue playbooks (skill_view) et OUTILS bindés
# (appel direct) : « lis-le via skill_view » était une consigne trompeuse
# pour un python_tool — le modèle doit l'APPELER, pas le lire.
# ────────────────────────────────────────────────────────────────────────


def test_format_block_python_tool_section():
    pb = SimpleNamespace(name="mail-triage", description="procédure mails",
                         content_format="markdown_playbook")
    pt = SimpleNamespace(name="levenshtein_distance", description="distance",
                         content_format="python_tool")
    out = format_active_skills_block([pb, pt])
    assert "skill_view" in out
    assert "DIRECTEMENT" in out
    assert "mail-triage" in out
    assert "levenshtein_distance" in out
    # L'outil ne doit PAS être listé dans la section skill_view
    playbook_part = out.split("DIRECTEMENT")[0]
    assert "levenshtein_distance" not in playbook_part


def test_format_block_only_python_tools_skips_playbook_header():
    pt = SimpleNamespace(name="only-tool", description="d",
                         content_format="python_tool")
    out = format_active_skills_block([pt])
    # Pas de section playbook (sa consigne « lis-le EN ENTIER via
    # skill_view » serait trompeuse pour un outil bindé). La mention
    # NÉGATIVE de skill_view dans l'en-tête outils, elle, est voulue.
    assert "playbook" not in out
    assert "lis-le EN ENTIER" not in out
    assert "DIRECTEMENT" in out
    assert out.startswith("<learned_skills>")
    assert out.rstrip().endswith("</learned_skills>")


def test_format_block_marks_fresh_skills_as_new():
    fresh = SimpleNamespace(
        name="fresh-tool", description="d", content_format="python_tool",
        promoted_at=datetime.now(timezone.utc),
    )
    old = SimpleNamespace(
        name="old-tool", description="d", content_format="python_tool",
        promoted_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    out = format_active_skills_block([fresh, old])
    fresh_line = [l for l in out.split("\n") if "fresh-tool" in l][0]
    old_line = [l for l in out.split("\n") if "old-tool" in l][0]
    assert "(nouveau)" in fresh_line
    assert "(nouveau)" not in old_line


# ────────────────────────────────────────────────────────────────────────
# C4-3 — intégration snapshot : à cap plein, le frais promu est visible
# dans le bloc construit par build_memory_snapshot (câblage complet).
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_snapshot_surfaces_fresh_promoted_over_cap(
    _seeded_user, monkeypatch,
):
    for i in range(MAX_SKILLS_IN_PROMPT):
        await _seed_active_skill(_seeded_user, f"vet-{i:02d}", use_count=10 + i)
    await _seed_active_skill(
        _seeded_user, "fresh-over-cap", use_count=0,
        promoted_at=datetime.now(timezone.utc),
    )

    class _StubMemory:
        async def get_relevant_constraints(self, q, u): return []
        async def get_relevant_memories(self, q, u): return []
        async def get_relevant_interactions(self, q, u, limit=3): return []
        async def get_user_preferences(self, u): return []

    async def _fake_user_context(uid): return ""
    monkeypatch.setattr(
        "app.services.memory_service.get_user_context",
        _fake_user_context,
    )
    from app.services.learning import active_skills as mod

    async def _empty(query, skills):
        return {}

    monkeypatch.setattr(mod, "_semantic_scores", _empty)

    from app.agent.builders.memory_snapshot import build_memory_snapshot
    snapshot, _ = await build_memory_snapshot(
        messages=[],
        user_id=_seeded_user,
        user_query="n'importe quelle demande",
        memory=_StubMemory(),
        use_compact=False,
    )
    assert "fresh-over-cap" in snapshot
