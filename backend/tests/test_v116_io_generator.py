# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_v116_io_generator.py
# @brief      Sprint 4b V3 J7+J8 (v1.16.0) — le tool_creator génère le
#             profil io ; la revue admin expose les déclarations V3.
# @license    Elastic License 2.0
# =============================================================================
"""v1.16.0 — pins du générateur io (J7) et de la revue déclarations (J8)."""
from __future__ import annotations

import textwrap
import types
import uuid

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────────────────
# J7 — prompt io
# ─────────────────────────────────────────────────────────────────────────


def test_compose_user_prompt_io_carries_sandbox_context() -> None:
    from app.services.learning.tool_generator import compose_user_prompt

    prompt = compose_user_prompt(
        "appeler l'API météo",
        available_tools=["gmail_list_emails"],
        profile="io",
        allowed_egress=[".httpbin.org", ".example.com"],
        available_secret_labels=["openweather_api_key"],
    )
    assert ".httpbin.org" in prompt and ".example.com" in prompt
    assert "openweather_api_key" in prompt
    # Le contrat io ne propose PAS la composition d'outils V2
    assert "AVAILABLE TOOLS" not in prompt


def test_compose_user_prompt_pure_unchanged() -> None:
    """Rétrocompatibilité : le chemin pure garde son contrat V2 à
    l'identique (liste d'outils composables, pas de contexte sandbox)."""
    from app.services.learning.tool_generator import compose_user_prompt

    prompt = compose_user_prompt(
        "calculer fibonacci",
        available_tools=["gmail_list_emails"],
    )
    assert "AVAILABLE TOOLS" in prompt
    assert "ALLOWED EGRESS" not in prompt


def test_compose_user_prompt_io_degrades_without_context() -> None:
    from app.services.learning.tool_generator import compose_user_prompt

    prompt = compose_user_prompt(
        "appeler une API", available_tools=[], profile="io",
        allowed_egress=[], available_secret_labels=[],
    )
    assert "list unavailable" in prompt
    assert "none provisioned" in prompt


@pytest.mark.asyncio
async def test_generate_tool_source_selects_io_system_prompt(monkeypatch) -> None:
    from app.services.learning import tool_generator as tg

    captured: dict = {}

    class _FakeLLM:
        async def ainvoke(self, messages):
            captured["system"] = messages[0].content
            captured["user"] = messages[1].content
            return types.SimpleNamespace(
                content="```python\nx = 1\n```", usage_metadata=None,
                response_metadata={},
            )

    async def fake_tier_s():
        return _FakeLLM(), "deepseek"

    monkeypatch.setattr(tg, "get_tier_s_llm", fake_tier_s)

    source, info = await tg.generate_tool_source(
        task_description="appeler l'API météo",
        user_id="u1",
        profile="io",
        allowed_egress=[".example.com"],
        available_secret_labels=["meteo_key"],
    )

    assert info["profile"] == "io"
    assert "V3 IO SCOPE" in captured["system"], "le prompt système io doit être sélectionné"
    assert "get_secret" in captured["system"]
    assert ".example.com" in captured["user"]
    assert source == "x = 1"


def test_squid_allowed_domains_reads_the_real_acl() -> None:
    """La source de vérité du prompt = la même ACL que le proxy au runtime."""
    from app.services.learning.v3_declarations import squid_allowed_domains

    domains = squid_allowed_domains()
    assert ".httpbin.org" in domains
    assert ".example.com" in domains


# ─────────────────────────────────────────────────────────────────────────
# J7 — tool_creator profil io
# ─────────────────────────────────────────────────────────────────────────


_IO_SOURCE = textwrap.dedent("""
    from __future__ import annotations
    import httpx
    from langchain_core.tools import tool
    from app.skills.base import Domain
    from app.skills.decorator import register

    @register(
        domain=Domain.RESEARCH,
        skill_name="ping_example",
        skill_display_name="Ping",
        skill_description="x",
        skill_icon="i",
        enabled_by_default=False,
        network_allow=["example.com"],
        requires=["httpx"],
    )
    @tool
    def ping_example() -> int:
        \"\"\"Ping example.com.\"\"\"
        return httpx.get("https://example.com", timeout=5).status_code
""").strip()


