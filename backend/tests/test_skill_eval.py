# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_skill_eval.py
# @brief      Sprint 4b Phase 3.b — tests for the LLM-as-judge skill evaluator
# @license    Elastic License 2.0
# =============================================================================
"""Tests for ``app/services/learning/skill_eval.py``.

Three layers :
  1. Pure parser tests — ``parse_judge_response`` shape coverage
     including verdict/score consistency coercion.
  2. DB helper — `_load_skill_and_cases` handles missing skill,
     malformed case-id JSON, and the per-skill MAX_CASES_IN_PROMPT cap.
  3. End-to-end ``evaluate_skill`` with mocked tier-S — happy path,
     no-cases, no-provider, llm-call-failure, parse-failure.
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.learning import skill_eval
from app.services.learning.skill_eval import (
    MAX_CASES_IN_PROMPT,
    PASS_THRESHOLD,
    _load_skill_and_cases,
    evaluate_skill,
    parse_judge_response,
)


@pytest_asyncio.fixture
async def _seeded_user():
    await init_db()
    from app.models.user import User
    from app.models.usage_log import UsageLog
    async with async_session() as db:
        existing = (await db.execute(
            select(User).where(User.id == "se1")
        )).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="se1",
                username="skill_eval_test_user",
                email="se1@test.local",
                hashed_password="x",
            ))
            await db.commit()
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == "se1"))
        await db.execute(delete(FailureCase).where(FailureCase.user_id == "se1"))
        # Wipe tier-S usage rows — see test_skill_creator for rationale
        # (global monthly_spend isolation across test files).
        await db.execute(
            delete(UsageLog).where(
                UsageLog.user_id == "se1",
                UsageLog.skill_used.like("tier_s.%"),
            )
        )
        await db.commit()
    yield "se1"
    async with async_session() as db:
        await db.execute(
            delete(UsageLog).where(
                UsageLog.user_id == "se1",
                UsageLog.skill_used.like("tier_s.%"),
            )
        )
        await db.commit()


async def _seed_skill_with_cases(
    user_id: str,
    n_cases: int = 2,
    pattern_hash: str = "eval_hash",
    content: str = "# OK\nthis is a body",
) -> tuple[str, list[int]]:
    """Insert a candidate skill + N source failure cases. Returns
    (skill_id, list of case ids)."""
    case_ids: list[int] = []
    async with async_session() as db:
        for i in range(n_cases):
            fc = FailureCase(
                user_id=user_id,
                signal_table="hitl_refusals",
                signal_id=uuid.uuid4().int % 1_000_000,
                conversation_id="conv-e",
                replay_payload=json.dumps({
                    "signal_kind": "hitl_refusal",
                    "tool_name": "gmail_trash_emails",
                    "decision": "deny",
                }),
                pattern_hash=pattern_hash,
                tier_llm="B",
            )
            db.add(fc)
            await db.flush()
            case_ids.append(fc.id)

        skill = LearnedSkill(
            user_id=user_id,
            name="test-skill",
            description="A test skill",
            content=content,
            frontmatter_json="{}",
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids=json.dumps(case_ids),
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        return skill.id, case_ids


# ─────────────────────────────────────────────────────────────────────────
# parse_judge_response
# ─────────────────────────────────────────────────────────────────────────


def test_parse_clean_pass():
    raw = '{"score": 85, "verdict": "pass", "rationale": "names the exact tool"}'
    out = parse_judge_response(raw)
    assert out == {
        "score": 85, "verdict": "pass", "rationale": "names the exact tool",
    }


def test_parse_clean_fail():
    raw = '{"score": 30, "verdict": "fail", "rationale": "too generic"}'
    out = parse_judge_response(raw)
    assert out["score"] == 30
    assert out["verdict"] == "fail"


def test_parse_strips_markdown_fences():
    raw = """```json
{"score": 70, "verdict": "pass", "rationale": "ok"}
```"""
    out = parse_judge_response(raw)
    assert out is not None
    assert out["score"] == 70


def test_parse_strips_leading_prose():
    raw = """Here's my evaluation:

