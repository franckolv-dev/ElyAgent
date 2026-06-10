# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_graduation_codegen.py
# @brief      Sprint 4d J4 — codegen de graduation (fichier core + test +
#             manifest), dry-run complet, garde d'unicité au chargement.
# @license    Elastic License 2.0
# =============================================================================
"""Pins J4 : la mécanique de conversion learned → core.

Run with:  cd backend && python -m pytest tests/test_graduation_codegen.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.services.learning import learned_tools_runtime as runtime
from app.services.learning.graduation_codegen import (
    GRADUATED_PKG_DIR,
    build_manifest,
    build_test_file,
    build_tool_file,
    dry_run_graduation,
    graduated_test_path,
    graduated_tool_path,
    scan_composition_deps,
)

# Source canonique valide (scaffold V2, stdlib only) — la même famille que
# le scénario bench learned_tool_exec.
_VALID_SOURCE = '''
from __future__ import annotations

import statistics

from langchain_core.tools import tool

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,
    skill_name="grad_mean_ms",
    skill_display_name="Mean latency",
    skill_description="Mean of a list of latencies in ms.",
    skill_icon="🧮",
    enabled_by_default=False,
)
@tool
def grad_mean_ms(values: str) -> str:
    """Compute the mean of comma-separated latency values in ms."""
    parsed = [float(v.strip()) for v in values.split(",") if v.strip()]
    if not parsed:
        return "no values"
    return str(statistics.mean(parsed))
'''


@pytest_asyncio.fixture
async def seeded_user():
    await init_db()
    from app.models.user import User
    uid = "u_grad_cg"
    async with async_session() as db:
        existing = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id=uid, username="grad_codegen_test_user",
                email="u_grad_cg@test.local", hashed_password="x",
            ))
            await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.commit()


def _make_skill(uid: str, *, name: str = "grad_mean_ms",
                content: str = _VALID_SOURCE, use_count: int = 50,
                age_days: int = 30, status: str = SkillStatus.ACTIVE) -> LearnedSkill:
    return LearnedSkill(
        id=str(uuid.uuid4()), user_id=uid, name=name,
        description="test", content=content,
        content_format=SkillContentFormat.PYTHON_TOOL,
        frontmatter_json="{}", tool_profile="pure", status=status,
        source=SkillSource.AUTO_GENERATED, iteration_count=1,
        from_failure_case_ids="[]", use_count=use_count,
        rationale="Auto-generated for tests",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=age_days),
    )


# ── Artefacts ─────────────────────────────────────────────────────────────────

class TestCodegen:
    def test_paths_are_slugged_and_stable(self):
        assert graduated_tool_path("grad_mean_ms") == (
            f"{GRADUATED_PKG_DIR}/grad_mean_ms_tool.py"
        )
        assert graduated_test_path("grad_mean_ms") == (
            "backend/tests/test_graduated_grad_mean_ms.py"
        )
        # un nom hostile ne sort jamais du slug [a-z0-9_] — pas de
        # traversée de chemin possible dans le path généré
        import re as _re
        hostile = graduated_tool_path("évil/../name")
        module_part = hostile[len(GRADUATED_PKG_DIR) + 1:]
        assert _re.fullmatch(r"[a-z0-9_]+_tool\.py", module_part)
        assert ".." not in hostile

    def test_tool_file_preserves_content_and_adds_provenance(self, seeded_user):
        skill = _make_skill(seeded_user)
        manifest = build_manifest(skill, {"stats": {"invocations": 50}, "thresholds": {}, "gates": []})
        path, content = build_tool_file(skill, manifest)
        assert path.endswith("grad_mean_ms_tool.py")
        # le content du skill est repris À L'IDENTIQUE (version éprouvée)
        assert _VALID_SOURCE.strip() in content
        # provenance + licence
        assert "PROVENANCE" in content
        assert skill.id in content
        assert "Elastic License 2.0" in content

    def test_manifest_truncates_user_id(self, seeded_user):
        skill = _make_skill(seeded_user)
        manifest = build_manifest(skill, {"stats": {}, "thresholds": {}, "gates": []})
        assert manifest["origin_user"] == seeded_user[:8]
        assert len(manifest["origin_user"]) <= 8
        assert manifest["tool_name"] == "grad_mean_ms"

    def test_test_file_without_smoke_kwargs(self, seeded_user):
        skill = _make_skill(seeded_user)
        path, content = build_test_file(skill, None)
        assert path == "backend/tests/test_graduated_grad_mean_ms.py"
        assert "test_grad_mean_ms_is_a_bindable_tool" in content
        assert "smoke_invocation" not in content

    def test_test_file_with_smoke_kwargs_invokes(self, seeded_user):
        skill = _make_skill(seeded_user)
        _, content = build_test_file(skill, {"values": "1, 2, 3"})
        assert "test_grad_mean_ms_smoke_invocation" in content
        assert '"values"' in content
        # le test généré doit être du Python valide
        compile(content, "generated_test.py", "exec")


# ── Composition ───────────────────────────────────────────────────────────────

class TestCompositionScan:
    def test_no_deps_is_ok(self):
        report = scan_composition_deps(_VALID_SOURCE)
        assert report == {"targets": [], "missing": [], "ok": True}

    def test_known_dep_passes(self, monkeypatch):
        import app.services.learning.learned_tool_dispatch as dispatch
        monkeypatch.setattr(dispatch, "composable_tool_names", lambda: {"web_search"})
        src = 'result = await call_tool("web_search", {"q": "x"})'
        report = scan_composition_deps(src)
        assert report["ok"] is True and report["targets"] == ["web_search"]

    def test_missing_dep_blocks(self, monkeypatch):
        import app.services.learning.learned_tool_dispatch as dispatch
        monkeypatch.setattr(dispatch, "composable_tool_names", lambda: set())
        src = 'await call_tool("vanished_tool", {})'
        report = scan_composition_deps(src)
        assert report["ok"] is False and report["missing"] == ["vanished_tool"]


# ── Dry-run de bout en bout ───────────────────────────────────────────────────

class TestDryRun:
    @pytest.mark.asyncio
    async def test_eligible_valid_skill_is_ready(self, seeded_user):
        skill = _make_skill(seeded_user)
        async with async_session() as db:
            db.add(skill)
            await db.commit()
            await db.refresh(skill)
            result = await dry_run_graduation(db, skill, smoke_kwargs={"values": "1, 3"})
        assert result["revalidation"]["ok"] is True
        assert result["composition"]["ok"] is True
        assert result["graduation"]["eligible"] is True
        assert result["ready"] is True
        paths = [f["path"] for f in result["files"]]
        assert f"{GRADUATED_PKG_DIR}/__init__.py" in paths
        assert f"{GRADUATED_PKG_DIR}/grad_mean_ms_tool.py" in paths
        assert "backend/tests/test_graduated_grad_mean_ms.py" in paths
        init_file = next(f for f in result["files"] if f["path"].endswith("__init__.py"))
        assert init_file["create_only"] is True

    @pytest.mark.asyncio
    async def test_not_eligible_skill_not_ready_but_previews(self, seeded_user):
        skill = _make_skill(seeded_user, use_count=2)  # < 10 invocations
        async with async_session() as db:
            db.add(skill)
            await db.commit()
            await db.refresh(skill)
            result = await dry_run_graduation(db, skill)
        assert result["ready"] is False
        assert result["graduation"]["eligible"] is False
        # l'aperçu des fichiers reste produit (l'admin voit ce qui sortirait)
        assert len(result["files"]) == 3

    @pytest.mark.asyncio
    async def test_invalid_source_fails_revalidation(self, seeded_user):
        bad = _VALID_SOURCE.replace("import statistics", "import os")
        skill = _make_skill(seeded_user, content=bad)
        async with async_session() as db:
            db.add(skill)
            await db.commit()
            await db.refresh(skill)
            result = await dry_run_graduation(db, skill)
        assert result["revalidation"]["ok"] is False
        assert result["ready"] is False


# ── Garde d'unicité au chargement ────────────────────────────────────────────

class TestReconcileGraduated:
    @pytest.mark.asyncio
    async def test_core_collision_flips_to_graduated(self, seeded_user, monkeypatch):
        skill = _make_skill(seeded_user, name="now_core_tool")
        async with async_session() as db:
            db.add(skill)
            await db.commit()
            await db.refresh(skill)
        monkeypatch.setattr(runtime, "_core_tool_names", lambda: {"now_core_tool"})
        survivors = await runtime._reconcile_graduated([skill])
        assert survivors == []
        async with async_session() as db:
            fresh = await db.get(LearnedSkill, skill.id)
            assert fresh.status == SkillStatus.GRADUATED

    @pytest.mark.asyncio
    async def test_no_collision_leaves_rows_untouched(self, seeded_user, monkeypatch):
        skill = _make_skill(seeded_user, name="still_learned_tool")
        async with async_session() as db:
            db.add(skill)
            await db.commit()
            await db.refresh(skill)
        monkeypatch.setattr(runtime, "_core_tool_names", lambda: {"unrelated_tool"})
        survivors = await runtime._reconcile_graduated([skill])
        assert [s.id for s in survivors] == [skill.id]
        async with async_session() as db:
            fresh = await db.get(LearnedSkill, skill.id)
            assert fresh.status == SkillStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_registry_failure_fails_open(self, seeded_user, monkeypatch):
        """Registre indisponible → AUCUNE bascule (on ne gradue pas sur un
        doute), les rows restent bindables."""
        skill = _make_skill(seeded_user, name="cautious_tool")
        monkeypatch.setattr(runtime, "_core_tool_names", lambda: set())
        survivors = await runtime._reconcile_graduated([skill])
        assert len(survivors) == 1


# ── Statuts & transitions ─────────────────────────────────────────────────────

class TestGraduatedStatus:
    def test_graduated_in_all_statuses(self):
        assert SkillStatus.GRADUATED == "graduated"
        assert SkillStatus.GRADUATED in SkillStatus.ALL
        # jamais injecté au prompt : seul ACTIVE est visible
        assert SkillStatus.GRADUATED not in SkillStatus.PROMPT_VISIBLE

    def test_transitions_active_to_graduated_and_back(self):
        from app.routers.learning_skills import _ALLOWED_TRANSITIONS
        assert SkillStatus.GRADUATED in _ALLOWED_TRANSITIONS[SkillStatus.ACTIVE]
        # un-graduation (PR refusée / revert) : retour au binding dynamique
        assert _ALLOWED_TRANSITIONS[SkillStatus.GRADUATED] == {SkillStatus.ACTIVE}
