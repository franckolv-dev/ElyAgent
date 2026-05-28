# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_skill_creator.py
# @brief      Sprint 4b Phase 3.a — tests for the autonomous skill generator
# @license    Elastic License 2.0
# =============================================================================
"""Tests for `app/services/learning/skill_creator.py` — Sprint 4b Phase 3.a.

Four layers :
  1. Pure parser tests — `parse_playbook_response` shape coverage
  2. Prompt assembly — `_format_failure_case_for_prompt` + `_compose_user_prompt`
  3. DB-touching helpers — `_fetch_unprocessed_cases` clustering logic
  4. End-to-end — `run_skill_creator_batch` with a mocked tier-S LLM
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillStatus
from app.services.learning import skill_creator
from app.services.learning.skill_creator import (
    _compose_user_prompt,
    _fetch_unprocessed_cases,
    _format_failure_case_for_prompt,
    parse_playbook_response,
    run_skill_creator_batch,
)


@pytest_asyncio.fixture
async def _seeded_user():
    await init_db()
    from app.models.user import User
    async with async_session() as db:
        existing = (await db.execute(
            select(User).where(User.id == "sc1")
        )).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="sc1",
                username="skill_creator_test_user",
                email="sc1@test.local",
                hashed_password="x",
            ))
            await db.commit()
        # Wipe pre-existing failure_cases + learned_skills for this user
        await db.execute(delete(FailureCase).where(FailureCase.user_id == "sc1"))
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == "sc1"))
        await db.commit()
    yield "sc1"


async def _seed_failure_case(
    user_id: str,
    *,
    pattern_hash: str,
    signal_kind: str = "hitl_refusal",
    tool_name: str = "gmail_trash_emails",
    decision: str = "deny",
    signal_id: int | None = None,
) -> int:
    """Insert a fake failure_case and return its id."""
    async with async_session() as db:
        row = FailureCase(
            user_id=user_id,
            signal_table=f"{signal_kind}s",
            signal_id=signal_id or (uuid.uuid4().int % 1_000_000),
            conversation_id="conv-test",
            replay_payload=json.dumps({
                "signal_kind": signal_kind,
                "tool_name": tool_name,
                "decision": decision,
                "action_description": "Move 5 emails to trash",
            }),
            pattern_hash=pattern_hash,
            tier_llm="B",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


# ─────────────────────────────────────────────────────────────────────────
# parse_playbook_response
# ─────────────────────────────────────────────────────────────────────────


def test_parse_clean_response():
    raw = """---
name: gmail-trash-by-query-cautious
description: When the user asked to mass-delete emails, propose batch-by-batch instead of one shot.
tags: [gmail, hitl, destructive]
---

# Gmail bulk-trash cautious approach

## When this applies
- The user asks to trash N emails matching a query
- Previous HITL was refused with a destructive tool

## Procedure
1. Show the count first
2. Trash in batches of 10 max
3. Ask for confirmation between batches

## What NOT to do
- gmail_trash_by_query on a broad query without confirmation
"""
    parsed = parse_playbook_response(raw)
    assert parsed is not None
    assert parsed["name"] == "gmail-trash-by-query-cautious"
    assert parsed["description"].startswith("When the user asked")
    assert "Gmail bulk-trash cautious approach" in parsed["body"]
    assert isinstance(parsed["frontmatter"], dict)


def test_parse_with_markdown_fences():
    """LLMs sometimes wrap the whole thing in ```markdown ... ```"""
    raw = """```markdown
---
name: simple-test
description: a tiny one
---

# Body
content
```"""
    parsed = parse_playbook_response(raw)
    assert parsed is not None
    assert parsed["name"] == "simple-test"


def test_parse_with_leading_prose():
    """Sometimes the LLM forgets the strict-output rule and prepends prose."""
    raw = """Sure, here's the playbook:

---
name: leading-prose-test
description: parser should still find the frontmatter
---

# Body
content"""
    parsed = parse_playbook_response(raw)
    assert parsed is not None
    assert parsed["name"] == "leading-prose-test"


def test_parse_rejects_missing_name():
    raw = """---
description: missing name
---
# Body"""
    assert parse_playbook_response(raw) is None


def test_parse_rejects_missing_description():
    raw = """---
name: missing-desc
---
# Body"""
    assert parse_playbook_response(raw) is None


def test_parse_rejects_empty():
    assert parse_playbook_response("") is None
    assert parse_playbook_response("   ") is None
    assert parse_playbook_response("not a playbook at all") is None


def test_parse_caps_name_at_64_chars():
    long_name = "a" * 100
    raw = f"""---
name: {long_name}
description: testing the cap
---
# Body"""
    parsed = parse_playbook_response(raw)
    assert parsed is not None
    assert len(parsed["name"]) == 64