@pytest_asyncio.fixture
async def creator_user():
    from app.database import async_session, init_db
    from app.models.user import User

    await init_db()
    uid = f"test_v116_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    yield uid
    from sqlalchemy import delete

    from app.models.learned_skill import LearnedSkill
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.mark.asyncio
async def test_creator_persists_io_profile(monkeypatch, creator_user) -> None:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.learned_skill import LearnedSkill
    from app.services.learning import tool_creator as tc

    async def fake_gen(**_kw):
        return _IO_SOURCE, {"status": "generated", "provider_pick": "deepseek"}

    fake_report = types.SimpleNamespace(
        ok=True, tool_name="ping_example",
        summary=lambda: "ok", to_json=lambda: "{}",
    )
    monkeypatch.setattr(tc, "generate_tool_source", fake_gen)
    monkeypatch.setattr(tc, "validate_tool_source", lambda *a, **kw: fake_report)

    result = await tc.generate_and_persist_tool(
        task_description="ping example.com — outil réseau",
        user_id=creator_user,
        profile="io",
    )

    assert result["status"] == "created", result
    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == result["learned_skill_id"])
        )).scalar_one()
    assert row.tool_profile == "io", (
        "le candidat doit porter tool_profile=io — sinon le runtime V3 ne "
        "le chargera jamais (load_active_io_tools filtre dessus)"
    )


@pytest.mark.asyncio
async def test_creator_validates_with_io_profile(monkeypatch, creator_user) -> None:
    """La chaîne 7 étages (J5) doit être sélectionnée — pas la chaîne pure
    qui rejetterait httpx."""
    from app.services.learning import tool_creator as tc

    seen: dict = {}

    async def fake_gen(**_kw):
        return _IO_SOURCE, {"status": "generated", "provider_pick": "deepseek"}

    def fake_validate(source, **kw):
        seen["profile"] = kw.get("profile")
        return types.SimpleNamespace(
            ok=True, tool_name="ping_example",
            summary=lambda: "ok", to_json=lambda: "{}",
        )

    monkeypatch.setattr(tc, "generate_tool_source", fake_gen)
    monkeypatch.setattr(tc, "validate_tool_source", fake_validate)

    await tc.generate_and_persist_tool(
        task_description="ping — réseau", user_id=creator_user, profile="io",
    )
    assert seen["profile"] == "io"


@pytest.mark.asyncio
async def test_creator_rejects_unknown_profile() -> None:
    from app.services.learning.tool_creator import generate_and_persist_tool

    result = await generate_and_persist_tool(
        task_description="x" * 10, user_id="u1", profile="yolo",
    )
    assert result["status"] == "error"


# ─────────────────────────────────────────────────────────────────────────
# J8 — la revue expose les déclarations V3
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_candidates_endpoint_surfaces_v3_declarations(creator_user) -> None:
    from app.database import async_session
    from app.models.learned_skill import (
        LearnedSkill,
        SkillContentFormat,
        SkillStatus,
        SkillToolProfile,
    )
    from app.routers.learning_skills import list_candidates

    async with async_session() as db:
        db.add(LearnedSkill(
            id=str(uuid.uuid4()), user_id=creator_user, name="ping_example",
            description="t", content=_IO_SOURCE,
            content_format=SkillContentFormat.PYTHON_TOOL,
            tool_profile=SkillToolProfile.IO,
            status=SkillStatus.CANDIDATE,
        ))
        await db.commit()

    async with async_session() as db:
        rows = await list_candidates(
            user_id=creator_user, status=None, limit=50, _admin=None, db=db,
        )

    assert len(rows) == 1
    out = rows[0]
    assert out.tool_profile == "io"
    assert out.v3_network_allow == ["example.com"]
    assert out.v3_requires == ["httpx"]
    assert out.v3_requires_secrets == []


def test_request_model_validates_profile() -> None:
    import pydantic

    from app.routers.learning_skills import ToolCreatorRunRequest

    ok = ToolCreatorRunRequest(
        task_description="ping example.com", user_id="u1", profile="io",
    )
    assert ok.profile == "io"

    with pytest.raises(pydantic.ValidationError):
        ToolCreatorRunRequest(
            task_description="ping example.com", user_id="u1", profile="yolo",
        )
