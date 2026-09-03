# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_graduation_stats.py
# @brief      Sprint 4d J1 — tool_origin à la capture + stats/gates de
#             graduation (seuils souples 10 inv / 14 j / 7 j).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins J1 : la vérité par outil sur laquelle la graduation (J3-J5) s'appuie.

Run with:  cd backend && python -m pytest tests/test_graduation_stats.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import async_session, init_db
from app.models.error_log import ErrorLog
from app.models.hitl_refusal import HitlRefusal
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.services.learning.graduation import (
    ORIGIN_BUILTIN,
    ORIGIN_LEARNED,
    compute_graduation_stats,
    graduation_thresholds,
    tool_origin,
)
from app.services.learning.signals import record_hitl_refusal, record_tool_error


@pytest_asyncio.fixture
async def seeded_user():
    await init_db()
    from app.models.user import User
    uid = "u_grad"
    async with async_session() as db:
        existing = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id=uid,
                username="graduation_test_user",
                email="u_grad@test.local",
                hashed_password="x",
            ))
            await db.commit()
    yield uid


def _make_skill(uid: str, *, name: str, status: str = SkillStatus.ACTIVE,
                profile: str = "pure", use_count: int = 0,
                age_days: int = 30) -> LearnedSkill:
    return LearnedSkill(
        id=str(uuid.uuid4()),
        user_id=uid,
        name=name,
        description="test tool",
        content="# python source",
        content_format=SkillContentFormat.PYTHON_TOOL,
        frontmatter_json="{}",
        tool_profile=profile,
        status=status,
        source=SkillSource.AUTO_GENERATED,
        iteration_count=1,
        from_failure_case_ids="[]",
        use_count=use_count,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=age_days),
    )


async def _seed_skill(skill: LearnedSkill) -> LearnedSkill:
    async with async_session() as db:
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
    return skill


async def _cleanup(uid: str, *names: str) -> None:
    from sqlalchemy import delete
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        for model in (ErrorLog, HitlRefusal):
            await db.execute(delete(model).where(model.user_id == uid))
        await db.commit()


# ── tool_origin : posé à la capture ──────────────────────────────────────────

class TestToolOrigin:
    @pytest.mark.asyncio
    async def test_active_python_tool_is_learned(self, seeded_user):
        await _seed_skill(_make_skill(seeded_user, name="my_gen_tool"))
        try:
            assert await tool_origin(seeded_user, "my_gen_tool") == ORIGIN_LEARNED
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_builtin_and_unknown_names(self, seeded_user):
        assert await tool_origin(seeded_user, "gmail_send_email") == ORIGIN_BUILTIN
        assert await tool_origin(seeded_user, "") == ORIGIN_BUILTIN
        assert await tool_origin("", "x") == ORIGIN_BUILTIN

    @pytest.mark.asyncio
    async def test_non_active_statuses_are_builtin(self, seeded_user):
        """Seuls les ACTIFS sont bindés au LLM — un candidate/archived/graduated
        homonyme ne doit PAS attribuer les signaux au learned tool."""
        await _seed_skill(_make_skill(seeded_user, name="dormant_tool",
                                      status=SkillStatus.ARCHIVED))
        try:
            assert await tool_origin(seeded_user, "dormant_tool") == ORIGIN_BUILTIN
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_record_tool_error_stamps_origin(self, seeded_user):
        await _seed_skill(_make_skill(seeded_user, name="stamped_tool"))
        try:
            row_id = await record_tool_error(
                user_id=seeded_user, tool_name="stamped_tool",
                args={}, error_type="ValueError", error_msg="boom",
            )
            builtin_id = await record_tool_error(
                user_id=seeded_user, tool_name="gmail_send_email",
                args={}, error_type="ValueError", error_msg="boom",
            )
            async with async_session() as db:
                learned_row = await db.get(ErrorLog, row_id)
                builtin_row = await db.get(ErrorLog, builtin_id)
            assert learned_row.tool_origin == ORIGIN_LEARNED
            assert builtin_row.tool_origin == ORIGIN_BUILTIN
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_record_hitl_refusal_stamps_origin(self, seeded_user):
        await _seed_skill(_make_skill(seeded_user, name="refused_tool"))
        try:
            row_id = await record_hitl_refusal(
                user_id=seeded_user, conversation_id="c1",
                tool_name="refused_tool", args={},
                action_description="do it", decision="deny", reason="user-provided",
            )
            async with async_session() as db:
                row = await db.get(HitlRefusal, row_id)
            assert row.tool_origin == ORIGIN_LEARNED
        finally:
            await _cleanup(seeded_user)