# ─────────────────────────────────────────────────────────────────────────
# Prompt assembly
# ─────────────────────────────────────────────────────────────────────────


def test_format_failure_case_for_prompt_includes_key_fields():
    fc = SimpleNamespace(
        id=42,
        signal_table="hitl_refusals",
        tier_llm="B",
        replay_payload=json.dumps({
            "signal_kind": "hitl_refusal",
            "tool_name": "gmail_trash_emails",
            "decision": "deny",
            "action_description": "Move 12 emails to trash",
        }),
    )
    out = _format_failure_case_for_prompt(fc)
    assert "case#42" in out
    assert "gmail_trash_emails" in out
    assert "deny" in out
    assert "Move 12 emails" in out


def test_format_failure_case_handles_broken_payload():
    """A malformed replay_payload must not crash the formatter."""
    fc = SimpleNamespace(
        id=99,
        signal_table="mission_critiques",
        tier_llm=None,
        replay_payload="not json{",
    )
    out = _format_failure_case_for_prompt(fc)
    assert "case#99" in out
    assert "mission_critiques" in out


def test_compose_user_prompt_groups_cluster():
    cluster = [
        SimpleNamespace(
            id=1, signal_table="hitl_refusals", tier_llm="B", pattern_hash="abc",
            replay_payload=json.dumps({"tool_name": "gmail_trash_emails", "decision": "deny"}),
        ),
        SimpleNamespace(
            id=2, signal_table="hitl_refusals", tier_llm="B", pattern_hash="abc",
            replay_payload=json.dumps({"tool_name": "gmail_trash_emails", "decision": "ban"}),
        ),
    ]
    out = _compose_user_prompt(cluster)
    assert "abc" in out  # fingerprint visible
    assert "Number of cases in this cluster: 2" in out
    assert "case#1" in out and "case#2" in out
    assert "Write the playbook now" in out


# ─────────────────────────────────────────────────────────────────────────
# _fetch_unprocessed_cases
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_no_failure_cases(_seeded_user):
    async with async_session() as db:
        out = await _fetch_unprocessed_cases(db, _seeded_user, 5)
    assert out == []


@pytest.mark.asyncio
async def test_fetch_clusters_by_pattern_hash(_seeded_user):
    """Failure cases with the same pattern_hash must end up in the same
    cluster; different hashes → different clusters."""
    await _seed_failure_case(_seeded_user, pattern_hash="hash_A", tool_name="t_a")
    await _seed_failure_case(_seeded_user, pattern_hash="hash_A", tool_name="t_a")
    await _seed_failure_case(_seeded_user, pattern_hash="hash_A", tool_name="t_a")
    await _seed_failure_case(_seeded_user, pattern_hash="hash_B", tool_name="t_b")

    async with async_session() as db:
        clusters = await _fetch_unprocessed_cases(db, _seeded_user, 10)

    assert len(clusters) == 2
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 3]


@pytest.mark.asyncio
async def test_fetch_respects_batch_size(_seeded_user):
    """If 5 distinct clusters exist and batch_size=2, we get 2 clusters."""
    for i in range(5):
        await _seed_failure_case(_seeded_user, pattern_hash=f"hash_{i}")
    async with async_session() as db:
        clusters = await _fetch_unprocessed_cases(db, _seeded_user, 2)
    assert len(clusters) == 2


@pytest.mark.asyncio
async def test_fetch_skips_already_processed_cases(_seeded_user):
    """Cases with processed_at set must NOT be returned again."""
    fc_id = await _seed_failure_case(_seeded_user, pattern_hash="hash_X")
    async with async_session() as db:
        # Mark it processed
        from datetime import datetime, timezone
        from sqlalchemy import update
        await db.execute(
            update(FailureCase)
            .where(FailureCase.id == fc_id)
            .values(processed_at=datetime.now(timezone.utc))
        )
        await db.commit()
        clusters = await _fetch_unprocessed_cases(db, _seeded_user, 5)
    assert clusters == []


# ─────────────────────────────────────────────────────────────────────────
# End-to-end run_skill_creator_batch (with mocked tier-S)
# ─────────────────────────────────────────────────────────────────────────


class _FakeLLMResponse:
    """Mimics a langchain BaseMessage response."""
    def __init__(self, content: str, in_tok: int = 1000, out_tok: int = 500):
        self.content = content
        self.usage_metadata = {"input_tokens": in_tok, "output_tokens": out_tok}
        self.response_metadata = {"model_name": "fake-opus"}


class _FakeLLM:
    """Async stub for the tier-S LLM."""
    def __init__(self, response_content: str):
        self._content = response_content
        self.call_count = 0

    async def ainvoke(self, messages):
        self.call_count += 1
        return _FakeLLMResponse(self._content)