{"score": 50, "verdict": "fail", "rationale": "borderline"}

End."""
    out = parse_judge_response(raw)
    assert out is not None
    assert out["score"] == 50


def test_parse_coerces_inconsistent_verdict_to_score():
    """If the LLM says score=85 but verdict=fail, trust the score."""
    raw = '{"score": 85, "verdict": "fail", "rationale": "mismatch"}'
    out = parse_judge_response(raw)
    assert out is not None
    assert out["score"] == 85
    assert out["verdict"] == "pass"  # coerced to score-implied


def test_parse_coerces_low_score_to_fail():
    raw = '{"score": 40, "verdict": "pass", "rationale": "mismatch"}'
    out = parse_judge_response(raw)
    assert out["score"] == 40
    assert out["verdict"] == "fail"  # coerced


def test_parse_rejects_score_out_of_range():
    assert parse_judge_response('{"score": -5, "verdict": "fail", "rationale": "x"}') is None
    assert parse_judge_response('{"score": 150, "verdict": "pass", "rationale": "x"}') is None


def test_parse_rejects_missing_fields():
    assert parse_judge_response('{"score": 70, "rationale": "x"}') is None
    assert parse_judge_response('{"verdict": "pass", "rationale": "x"}') is None


def test_parse_rejects_invalid_verdict():
    raw = '{"score": 70, "verdict": "maybe", "rationale": "x"}'
    assert parse_judge_response(raw) is None


def test_parse_rejects_garbage():
    assert parse_judge_response("") is None
    assert parse_judge_response("not json") is None
    assert parse_judge_response('{"incomplete":') is None


def test_parse_caps_rationale_length():
    long = "x" * 500
    raw = json.dumps({"score": 80, "verdict": "pass", "rationale": long})
    out = parse_judge_response(raw)
    assert out is not None
    assert len(out["rationale"]) == 240


def test_pass_threshold_is_60():
    """Pin the magic number so a future refactor that bumps it gets
    surfaced in a test diff."""
    assert PASS_THRESHOLD == 60


# ─────────────────────────────────────────────────────────────────────────
# _load_skill_and_cases
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_returns_none_for_unknown_skill(_seeded_user):
    async with async_session() as db:
        skill, cases = await _load_skill_and_cases(db, "does-not-exist")
    assert skill is None
    assert cases == []


@pytest.mark.asyncio
async def test_load_returns_skill_and_cases(_seeded_user):
    skill_id, case_ids = await _seed_skill_with_cases(_seeded_user, n_cases=3)
    async with async_session() as db:
        skill, cases = await _load_skill_and_cases(db, skill_id)
    assert skill is not None
    assert sorted(c.id for c in cases) == sorted(case_ids)


@pytest.mark.asyncio
async def test_load_caps_at_max_cases_in_prompt(_seeded_user):
    """If a skill references more than MAX_CASES_IN_PROMPT cases, we
    only load the top-N to keep the prompt bounded."""
    skill_id, _ = await _seed_skill_with_cases(_seeded_user, n_cases=MAX_CASES_IN_PROMPT + 3)
    async with async_session() as db:
        _skill, cases = await _load_skill_and_cases(db, skill_id)
    assert len(cases) <= MAX_CASES_IN_PROMPT


# ─────────────────────────────────────────────────────────────────────────
# End-to-end evaluate_skill with mocked tier-S
# ─────────────────────────────────────────────────────────────────────────


class _FakeLLMResponse:
    def __init__(self, content: str, in_tok: int = 500, out_tok: int = 100):
        self.content = content
        self.usage_metadata = {"input_tokens": in_tok, "output_tokens": out_tok}
        # Use a model name that matches the `claude-opus` prefix in the
        # cost table so `estimate_cost_usd` returns a non-zero figure.
        self.response_metadata = {"model_name": "claude-opus-fake"}


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, messages):
        return _FakeLLMResponse(self._content)


@pytest.mark.asyncio
async def test_evaluate_skill_not_found(_seeded_user):
    out = await evaluate_skill("nonexistent-id")
    assert out["status"] == "skill_not_found"
    assert out["score"] is None


@pytest.mark.asyncio
async def test_evaluate_skill_no_cases(_seeded_user):
    """A skill row with from_failure_case_ids=[] must surface no_cases
    rather than 500 / crash."""
    async with async_session() as db:
        skill = LearnedSkill(
            user_id=_seeded_user,
            name="orphan-skill",
            description="No cases",
            content="# orphan",
            frontmatter_json="{}",
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=1,
            from_failure_case_ids="[]",
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        skill_id = skill.id

    out = await evaluate_skill(skill_id)
    assert out["status"] == "no_cases"
    assert out["score"] is None


@pytest.mark.asyncio
async def test_evaluate_skill_happy_path_pass(_seeded_user, monkeypatch):
    skill_id, _ = await _seed_skill_with_cases(_seeded_user)
    fake = _FakeLLM(
        '{"score": 80, "verdict": "pass", "rationale": "names the gmail tool to avoid"}'
    )

    async def _fake_get_llm(*, force_fallback=False):
        return fake, "primary"
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_get_llm)

    out = await evaluate_skill(skill_id)
    assert out["status"] == "evaluated"
    assert out["score"] == 80
    assert out["verdict"] == "pass"
    assert "gmail tool" in out["rationale"]
    assert out["provider_pick"] == "primary"
    assert out["tokens_in"] == 500
    assert out["estimated_cost_usd"] > 0

    # Score persisted
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert skill.last_eval_score == 80


@pytest.mark.asyncio
async def test_evaluate_skill_happy_path_fail(_seeded_user, monkeypatch):
    skill_id, _ = await _seed_skill_with_cases(_seeded_user)
    fake = _FakeLLM('{"score": 30, "verdict": "fail", "rationale": "too vague"}')

    async def _fake_get_llm(*, force_fallback=False):
        return fake, "primary"
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_get_llm)

    out = await evaluate_skill(skill_id)
    assert out["status"] == "evaluated"
    assert out["score"] == 30
    assert out["verdict"] == "fail"


@pytest.mark.asyncio
async def test_evaluate_skill_no_provider(_seeded_user, monkeypatch):
    skill_id, _ = await _seed_skill_with_cases(_seeded_user)

    async def _fake_get_llm(*, force_fallback=False):
        return None, "none"
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_get_llm)

    out = await evaluate_skill(skill_id)
    assert out["status"] == "no_provider"
    assert out["score"] is None


@pytest.mark.asyncio
async def test_evaluate_skill_llm_call_failed(_seeded_user, monkeypatch):
    """If the tier-S call raises, we surface llm_call_failed and the
    skill's last_eval_score remains untouched."""
    skill_id, _ = await _seed_skill_with_cases(_seeded_user)

    class _ExplodingLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("simulated tier-S outage")

    async def _fake_get_llm(*, force_fallback=False):
        return _ExplodingLLM(), "primary"
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_get_llm)

    out = await evaluate_skill(skill_id)
    assert out["status"] == "llm_call_failed"
    assert "simulated tier-S outage" in (out["rationale"] or "")
    # Score not persisted
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert skill.last_eval_score is None


@pytest.mark.asyncio
async def test_evaluate_skill_parse_failed(_seeded_user, monkeypatch):
    """A malformed judge response must yield status=parse_failed,
    score not persisted."""
    skill_id, _ = await _seed_skill_with_cases(_seeded_user)
    fake = _FakeLLM("the judge forgot to output JSON and wrote prose instead")

    async def _fake_get_llm(*, force_fallback=False):
        return fake, "primary"
    monkeypatch.setattr(skill_eval, "get_tier_s_llm", _fake_get_llm)

    out = await evaluate_skill(skill_id)
    assert out["status"] == "parse_failed"
    assert out["score"] is None
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        assert skill.last_eval_score is None
