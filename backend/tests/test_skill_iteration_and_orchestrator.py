# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_skill_iteration_and_orchestrator.py
# @brief      Sprint 4b Phase 3.c — patch loop + orchestrator + admin router
# @license    Elastic License 2.0
# =============================================================================
"""Tests for `app/services/learning/skill_iteration.py`,
`skill_orchestrator.py` and `app/routers/learning_skills.py`.

Three layers :
  1. `patch_skill` — happy patch, max_iterations gate, no_provider,
     llm_call_failed, parse_failed, skill_not_found, no_cases.
  2. `mark_rejected` — flips status, idempotent on unknown id.
  3. `run_full_loop` — orchestrator chains creator → eval → patch →
     reject in the right order; pass-first iteration stops the loop;
     max_iterations triggers mark_rejected.
  4. Admin router — list candidates filter shapes, run endpoint
     happy path with mocked orchestrator.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.learning import (
    skill_creator,
    skill_eval,
    skill_iteration,
    skill_orchestrator,
)
from app.services.learning.skill_iteration import (
    MAX_ITERATIONS,
    mark_rejected,
    patch_skill,
)
from app.services.learning.skill_orchestrator import run_full_loop


@pytest_asyncio.fixture
async def _seeded_user():
    await init_db()
    from app.models.user import User
    from app.models.usage_log import UsageLog
    async with async_session() as db:
        existing = (await db.execute(
            select(User).where(User.id == "si1")
        )).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="si1",
                username="skill_iter_test_user",
                email="si1@test.local",
                hashed_password="x",
            ))
            await db.commit()
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == "si1"))
        await db.execute(delete(FailureCase).where(FailureCase.user_id == "si1"))
        await db.execute(
            delete(UsageLog).where(
                UsageLog.user_id == "si1",
                UsageLog.skill_used.like("tier_s.%"),
            )
        )
        await db.commit()
    yield "si1"
    async with async_session() as db:
        await db.execute(
            delete(UsageLog).where(
                UsageLog.user_id == "si1",
                UsageLog.skill_used.like("tier_s.%"),
            )
        )
        await db.commit()


async def _seed_candidate(
    user_id: str,
    iteration_count: int = 1,
    n_cases: int = 2,
    content: str = "# Original\nbody",
) -> str:
    """Insert a candidate skill + its source failure_cases; return skill_id."""
    case_ids: list[int] = []
    async with async_session() as db:
        for _ in range(n_cases):
            fc = FailureCase(
                user_id=user_id,
                signal_table="hitl_refusals",
                signal_id=uuid.uuid4().int % 1_000_000,
                conversation_id="conv-i",
                replay_payload=json.dumps({"signal_kind": "hitl_refusal"}),
                pattern_hash="iter_hash",
                tier_llm="B",
            )
            db.add(fc)
            await db.flush()
            case_ids.append(fc.id)
        skill = LearnedSkill(
            user_id=user_id,
            name="iter-test",
            description="A test candidate",
            content=content,
            frontmatter_json="{}",
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=iteration_count,
            from_failure_case_ids=json.dumps(case_ids),
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        return skill.id


# ── Fakes ───────────────────────────────────────────────────────────────────


class _FakeLLMResponse:
    def __init__(self, content: str, in_tok: int = 500, out_tok: int = 100):
        self.content = content
        self.usage_metadata = {"input_tokens": in_tok, "output_tokens": out_tok}
        self.response_metadata = {"model_name": "claude-opus-fake"}


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[Any] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return _FakeLLMResponse(self._content)


_PATCHED_PLAYBOOK = """---
name: iter-test
description: Patched version that addresses the judge rationale.
tags: [test]
---

