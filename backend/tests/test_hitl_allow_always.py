# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_hitl_allow_always.py
# @brief      2026-05-23 — pin the "Toujours autoriser" HITL feature : the
#             set_user_preference upsert, the nodes.py handler for the new
#             `allow_always` decision, the validation REST route, and the
#             4-button frontend layout in the avatar panel.
# @license    MIT
# =============================================================================
"""Tests for the symmetric "Toujours autoriser" feature.

Context (Franck, 2026-05-23) : recurring missions (e.g. inbox cleanup
3×/day × 5 categories) forced 15 HITL clicks/day for the same tools the
user had explicitly scheduled. Without an "always allow" pendant to
"always ban", the only way to skip HITL was to manually edit the
hitl_preferences row server-side. Now a single click locks in the
preference.

What the tests pin :
  1. `set_user_preference()` upserts cleanly + survives missing user_id
  2. nodes.py wires both `user_requires_hitl` check + `allow_always`
     handler that saves the preference (source-grep guards)
  3. The new REST route `/validation/{id}/allow_always` exists
  4. AvatarPanel + HitlBell render 4 buttons in a 2×2 grid
  5. The legacy `gridTemplateColumns: "repeat(3, 1fr)"` is gone from
     AvatarPanel (was the cause of the "Toujours interdire" overflow)
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select


_REPO = Path(__file__).resolve().parents[1]
_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


# ── set_user_preference upsert behaviour ─────────────────────────────


@pytest_asyncio.fixture
async def _seeded_user_for_pref():
    """A real users row so the FK constraint on hitl_preferences passes."""
    from app.database import async_session, init_db
    from app.models.user import User
    await init_db()
    async with async_session() as db:
        existing = (
            await db.execute(select(User).where(User.id == "pref_test_u"))
        ).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="pref_test_u",
                username="pref_test_user",
                email="pref_test_u@test.local",
                hashed_password="x",
            ))
            await db.commit()
    yield "pref_test_u"


@pytest.mark.asyncio
async def test_set_user_preference_creates_new_row(_seeded_user_for_pref) -> None:
    from app.database import async_session
    from app.models.hitl_preference import HitlPreference
    from app.services.hitl_preferences import set_user_preference

    ok = await set_user_preference(
        "pref_test_u", "gmail_send_email", requires_confirmation=False,
    )
    assert ok is True

    async with async_session() as db:
        row = (await db.execute(
            select(HitlPreference).where(
                HitlPreference.user_id == "pref_test_u",
                HitlPreference.tool_name == "gmail_send_email",
            )
        )).scalar_one()
        assert row.requires_confirmation is False


@pytest.mark.asyncio
async def test_set_user_preference_updates_existing_row(_seeded_user_for_pref) -> None:
    from app.database import async_session
    from app.models.hitl_preference import HitlPreference
    from app.services.hitl_preferences import set_user_preference

    # Two writes — second one flips back to True
    await set_user_preference(
        "pref_test_u", "drive_share_file", requires_confirmation=False,
    )
    await set_user_preference(
        "pref_test_u", "drive_share_file", requires_confirmation=True,
    )

    async with async_session() as db:
        rows = (await db.execute(
            select(HitlPreference).where(
                HitlPreference.user_id == "pref_test_u",
                HitlPreference.tool_name == "drive_share_file",
            )
        )).scalars().all()
        # No duplicate row — upsert kept the single one
        assert len(rows) == 1
        assert rows[0].requires_confirmation is True


@pytest.mark.asyncio
async def test_set_user_preference_returns_false_on_empty_args() -> None:
    from app.services.hitl_preferences import set_user_preference

    assert await set_user_preference("", "tool", requires_confirmation=False) is False
    assert await set_user_preference("u", "", requires_confirmation=False) is False


@pytest.mark.asyncio
async def test_user_requires_hitl_honours_skip_preference(_seeded_user_for_pref) -> None:
    """After a `set_user_preference(..., False)` for a non-locked tool,
    `user_requires_hitl` must return False. That's the read side that
    nodes.py uses to short-circuit the HITL prompt."""
    from app.services.hitl_preferences import (
        set_user_preference,
        user_requires_hitl,
    )

    await set_user_preference(
        "pref_test_u", "drive_list_files", requires_confirmation=False,
    )
    assert await user_requires_hitl("pref_test_u", "drive_list_files") is False


@pytest.mark.asyncio
async def test_dangerous_tools_honor_skip_preference() -> None:
    """Depuis 2026-06-19 (demande Franck) : les outils dangereux (ex-verrouillés)
    sont ON par défaut MAIS désactivables — la préférence est honorée. Avant, un
    outil verrouillé renvoyait True en dur (« Autoriser définitivement »
    inopérant pour le nettoyage de mails planifié).

    Note : user UNIQUE par run. Avant, ce test partageait ``pref_test_u`` et
    posait une préférence persistante en base ; comme ``next(iter(frozenset))``
    dépend du hash seed du process, un run suivant pouvait re-piocher le même
    outil et casser l'assertion « défaut = True » (test flaky ~1/3). Un user
    vierge garantit la précondition « aucune préférence ».

    ⚠️ 02/09/2026 — l'outil n'est plus tiré au hasard. Depuis l'audit sécurité,
    les passe-plats ``*_raw_api_call`` de ``LOCKED_HITL_TOOLS`` ne sont PLUS
    dispensables (``hitl_preferences.is_hitl_waivable``), et
    ``next(iter(frozenset))`` en piochait un environ un run sur trois — le test
    redevenait flaky, pour une raison différente. On nomme donc un outil
    dangereux ORDINAIRE ; la règle générale du 19/06 reste bien celle testée,
    et l'exception a son propre fichier
    (``test_raw_api_call_hors_preferences.py``)."""
    import uuid

    from app.database import async_session, init_db
    from app.models.user import User
    from app.services.hitl_preferences import (
        LOCKED_HITL_TOOLS,
        is_hitl_waivable,
        set_user_preference,
        user_requires_hitl,
    )

    await init_db()
    uid = f"pref_dang_{uuid.uuid4().hex}"
    async with async_session() as db:
        db.add(User(id=uid, username=uid, email=f"{uid}@test.local", hashed_password="x"))
        await db.commit()

    dangerous = "gmail_trash_emails"
    assert dangerous in LOCKED_HITL_TOOLS
    assert is_hitl_waivable(dangerous)
    # défaut sûr : aucune préférence → confirmation requise
    assert await user_requires_hitl(uid, dangerous) is True
    # l'utilisateur désactive explicitement → désormais honoré (= le fix)
    await set_user_preference(uid, dangerous, requires_confirmation=False)
    assert await user_requires_hitl(uid, dangerous) is False


# ── nodes.py source-grep guards ──────────────────────────────────────


def test_nodes_py_imports_user_requires_hitl_check() -> None:
    """tool_node must short-circuit HITL when the user has marked the
    tool as always-allowed. Mirror of sub_agents/factory.py:806.

    After the 2026-05-25 refactor (Phase 3), the HITL handler lives in
    app/agent/tool_node.py rather than nodes.py, and since C3a in
    app/services/tool_gateway.py (the single tool-execution gateway).
    """
    src = (_REPO / "app" / "services" / "tool_gateway.py").read_text(encoding="utf-8")
    assert "user_requires_hitl" in src, (
        "tool_node.py must check user_requires_hitl before triggering the "
        "HITL prompt — otherwise the user's 'always allow' preference "
        "set via the new button has no effect in the main agent path."
    )


def test_nodes_py_handles_allow_always_decision() -> None:
    """When the HITL prompt returns `allow_always`, tool_node must save
    the preference (so the next call skips HITL) and fall through to
    execute the tool this time.

    After the 2026-05-25 refactor (Phase 3), the HITL handler lives in
    app/agent/tool_node.py rather than nodes.py, and since C3a in
    app/services/tool_gateway.py (the single tool-execution gateway).
    """
    src = (_REPO / "app" / "services" / "tool_gateway.py").read_text(encoding="utf-8")
    assert 'decision == "allow_always"' in src
    assert "set_user_preference" in src
    # Order : the allow_always branch comes BEFORE the catch-all "not allow"
    aa_idx = src.index('decision == "allow_always"')
    catchall_idx = src.index('decision != "allow"')
    assert aa_idx < catchall_idx, (
        "The `allow_always` branch must come BEFORE `decision != 'allow'`, "
        "otherwise it gets swallowed by the refusal path."
    )


# ── REST route exists ────────────────────────────────────────────────


def test_validation_router_exposes_allow_always_route() -> None:
    src = (_REPO / "app" / "routers" / "validation.py").read_text(encoding="utf-8")
    assert '/{action_id}/allow_always' in src
    assert "allow_always_action" in src or "allow_always" in src


# ── Frontend source-grep guards ──────────────────────────────────────


def test_avatar_panel_uses_2x2_grid_for_hitl_buttons() -> None:
    """The bug we just fixed : `repeat(3, 1fr)` forced 3 columns and the
    "Toujours interdire" button overflowed the danger card on narrow
    panels. The new layout uses a 2×2 grid."""
    src = (
        _FRONTEND / "src" / "components" / "avatar" / "AvatarPanel.tsx"
    ).read_text(encoding="utf-8")
    # The old layout must be gone
    assert 'gridTemplateColumns: "repeat(3, 1fr)"' not in src
    # The new layout must be present
    assert 'gridTemplateColumns: "1fr 1fr"' in src


def test_avatar_panel_has_allow_always_button() -> None:
    src = (
        _FRONTEND / "src" / "components" / "avatar" / "AvatarPanel.tsx"
    ).read_text(encoding="utf-8")
    assert 'resolveHitl("allow_always")' in src
    assert "hitlAllowAlways" in src


def test_hitl_bell_has_allow_always_button() -> None:
    src = (
        _FRONTEND / "src" / "components" / "layout" / "HitlBell.tsx"
    ).read_text(encoding="utf-8")
    assert '"allow_always"' in src
    assert "Toujours autoriser" in src


def test_i18n_messages_have_allow_always_key() -> None:
    fr = (_FRONTEND / "messages" / "fr.json").read_text(encoding="utf-8")
    en = (_FRONTEND / "messages" / "en.json").read_text(encoding="utf-8")
    assert "hitlAllowAlways" in fr
    assert "hitlAllowAlways" in en
    assert "Toujours autoriser" in fr
    assert "Always allow" in en


def test_api_client_accepts_allow_always_in_decision_type() -> None:
    src = (_FRONTEND / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert '"allow_always"' in src, (
        "The hitlResolve helper's decision union must accept the new "
        "`allow_always` value, otherwise the AvatarPanel call won't typecheck."
    )