@pytest.mark.asyncio
async def test_run_batch_no_cases_returns_zero(_seeded_user):
    out = await run_skill_creator_batch(user_id=_seeded_user, batch_size=3)
    assert out["clusters_processed"] == 0
    assert out["skills_created"] == 0
    assert out["drafts"] == []


@pytest.mark.asyncio
async def test_run_batch_no_user_id_errors_cleanly():
    out = await run_skill_creator_batch(user_id="", batch_size=3)
    assert "error" in out
    assert out["skills_created"] == 0


@pytest.mark.asyncio
async def test_run_batch_drafts_skill_and_marks_processed(_seeded_user, monkeypatch):
    """End-to-end happy path: 2 cases in 1 cluster → 1 candidate skill,
    both cases get marked processed_at and linked to the new skill."""
    fc_id_a = await _seed_failure_case(_seeded_user, pattern_hash="happy_hash")
    fc_id_b = await _seed_failure_case(_seeded_user, pattern_hash="happy_hash")

    fake_response = """---
name: test-happy-path
description: A test playbook from a mocked tier-S call.
tags: [test]
---

# Test playbook
## When this applies
- happy hash trigger
## Procedure
1. Do the right thing
## What NOT to do
- Do the wrong thing
"""
    fake = _FakeLLM(fake_response)

    async def _fake_get_llm(*, force_fallback=False):
        return fake, "primary"

    monkeypatch.setattr(skill_creator, "get_tier_s_llm", _fake_get_llm)

    out = await run_skill_creator_batch(user_id=_seeded_user, batch_size=5)

    assert out["clusters_processed"] == 1
    assert out["skills_created"] == 1
    assert fake.call_count == 1
    assert len(out["drafts"]) == 1
    draft = out["drafts"][0]
    assert draft["status"] == "drafted"
    assert draft["skill_name"] == "test-happy-path"
    assert draft["cluster_size"] == 2
    assert "learned_skill_id" in draft

    # DB checks: skill row exists + cases processed
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == draft["learned_skill_id"])
        )).scalar_one()
        assert skill.name == "test-happy-path"
        assert skill.status == SkillStatus.CANDIDATE
        assert skill.iteration_count == 1
        assert "happy_hash" in (skill.rationale or "")
        # Case ids stored
        case_ids = json.loads(skill.from_failure_case_ids)
        assert sorted(case_ids) == sorted([fc_id_a, fc_id_b])

        for fc_id in (fc_id_a, fc_id_b):
            fc = (await db.execute(
                select(FailureCase).where(FailureCase.id == fc_id)
            )).scalar_one()
            assert fc.processed_at is not None
            assert fc.learned_skill_id == draft["learned_skill_id"]


@pytest.mark.asyncio
async def test_run_batch_parse_failure_does_not_crash_batch(_seeded_user, monkeypatch):
    """When the tier-S response can't be parsed, we log + skip + return
    a draft entry with status=parse_failed. The other clusters continue."""
    # Two clusters: A will get a bad response, B will get a good one.
    await _seed_failure_case(_seeded_user, pattern_hash="bad_hash")
    await _seed_failure_case(_seeded_user, pattern_hash="good_hash")

    call_count = {"n": 0}

    class _PartialFake(_FakeLLM):
        async def ainvoke(self, messages):
            call_count["n"] += 1
            # The order of calls follows _fetch_unprocessed_cases sort.
            # Both clusters have a single recent case, so order between
            # them is by creation timestamp desc — the most-recently
            # seeded ("good_hash") fires first.
            if call_count["n"] == 1:
                return _FakeLLMResponse("""---
name: good-skill
description: This one parses fine.
---
# OK
content""")
            else:
                return _FakeLLMResponse("garbage that won't parse at all")

    fake = _PartialFake("")
    async def _fake_get_llm(*, force_fallback=False):
        return fake, "primary"

    monkeypatch.setattr(skill_creator, "get_tier_s_llm", _fake_get_llm)

    out = await run_skill_creator_batch(user_id=_seeded_user, batch_size=5)

    assert out["clusters_processed"] == 2
    assert out["skills_created"] == 1  # only the good one
    statuses = sorted(d["status"] for d in out["drafts"])
    assert statuses == ["drafted", "parse_failed"]


@pytest.mark.asyncio
async def test_run_batch_no_provider_returns_no_provider(_seeded_user, monkeypatch):
    """If neither Anthropic nor DeepSeek is configured, we surface
    'no_provider' for each cluster but don't crash."""
    await _seed_failure_case(_seeded_user, pattern_hash="any_hash")

    async def _fake_get_llm(*, force_fallback=False):
        return None, "none"

    monkeypatch.setattr(skill_creator, "get_tier_s_llm", _fake_get_llm)

    out = await run_skill_creator_batch(user_id=_seeded_user, batch_size=5)
    assert out["clusters_processed"] == 1
    assert out["skills_created"] == 0
    assert out["drafts"][0]["status"] == "no_provider"