# Patched
## When this applies
- specific trigger
## Procedure
1. concrete step
## What NOT to do
- exact forbidden move
"""


# ────────────────────────────────────────────────────────────────────────
# patch_skill
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_skill_happy_path(_seeded_user, monkeypatch):
    skill_id = await _seed_candidate(_seeded_user, iteration_count=1)
    fake = _FakeLLM(_PATCHED_PLAYBOOK)

    async def _fake_llm(*, force_fallback=False):
        return fake, "primary"
    monkeypatch.setattr(skill_iteration, "get_tier_s_llm", _fake_llm)

    out = await patch_skill(skill_id, "too vague — name the actual tool")

    assert out["status"] == "patched"
    assert out["iteration_count"] == 2
    assert out["provider_pick"] == "primary"
    assert out["tokens_in"] == 500
    assert out["estimated_cost_usd"] > 0

    # DB updated
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert skill.iteration_count == 2
        assert "Patched" in skill.content
        assert "specific trigger" in skill.content
        assert skill.last_eval_score is None  # reset


@pytest.mark.asyncio
async def test_patch_skill_max_iterations_gate(_seeded_user):
    """Once iteration_count reaches MAX_ITERATIONS, patch_skill must
    refuse to spend more tokens and return max_iterations_reached."""
    skill_id = await _seed_candidate(_seeded_user, iteration_count=MAX_ITERATIONS)
    out = await patch_skill(skill_id, "doesn't matter")
    assert out["status"] == "max_iterations_reached"
    assert out["iteration_count"] == MAX_ITERATIONS


@pytest.mark.asyncio
async def test_patch_skill_not_found(_seeded_user):
    out = await patch_skill("nope", "rationale")
    assert out["status"] == "skill_not_found"


@pytest.mark.asyncio
async def test_patch_skill_no_provider(_seeded_user, monkeypatch):
    skill_id = await _seed_candidate(_seeded_user)

    async def _fake_llm(*, force_fallback=False):
        return None, "none"
    monkeypatch.setattr(skill_iteration, "get_tier_s_llm", _fake_llm)

    out = await patch_skill(skill_id, "x")
    assert out["status"] == "no_provider"


@pytest.mark.asyncio
async def test_patch_skill_llm_call_failed(_seeded_user, monkeypatch):
    skill_id = await _seed_candidate(_seeded_user)

    class _Exploder:
        async def ainvoke(self, messages):
            raise RuntimeError("simulated outage")

    async def _fake_llm(*, force_fallback=False):
        return _Exploder(), "primary"
    monkeypatch.setattr(skill_iteration, "get_tier_s_llm", _fake_llm)

    out = await patch_skill(skill_id, "x")
    assert out["status"] == "llm_call_failed"

    # Content unchanged
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert "Original" in skill.content
        assert skill.iteration_count == 1  # unchanged


@pytest.mark.asyncio
async def test_patch_skill_parse_failed(_seeded_user, monkeypatch):
    skill_id = await _seed_candidate(_seeded_user)
    fake = _FakeLLM("the patcher forgot the strict-output rule and wrote prose")

    async def _fake_llm(*, force_fallback=False):
        return fake, "primary"
    monkeypatch.setattr(skill_iteration, "get_tier_s_llm", _fake_llm)

    out = await patch_skill(skill_id, "x")
    assert out["status"] == "parse_failed"

    # Content unchanged
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert "Original" in skill.content


# ────────────────────────────────────────────────────────────────────────
# mark_rejected
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_rejected_flips_status(_seeded_user):
    skill_id = await _seed_candidate(_seeded_user)
    ok = await mark_rejected(skill_id, "test rejection reason")
    assert ok is True
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert skill.status == SkillStatus.REJECTED
        assert "test rejection" in (skill.rationale or "")


@pytest.mark.asyncio
async def test_mark_rejected_unknown_id(_seeded_user):
    ok = await mark_rejected("nope")
    assert ok is False


# ────────────────────────────────────────────────────────────────────────
# Orchestrator — run_full_loop
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_full_loop_no_failure_cases(_seeded_user):
    out = await run_full_loop(user_id=_seeded_user, batch_size=3)
    assert out["totals"] == {"drafts": 0, "passed": 0, "rejected": 0, "errored": 0}
    assert out["loops"] == []


@pytest.mark.asyncio
async def test_run_full_loop_pass_first_attempt(_seeded_user, monkeypatch):
    """Creator drafts, evaluator passes on attempt 1, loop exits early."""
    # Seed a failure_case so creator finds something to do
    async with async_session() as db:
        fc = FailureCase(
            user_id=_seeded_user,
            signal_table="hitl_refusals",
            signal_id=1,
            conversation_id="conv",
            replay_payload=json.dumps({"signal_kind": "hitl_refusal"}),
            pattern_hash="lup_hash",
            tier_llm="B",
        )
        db.add(fc)
        await db.commit()

    creator_response = """---