# ── Seuils ────────────────────────────────────────────────────────────────────

class TestThresholds:
    def test_soft_defaults_franck_2026_06_10(self):
        """Arbitrage Franck : profil souple tant que le funnel est naissant."""
        th = graduation_thresholds()
        assert th == {"min_invocations": 10, "error_free_days": 14, "min_age_days": 7}

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("GRADUATION_MIN_INVOCATIONS", "25")
        monkeypatch.setenv("GRADUATION_ERROR_FREE_DAYS", "30")
        monkeypatch.setenv("GRADUATION_MIN_AGE_DAYS", "14")
        th = graduation_thresholds()
        assert th == {"min_invocations": 25, "error_free_days": 30, "min_age_days": 14}

    def test_garbage_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("GRADUATION_MIN_INVOCATIONS", "beaucoup")
        assert graduation_thresholds()["min_invocations"] == 10


# ── compute_graduation_stats : gates ─────────────────────────────────────────

class TestGraduationGates:
    async def _stats_for(self, skill):
        async with async_session() as db:
            merged = await db.merge(skill)
            return await compute_graduation_stats(db, merged)

    @pytest.mark.asyncio
    async def test_eligible_when_all_gates_pass(self, seeded_user):
        skill = await _seed_skill(_make_skill(
            seeded_user, name="proven_tool", use_count=12, age_days=10,
        ))
        try:
            report = await self._stats_for(skill)
            assert report["eligible"] is True
            assert all(g["ok"] for g in report["gates"])
            assert report["stats"]["invocations"] == 12
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_not_enough_invocations(self, seeded_user):
        skill = await _seed_skill(_make_skill(
            seeded_user, name="young_tool", use_count=9, age_days=10,
        ))
        try:
            report = await self._stats_for(skill)
            assert report["eligible"] is False
            gate = next(g for g in report["gates"] if g["key"] == "invocations")
            assert gate["ok"] is False and gate["value"] == 9
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_recent_learned_error_blocks(self, seeded_user):
        skill = await _seed_skill(_make_skill(
            seeded_user, name="flaky_tool", use_count=50, age_days=60,
        ))
        try:
            await record_tool_error(
                user_id=seeded_user, tool_name="flaky_tool",
                args={}, error_type="RuntimeError", error_msg="kaboom",
            )
            report = await self._stats_for(skill)
            assert report["eligible"] is False
            gate = next(g for g in report["gates"] if g["key"] == "error_free")
            assert gate["ok"] is False and gate["value"] == 1
            assert report["stats"]["last_error_at"] is not None
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_builtin_homonym_error_does_not_block(self, seeded_user):
        """Une erreur estampillée builtin (autre outil, même nom par hasard
        APRÈS graduation par ex.) ne compte pas contre le learned tool."""
        skill = await _seed_skill(_make_skill(
            seeded_user, name="shared_name", use_count=50, age_days=60,
        ))
        try:
            async with async_session() as db:
                db.add(ErrorLog(
                    user_id=seeded_user, tool_name="shared_name",
                    args_redacted="{}", error_type="ValueError",
                    error_msg="core-side error", tool_origin="builtin",
                ))
                await db.commit()
            report = await self._stats_for(skill)
            gate = next(g for g in report["gates"] if g["key"] == "error_free")
            assert gate["ok"] is True
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_pre_j1_null_origin_error_blocks_by_prudence(self, seeded_user):
        """Row pré-J1 (origin NULL) : comptée CONTRE la graduation — un échec
        non attribuable ne doit pas l'accélérer."""
        skill = await _seed_skill(_make_skill(
            seeded_user, name="legacy_sig_tool", use_count=50, age_days=60,
        ))
        try:
            async with async_session() as db:
                db.add(ErrorLog(
                    user_id=seeded_user, tool_name="legacy_sig_tool",
                    args_redacted="{}", error_type="ValueError",
                    error_msg="old row", tool_origin=None,
                ))
                await db.commit()
            report = await self._stats_for(skill)
            gate = next(g for g in report["gates"] if g["key"] == "error_free")
            assert gate["ok"] is False
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_io_profile_supported_with_io_gates(self, seeded_user):
        """V4.1 : le profil io est supporté — gate profile verte, mais les
        gates io (returned/timeout) exigent des PREUVES sandbox : à zéro
        dispatch, elles sont rouges (zéro preuve = pas de graduation)."""
        skill = await _seed_skill(_make_skill(
            seeded_user, name="io_tool", profile="io", use_count=50, age_days=60,
        ))
        try:
            report = await self._stats_for(skill)
            gate = next(g for g in report["gates"] if g["key"] == "profile_supported")
            assert gate["ok"] is True
            returned_gate = next(g for g in report["gates"] if g["key"] == "io_returned_rate")
            timeout_gate = next(g for g in report["gates"] if g["key"] == "io_timeout_rate")
            assert returned_gate["ok"] is False     # 0 dispatch = 0 preuve
            assert timeout_gate["ok"] is False
            assert report["eligible"] is False
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_io_gates_with_healthy_dispatch_history(self, seeded_user):
        """20 dispatchs : 18 returned, 1 raised, 1 timeout → returned 90 % ✓,
        timeout 5 % (= seuil max(1, 5%)=1, 1<1 faux) → la gate timeout est
        STRICTE : exactement à la limite, elle bloque."""
        from app.models.io_tool_dispatch import IoToolDispatch
        skill = await _seed_skill(_make_skill(
            seeded_user, name="io_proven", profile="io", use_count=0, age_days=60,
        ))
        try:
            async with async_session() as db:
                for outcome in (["returned"] * 18 + ["raised"] + ["timeout"]):
                    db.add(IoToolDispatch(
                        user_id=seeded_user, skill_id=skill.id,
                        tool_name="io_proven", outcome=outcome, duration_ms=120,
                        secrets_used_json="[]", network_allow_json="[]",
                    ))
                await db.commit()
            report = await self._stats_for(skill)
            returned_gate = next(g for g in report["gates"] if g["key"] == "io_returned_rate")
            assert returned_gate["ok"] is True and returned_gate["value"] == "18/20"
            timeout_gate = next(g for g in report["gates"] if g["key"] == "io_timeout_rate")
            assert timeout_gate["ok"] is False and timeout_gate["value"] == "1/20"
            # les invocations comptent les dispatchs sandbox
            assert report["stats"]["invocations"] == 20
            assert report["stats"]["io_outcomes"]["returned"] == 18
        finally:
            from sqlalchemy import delete
            async with async_session() as db:
                await db.execute(delete(IoToolDispatch).where(IoToolDispatch.user_id == seeded_user))
                await db.commit()
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_pure_profile_has_no_io_gates(self, seeded_user):
        skill = await _seed_skill(_make_skill(
            seeded_user, name="pure_tool", use_count=50, age_days=60,
        ))
        try:
            report = await self._stats_for(skill)
            assert not any(g["key"].startswith("io_") for g in report["gates"])
        finally:
            await _cleanup(seeded_user)

    @pytest.mark.asyncio
    async def test_old_error_outside_window_ok(self, seeded_user):
        skill = await _seed_skill(_make_skill(
            seeded_user, name="redeemed_tool", use_count=50, age_days=60,
        ))
        try:
            async with async_session() as db:
                db.add(ErrorLog(
                    user_id=seeded_user, tool_name="redeemed_tool",
                    args_redacted="{}", error_type="ValueError",
                    error_msg="ancient", tool_origin="learned",
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                    - timedelta(days=20),
                ))
                await db.commit()
            report = await self._stats_for(skill)
            gate = next(g for g in report["gates"] if g["key"] == "error_free")
            assert gate["ok"] is True
            assert report["stats"]["last_error_at"] is not None
        finally:
            await _cleanup(seeded_user)
