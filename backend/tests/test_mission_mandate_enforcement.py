# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_mandate_enforcement.py
# @brief      Missions autonomes J2 — enforcement du mandat : mapping
#             outil→famille, chargement du mandat actif, gate dans dispatch_tool.
# @license    Elastic License 2.0
# =============================================================================
"""Missions autonomes J2 — pins de l'enforcement.

Cadrage : docs_internes/cadrage_missions_autonomes.md (§3.2, D1/D2).
Le mandat DÉPLACE le HITL de l'action vers le grant : sous mandat actif,
famille autorisée ⇒ pas de HITL ; noyau interdit ⇒ refus sec ; hors
mandat ⇒ escalade au HITL humain. J2 = escalate ; decide = J5.
"""
from __future__ import annotations

import uuid

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Mapping outil → famille
# ─────────────────────────────────────────────────────────────────────────


def test_tool_family_known_prefixes() -> None:
    from app.services.mission_tool_families import tool_family

    assert tool_family("gmail_send_email") == "email"
    assert tool_family("gmail_list_emails") == "email"
    assert tool_family("drive_create_file") == "drive"
    assert tool_family("calendar_create_event") == "calendar"
    assert tool_family("browser_navigate") == "web"
    assert tool_family("web_search") == "web"
    assert tool_family("desktop_read_file") == "files"
    assert tool_family("scheduler_create_task") == "scheduler"
    assert tool_family("tasks_create") == "tasks"
    assert tool_family("contacts_search") == "contacts"
    assert tool_family("github_repo_stats") == "github"
    assert tool_family("notes_create") == "notes"
    assert tool_family("vision_analyze_image") == "vision"


def test_tool_family_forbidden_prefixes() -> None:
    from app.services.mission_spec import MANDATE_FORBIDDEN_FAMILIES
    from app.services.mission_tool_families import tool_family

    assert tool_family("ssh_execute") == "ssh"
    assert tool_family("vault_unlock") == "vault"
    assert tool_family("mcp_call_tool") == "mcp"
    assert tool_family("os_click") == "system"
    # tous bien dans le noyau interdit du contrat J1
    for t in ("ssh_execute", "vault_unlock", "mcp_call_tool", "os_click"):
        assert tool_family(t) in MANDATE_FORBIDDEN_FAMILIES


def test_tool_family_unknown_is_none() -> None:
    from app.services.mission_tool_families import tool_family

    # Un outil non mappé ⇒ None ⇒ le gate escalade (fail-closed).
    assert tool_family("some_brand_new_tool") is None
    assert tool_family("orchestrate") is None   # méta/univ — non rattaché à une famille


def test_escalate_always_set_covers_escape_hatches() -> None:
    from app.services.mission_tool_families import MANDATE_ESCALATE_ALWAYS

    # Sans annulation possible : toujours escalader, même famille autorisée.
    assert "gmail_empty_trash" in MANDATE_ESCALATE_ALWAYS
    assert "gmail_raw_api_call" in MANDATE_ESCALATE_ALWAYS
    assert "drive_raw_api_call" in MANDATE_ESCALATE_ALWAYS


# ─────────────────────────────────────────────────────────────────────────
# Reconstruction du mandat + chargement de l'actif
# ─────────────────────────────────────────────────────────────────────────


def test_mandate_json_roundtrip() -> None:
    from app.services.mission_spec import (
        mandate_from_json,
        mandate_to_json,
        parse_mission_spec,
    )

    spec = parse_mission_spec(
        "version: 2\nmandate:\n  tools_allow: [youtube, drive]\n"
        "  on_unforeseen: decide\n  llm_tier: medium\n"
        "steps:\n  - id: s1\n    do: x"
    )
    restored = mandate_from_json(mandate_to_json(spec.mandate))
    assert restored == spec.mandate  # frozen dataclass ⇒ égalité structurelle


@pytest.mark.asyncio
async def test_load_active_mandate_gated_by_flag_and_state(monkeypatch) -> None:
    from sqlalchemy import delete

    from app.config import get_settings
    from app.database import async_session, init_db
    from app.models.mission import Mission
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j2_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
    try:
        m = await mission_service.create_mission(
            user_id=uid, title="YT", goal="gérer",
            spec_yaml="version: 2\nmandate:\n  tools_allow: [youtube]\n"
                      "steps:\n  - id: s1\n    do: x",
        )
        # pending_validation (défaut J1) ⇒ pas encore actif
        assert await mission_service.load_active_mandate(m.id) is None

        # activé ⇒ le mandat est chargé
        await mission_service.set_autonomy_state(m.id, "active")
        mandate = await mission_service.load_active_mandate(m.id)
        assert mandate is not None and mandate.tools_allow == ("youtube",)

        # flag OFF ⇒ inerte même si actif (fail-closed)
        monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", False)
        assert await mission_service.load_active_mandate(m.id) is None
    finally:
        async with async_session() as db:
            await db.execute(delete(Mission).where(Mission.user_id == uid))
            u = await db.get(User, uid)
            if u is not None:
                await db.delete(u)
            await db.commit()