name: lup-test
description: Test playbook from orchestrator pass-first scenario.
---
# OK
content
"""
    creator_fake = _FakeLLM(creator_response)
    eval_fake = _FakeLLM('{"score": 85, "verdict": "pass", "rationale": "good"}')

    async def _fake_creator_llm(*, force_fallback=False):
        return creator_fake, "primary"

    async def _fake_eval_llm(*, force_fallback=False):
        return eval_fake, "primary"

    monkeypatch.setattr(skill_creator, "get_tier_s_llm", _fake_creator_llm)
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_eval_llm)

    out = await run_full_loop(user_id=_seeded_user, batch_size=3)

    assert out["totals"]["drafts"] == 1
    assert out["totals"]["passed"] == 1
    assert out["totals"]["rejected"] == 0
    assert len(out["loops"]) == 1
    loop = out["loops"][0]
    assert loop["final_status"] == "pass"
    assert loop["final_score"] == 85
    assert len(loop["evals"]) == 1  # passed on first attempt
    assert loop["patches"] == []  # no patch needed


@pytest.mark.asyncio
async def test_run_full_loop_iterates_then_passes(_seeded_user, monkeypatch):
    """Eval fails first → patch → eval passes second. Loop reports
    iterations_used=2."""
    async with async_session() as db:
        db.add(FailureCase(
            user_id=_seeded_user,
            signal_table="hitl_refusals",
            signal_id=1,
            conversation_id="c",
            replay_payload=json.dumps({"signal_kind": "hitl_refusal"}),
            pattern_hash="iter_pass_hash",
            tier_llm="B",
        ))
        await db.commit()

    creator_response = """---
name: iter-pass
description: Will need one patch.
---
# v1
content"""

    creator_fake = _FakeLLM(creator_response)

    eval_call = {"n": 0}

    class _EvalCounter:
        async def ainvoke(self, messages):
            eval_call["n"] += 1
            if eval_call["n"] == 1:
                return _FakeLLMResponse(
                    '{"score": 30, "verdict": "fail", "rationale": "too vague"}'
                )
            return _FakeLLMResponse(
                '{"score": 80, "verdict": "pass", "rationale": "now concrete"}'
            )

    patch_fake = _FakeLLM("""---
name: iter-pass
description: Patched and now concrete.
---
# v2
content""")

    async def _fake_creator_llm(*, force_fallback=False):
        return creator_fake, "primary"

    async def _fake_eval_llm(*, force_fallback=False):
        return _EvalCounter(), "primary"

    async def _fake_patch_llm(*, force_fallback=False):
        return patch_fake, "primary"

    monkeypatch.setattr(skill_creator, "get_tier_s_llm", _fake_creator_llm)
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_eval_llm)
    monkeypatch.setattr(skill_iteration, "get_tier_s_llm", _fake_patch_llm)

    out = await run_full_loop(user_id=_seeded_user, batch_size=3)

    assert out["totals"]["passed"] == 1
    loop = out["loops"][0]
    assert loop["final_status"] == "pass"
    assert len(loop["evals"]) == 2
    assert len(loop["patches"]) == 1
    assert loop["patches"][0]["status"] == "patched"


@pytest.mark.asyncio
async def test_run_full_loop_rejects_after_max_iterations(_seeded_user, monkeypatch):
    """If every eval fails, after max_iterations attempts the skill is
    marked rejected and the loop reports it."""
    async with async_session() as db:
        db.add(FailureCase(
            user_id=_seeded_user,
            signal_table="hitl_refusals",
            signal_id=1,
            conversation_id="c",
            replay_payload=json.dumps({"signal_kind": "hitl_refusal"}),
            pattern_hash="reject_hash",
            tier_llm="B",
        ))
        await db.commit()

    creator_response = """---
