# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_v115_io_integration.py
# @brief      Sprint 4b V3 — intégration agent (v1.15.0) : les outils io
#             rejoignent les deux coutures bind/dispatch + canary HITL
#             (design note §5.6).
# @license    Elastic License 2.0
# =============================================================================
"""v1.15.0 — pins de l'intégration agent du pipeline io.

Le pipeline V3 (PRs #67-#71) était fonctionnellement complet mais DORMANT :
l'agent n'appelait jamais ``load_active_io_tools``. Cette intégration
l'accroche aux deux coutures partagées (``append_learned_tools`` au bind,
``merge_into_tool_map`` au dispatch — chat ET missions en héritent) et
ajoute la période canary : les N premières invocations d'un outil io
passent par HITL.
"""
from __future__ import annotations

import types
import uuid

import pytest
import pytest_asyncio


def _fake_tool(name: str):
    return types.SimpleNamespace(name=name)


# ─────────────────────────────────────────────────────────────────────────
# Coutures bind/dispatch
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seams_unchanged_when_io_flag_off(monkeypatch) -> None:
    """Flag off (défaut) : zéro changement de comportement — le loader io
    retourne []."""
    from app.services.learning import learned_tools_runtime as rt

    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", raising=False)

    async def no_pure(_uid):
        return []

    monkeypatch.setattr(rt, "load_active_python_tools", no_pure)

    builtin = _fake_tool("gmail_send_email")
    out = await rt.append_learned_tools([builtin], "u1")
    assert out == [builtin]

    tool_map = {"gmail_send_email": builtin}
    await rt.merge_into_tool_map(tool_map, "u1")
    assert tool_map == {"gmail_send_email": builtin}


@pytest.mark.asyncio
async def test_io_tools_join_both_seams(monkeypatch) -> None:
    """Flag on : les outils io sont bindés ET dispatchables, sans jamais
    shadower un builtin ni un outil pure homonyme (pure gagne)."""
    from app.services.learning import learned_tools_runtime as rt
    from app.services.learning import learned_tools_runtime_io as rio

    pure = _fake_tool("mon_outil_pure")
    io_new = _fake_tool("appeler_api_meteo")
    io_collide = _fake_tool("mon_outil_pure")  # collision : pure doit gagner
    builtin = _fake_tool("gmail_send_email")

    async def fake_pure(_uid):
        return [pure]

    async def fake_io(_uid, **_kw):
        return [io_new, io_collide]

    monkeypatch.setattr(rt, "load_active_python_tools", fake_pure)
    monkeypatch.setattr(rio, "load_active_io_tools", fake_io)

    out = await rt.append_learned_tools([builtin], "u1")
    names = [t.name for t in out]
    assert names == ["gmail_send_email", "mon_outil_pure", "appeler_api_meteo"]
    assert out[1] is pure, "en cas de collision de nom, le pure in-process gagne"

    tool_map = {"gmail_send_email": builtin}
    await rt.merge_into_tool_map(tool_map, "u1")
    assert tool_map["appeler_api_meteo"] is io_new
    assert tool_map["mon_outil_pure"] is pure
    assert tool_map["gmail_send_email"] is builtin


