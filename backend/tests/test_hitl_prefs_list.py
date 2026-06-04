# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_hitl_prefs_list.py
# @brief      2026-06-04 — /hitl/preferences must list EVERY HITL-gated tool
#             (union of ALWAYS_CRITICAL_TOOLS and LOCKED_HITL_TOOLS), not just
#             ALWAYS_CRITICAL_TOOLS — else LOCKED-only tools (gmail_move_emails)
#             never appear on the settings page.
# @license    Elastic License 2.0
# =============================================================================
from __future__ import annotations

import pytest

from app.database import init_db
from app.routers.hitl_prefs import list_preferences
from app.services.hitl_preferences import LOCKED_HITL_TOOLS
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS


class _FakeUser:
    id = "hitl-prefs-test-user"


@pytest.mark.asyncio
async def test_list_includes_locked_only_tools():
    await init_db()
    rows = await list_preferences(current_user=_FakeUser(), accept_language="fr")
    names = {r.tool_name for r in rows}

    # The whole union must be present — every HITL-gated tool is manageable.
    assert names == (ALWAYS_CRITICAL_TOOLS | LOCKED_HITL_TOOLS)

    # gmail_move_emails is LOCKED but NOT always-critical → it was the missing
    # one Franck reported. It must now appear, and be locked.
    assert "gmail_move_emails" in names
    by_name = {r.tool_name: r for r in rows}
    assert by_name["gmail_move_emails"].locked is True
    assert by_name["gmail_move_emails"].requires_confirmation is True
    # gmail_batch_modify (also LOCKED-only) likewise present.
    assert "gmail_batch_modify" in names


@pytest.mark.asyncio
async def test_non_locked_critical_tool_is_toggleable():
    await init_db()
    rows = await list_preferences(current_user=_FakeUser(), accept_language="fr")
    by_name = {r.tool_name: r for r in rows}
    # gmail_send_email is ALWAYS_CRITICAL but NOT locked → user can disable HITL.
    assert by_name["gmail_send_email"].locked is False


@pytest.mark.asyncio
async def test_newly_surfaced_tool_has_description():
    await init_db()
    rows = await list_preferences(current_user=_FakeUser(), accept_language="fr")
    by_name = {r.tool_name: r for r in rows}
    # save_constraint is LOCKED-only and got a description in this fix.
    assert by_name["save_constraint"].description


# ── frontend wiring (source-grep, mirrors test_hitl_allow_always) ─────────────


def test_settings_page_renders_all_categories_as_accordions():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "components" / "settings" / "HitlPreferencesSection.tsx"
    ).read_text(encoding="utf-8")
    # Renders every present category (not just the hardcoded groupOrder)…
    assert "orderedGroups" in src
    # …as collapsible accordions.
    assert "setOpenCats" in src
    # labels for the previously-dropped categories exist
    for token in ('os:', 'whatsapp:', 'mcp:', 'save:'):
        assert token in src, f"missing group label {token}"