name: reject-me
description: Always fails the judge.
---
# nope
content"""

    creator_fake = _FakeLLM(creator_response)
    eval_fake = _FakeLLM('{"score": 20, "verdict": "fail", "rationale": "bad"}')

    patch_fake = _FakeLLM("""---
name: reject-me
description: Also bad after patching.
---
# still nope
content""")

    async def _fake_creator_llm(*, force_fallback=False):
        return creator_fake, "primary"

    async def _fake_eval_llm(*, force_fallback=False):
        return eval_fake, "primary"

    async def _fake_patch_llm(*, force_fallback=False):
        return patch_fake, "primary"

    monkeypatch.setattr(skill_creator, "get_tier_s_llm", _fake_creator_llm)
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_eval_llm)
    monkeypatch.setattr(skill_iteration, "get_tier_s_llm", _fake_patch_llm)

    out = await run_full_loop(user_id=_seeded_user, batch_size=3, max_iterations=3)

    assert out["totals"]["rejected"] == 1
    loop = out["loops"][0]
    assert loop["final_status"] == "rejected"
    assert len(loop["evals"]) == 3  # 3 attempts then stop
    assert len(loop["patches"]) == 2  # patch between attempts, not after the last

    # DB confirms rejection
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == loop["skill_id"])
        )).scalar_one()
        assert skill.status == SkillStatus.REJECTED


@pytest.mark.asyncio
async def test_run_full_loop_no_user_id():
    out = await run_full_loop(user_id="", batch_size=3)
    assert "error" in out
    assert out["totals"] == {"drafts": 0, "passed": 0, "rejected": 0, "errored": 0}


# ────────────────────────────────────────────────────────────────────────
# Admin router (lightweight — direct handler call)
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_candidates_returns_only_candidates_by_default(_seeded_user):
    """The default `status` filter is "candidate" — active / rejected
    skills must not leak into the default response."""
    from app.routers.learning_skills import list_candidates

    # Seed: 1 candidate, 1 active, 1 rejected for the same user
    async with async_session() as db:
        for status, name in [
            (SkillStatus.CANDIDATE, "c1"),
            (SkillStatus.ACTIVE, "a1"),
            (SkillStatus.REJECTED, "r1"),
        ]:
            db.add(LearnedSkill(
                user_id=_seeded_user,
                name=name,
                description=f"skill {name}",
                content="# x",
                frontmatter_json="{}",
                status=status,
                source=SkillSource.AUTO_GENERATED,
                iteration_count=1,
                from_failure_case_ids="[]",
            ))
        await db.commit()
        # We call the handler directly with the seeded session
        rows = await list_candidates(
            user_id=_seeded_user,
            status=None,  # default → candidate
            limit=50,
            _admin=None,
            db=db,
        )

    names = [r.name for r in rows]
    assert "c1" in names
    assert "a1" not in names
    assert "r1" not in names


@pytest.mark.asyncio
async def test_list_candidates_invalid_status_400(_seeded_user):
    """An unknown status filter must 400, not 500."""
    from fastapi import HTTPException
    from app.routers.learning_skills import list_candidates

    async with async_session() as db:
        with pytest.raises(HTTPException) as exc:
            await list_candidates(
                user_id=_seeded_user,
                status="totally-bogus",
                limit=50,
                _admin=None,
                db=db,
            )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_run_skill_creator_endpoint_passes_kwargs(_seeded_user, monkeypatch):
    """The endpoint must thread user_id / batch_size / max_iterations
    into the orchestrator without dropping any arg."""
    from app.routers.learning_skills import SkillCreatorRunRequest, run_skill_creator

    captured: dict[str, Any] = {}

    async def _fake_orchestrator(**kwargs):
        captured.update(kwargs)
        return {"totals": {"drafts": 2, "passed": 1, "rejected": 1, "errored": 0}}

    monkeypatch.setattr(
        "app.routers.learning_skills.run_full_loop", _fake_orchestrator,
    )

    body = SkillCreatorRunRequest(
        user_id=_seeded_user, batch_size=4, max_iterations=2,
    )
    result = await run_skill_creator(body, _admin=None)
    assert captured == {
        "user_id": _seeded_user,
        "batch_size": 4,
        "max_iterations": 2,
    }
    assert result["totals"]["passed"] == 1