# ─────────────────────────────────────────────────────────────────────────
# Registre des noms io bindés (consommé par le canary)
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def io_skill_user(monkeypatch):
    from app.database import async_session, init_db
    from app.models.learned_skill import (
        LearnedSkill,
        SkillContentFormat,
        SkillStatus,
        SkillToolProfile,
    )
    from app.models.user import User

    await init_db()
    uid = f"test_v115_{uuid.uuid4().hex[:8]}"
    skill_id = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    async with async_session() as db:
        db.add(LearnedSkill(
            id=skill_id, user_id=uid, name="appeler_api_meteo",
            description="t", content="def appeler_api_meteo(): ...",
            content_format=SkillContentFormat.PYTHON_TOOL,
            tool_profile=SkillToolProfile.IO,
            status=SkillStatus.ACTIVE,
        ))
        await db.commit()
    yield uid, skill_id
    from sqlalchemy import delete

    from app.models.io_tool_dispatch import IoToolDispatch
    async with async_session() as db:
        await db.execute(delete(IoToolDispatch).where(IoToolDispatch.user_id == uid))
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.mark.asyncio
async def test_loader_updates_bound_names_registry(monkeypatch, io_skill_user) -> None:
    from app.services.learning import learned_tools_runtime_io as rio

    uid, skill_id = io_skill_user
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", "true")
    monkeypatch.setattr(
        rio, "build_io_structured_tool",
        lambda **_kw: _fake_tool("appeler_api_meteo"),
    )

    tools = await rio.load_active_io_tools(uid)

    assert [t.name for t in tools] == ["appeler_api_meteo"]
    assert rio.is_bound_io_tool(uid, "appeler_api_meteo")
    assert not rio.is_bound_io_tool(uid, "gmail_send_email")

    # Flag repassé off : le loader retourne [] et le canary se désarme.
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_IO_ENABLED")
    assert await rio.load_active_io_tools(uid) == []
    assert await rio.io_canary_requires_hitl(uid, "appeler_api_meteo") is False


# ─────────────────────────────────────────────────────────────────────────
# Canary HITL
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_canary_requires_hitl_until_threshold(monkeypatch, io_skill_user) -> None:
    """Les N premières invocations → HITL ; au-delà, l'outil est de
    confiance. Compteur = lignes d'audit io_tool_dispatches (J6.c.1)."""
    from app.database import async_session
    from app.models.io_tool_dispatch import IoToolDispatch
    from app.services.learning import learned_tools_runtime_io as rio

    uid, skill_id = io_skill_user
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", "true")
    monkeypatch.setenv("LEARNED_IO_TOOLS_CANARY_CALLS", "2")
    monkeypatch.setitem(rio._BOUND_IO_NAMES, uid, {"appeler_api_meteo"})

    # 0 appel passé → canary
    assert await rio.io_canary_requires_hitl(uid, "appeler_api_meteo") is True
    # Un builtin homonyme d'aucun outil io → jamais canary
    assert await rio.io_canary_requires_hitl(uid, "gmail_send_email") is False

    # 2 appels audités → seuil atteint, confiance
    async with async_session() as db:
        for _ in range(2):
            db.add(IoToolDispatch(
                user_id=uid, skill_id=skill_id, tool_name="appeler_api_meteo",
                outcome="ok",
            ))
        await db.commit()
    assert await rio.io_canary_requires_hitl(uid, "appeler_api_meteo") is False


@pytest.mark.asyncio
async def test_canary_fails_closed_on_db_error(monkeypatch) -> None:
    """Un outil io dont l'historique est illisible reste sous HITL — un
    outil auto-généré avec egress réel ne tourne jamais sans validation
    par défaut de panne."""
    from app.services.learning import learned_tools_runtime_io as rio

    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", "true")
    monkeypatch.setitem(rio._BOUND_IO_NAMES, "u1", {"outil_io"})

    async def boom(_uid, _name):
        raise RuntimeError("db down")

    monkeypatch.setattr(rio, "_dispatch_count", boom)
    assert await rio.io_canary_requires_hitl("u1", "outil_io") is True


@pytest.mark.asyncio
async def test_canary_disabled_paths(monkeypatch) -> None:
    from app.services.learning import learned_tools_runtime_io as rio

    # Flag io off → jamais de canary
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", raising=False)
    monkeypatch.setitem(rio._BOUND_IO_NAMES, "u1", {"outil_io"})
    assert await rio.io_canary_requires_hitl("u1", "outil_io") is False

    # Flag on mais seuil 0 → canary désactivé explicitement
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", "true")
    monkeypatch.setenv("LEARNED_IO_TOOLS_CANARY_CALLS", "0")
    assert await rio.io_canary_requires_hitl("u1", "outil_io") is False


def test_tool_node_wires_canary_check() -> None:
    """Pin source-level : le HITL de tool_node consulte le canary io."""
    from pathlib import Path

    src = Path("app/agent/tool_node.py").read_text()
    assert "io_canary_requires_hitl" in src
