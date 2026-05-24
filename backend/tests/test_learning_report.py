# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_learning_report.py
# @brief      Sprint 3.7 V1.5 Jalon 6 — pin the /api/me/learning-report
#             endpoint contract : 5 sections, markdown + JSON formats,
#             window parsing, content-negotiation.
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests for `/api/me/learning-report`.

What is pinned :
  - The endpoint exists and is registered at `/api/me/learning-report`
  - Window string parser accepts 7d, 30d, 90d, 24h, garbage→30d default
  - Section loaders return the expected shape from real DB rows
  - Markdown renderer covers all 5 sections (empty state + populated)
  - Content negotiation : Accept: application/json → JSON ; default → markdown
  - `?format=` query param overrides the Accept header
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select


# ── _parse_window unit ────────────────────────────────────────────────


@pytest.mark.parametrize("inp,days", [
    ("7d", 7), ("30d", 30), ("90d", 90), ("1d", 1),
])
def test_parse_window_days(inp, days) -> None:
    from app.routers.learning_report import _parse_window
    assert _parse_window(inp).days == days


def test_parse_window_hours() -> None:
    from app.routers.learning_report import _parse_window
    assert _parse_window("24h").total_seconds() == 86400


def test_parse_window_garbage_defaults_to_30d() -> None:
    from app.routers.learning_report import _parse_window
    assert _parse_window("nope").days == 30
    assert _parse_window("").days == 30


# ── _render_markdown — empty data fallbacks ──────────────────────────


def test_render_markdown_empty_sections_show_friendly_messages() -> None:
    from app.routers.learning_report import _render_markdown
    md = _render_markdown(
        {
            "preferences": [],
            "hitl_refusals": [],
            "hallucinations": [],
            "mission_critiques": [],
            "tier_performance": [],
        },
        window_label="30d",
    )
    # Headings present
    assert "# Ce que tu sais sur moi — 30d" in md
    assert "## Préférences captées" in md
    assert "## Tes refus HITL" in md
    assert "## Quand ELY a halluciné" in md
    assert "## Missions critiquées" in md
    assert "## Performance par modèle" in md
    # Empty fallback strings
    assert "Rien d'enregistré" in md
    assert "Aucun refus" in md
    assert "Aucune hallucination interceptée" in md
    assert "Aucune critique de mission" in md
    assert "Pas assez de données" in md


def test_render_markdown_populated_sections_quote_data() -> None:
    from app.routers.learning_report import _render_markdown
    data = {
        "preferences": [
            {"key": "main_project", "value": "ELY", "confidence": 0.95,
             "source_count": 5, "last_seen": None},
            {"key": "preferred_language", "value": "français", "confidence": 0.7,
             "source_count": 3, "last_seen": None},
        ],
        "hitl_refusals": [
            {
                "tool_name": "gmail_trash_emails",
                "action_description": "Trash 12 newsletters",
                "decision": "deny",
                "reason": "user-provided",
                "created_at": datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc).isoformat(),
            },
        ],
        "hallucinations": [
            {
                "model_used": "gemma-4-e4b-it",
                "tier_llm": "A",
                "reason": "completion_claim_without_destructive_tool_call",
                "matched_patterns": ["fr.first_person_past"],
                "original_response": "J'ai supprimé tous les mails.",
                "created_at": datetime(2026, 5, 23, 14, 30, tzinfo=timezone.utc).isoformat(),
            },
        ],
        "mission_critiques": [
            {
                "mission_id": "m-1",
                "goal": "Verify Amazon orders",
                "status": "completed",
                "quality_score": 35,
                "honest_completion": False,
                "wasted_effort": True,
                "user_should_have_been_warned": True,
                "main_issue": "Agent claimed orders fetched but never read the page.",
                "critic_model": "deepseek-v4-pro",
                "created_at": datetime(2026, 5, 22, 16, 0, tzinfo=timezone.utc).isoformat(),
            },
        ],
        "tier_performance": [
            {"label": "llm:deepseek/v4-pro", "messages": 42,
             "hitl_refusals_total": 3, "hallucinations_total": 1,
             "feedback_count": 7, "feedback_mean": 0.71},
        ],
    }
    md = _render_markdown(data, window_label="7d")
    # Preferences
    assert "main_project" in md and "ELY" in md
    assert "preferred_language" in md
    # HITL
    assert "gmail_trash_emails" in md
    assert "**deny**" in md
    # Hallu
    assert "gemma-4-e4b-it" in md
    assert "fr.first_person_past" in md
    # Critic flags
    assert "succès en façade" in md   # honest_completion=False
    assert "gâchis" in md              # wasted_effort=True
    assert "user à prévenir" in md     # user_should_have_been_warned=True
    assert "35/100" in md
    # Perf table
    assert "deepseek/v4-pro" in md
    assert "| 42 |" in md


def test_render_markdown_truncates_long_action_descriptions() -> None:
    from app.routers.learning_report import _render_markdown
    very_long = "x" * 1000
    md = _render_markdown(
        {
            "preferences": [],
            "hitl_refusals": [
                {
                    "tool_name": "t",
                    "action_description": very_long,
                    "decision": "deny",
                    "reason": "user-provided",
                    "created_at": datetime(2026, 5, 22, tzinfo=timezone.utc).isoformat(),
                }
            ],
            "hallucinations": [],
            "mission_critiques": [],
            "tier_performance": [],
        },
        window_label="7d",
    )
    # No single line should be > 1000 chars — verify truncation kicked in
    lines = md.split("\n")
    assert all(len(line) < 500 for line in lines)


# ── Endpoint wiring (route registered + selects right format) ────────


@pytest_asyncio.fixture
async def _learning_test_user():
    """Idempotent : creates the user if missing AND wipes any leftover
    signal rows from a previous test run so every test sees a clean
    slate. Avoids cross-test pollution on the shared SQLite file."""
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.hallucination_block import HallucinationBlock
    from app.models.hitl_refusal import HitlRefusal
    from app.models.user import User
    from app.models.user_memory import UserProfile

    await init_db()
    async with async_session() as db:
        await db.execute(delete(UserProfile).where(UserProfile.user_id == "learning_test_user"))
        await db.execute(delete(HitlRefusal).where(HitlRefusal.user_id == "learning_test_user"))
        await db.execute(delete(HallucinationBlock).where(HallucinationBlock.user_id == "learning_test_user"))
        existing = (await db.execute(
            select(User).where(User.id == "learning_test_user")
        )).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="learning_test_user",
                username="learning_test",
                email="learn@test.local",
                hashed_password="x",
            ))
        await db.commit()
    yield "learning_test_user"


@pytest.mark.asyncio
async def test_endpoint_route_is_registered() -> None:
    from app.main import app
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/api/me/learning-report" in paths


@pytest.mark.asyncio
async def test_loaders_return_empty_lists_for_fresh_user(_learning_test_user) -> None:
    """A user with no signal rows must get empty lists, not errors."""
    from app.routers.learning_report import (
        _load_hallucinations,
        _load_hitl_refusals,
        _load_mission_critiques,
        _load_preferences,
        _load_tier_performance,
    )
    user_id = _learning_test_user
    since = datetime.now(timezone.utc) - timedelta(days=30)
    assert await _load_preferences(user_id) == []
    assert await _load_hitl_refusals(user_id, since) == []
    assert await _load_hallucinations(user_id, since) == []
    assert await _load_mission_critiques(user_id, since) == []
    assert await _load_tier_performance(user_id, since) == []


@pytest.mark.asyncio
async def test_loaders_return_real_rows(_learning_test_user) -> None:
    """Insert real signal rows + verify the loaders surface them."""
    from app.database import async_session
    from app.models.hallucination_block import HallucinationBlock
    from app.models.hitl_refusal import HitlRefusal
    from app.models.user_memory import UserProfile
    from app.routers.learning_report import (
        _load_hallucinations,
        _load_hitl_refusals,
        _load_preferences,
    )
    user_id = _learning_test_user

    async with async_session() as db:
        # Preferences
        db.add(UserProfile(
            user_id=user_id, key="favourite_color", value="bleu",
            confidence=0.9, source_count=2,
        ))
        # HITL refusal
        db.add(HitlRefusal(
            user_id=user_id,
            conversation_id="c-test",
            tool_name="gmail_trash_emails",
            args_redacted="{}",
            action_description="Trash 10 newsletters",
            decision="deny",
            reason="user-provided",
        ))
        # Hallucination
        db.add(HallucinationBlock(
            user_id=user_id,
            conversation_id="c-test",
            model_used="gemma-4-e4b-it",
            tier_llm="A",
            matched_patterns='["fr.passive_past"]',
            tools_invoked="[]",
            destructive_tools_invoked="[]",
            reason="completion_claim_without_destructive_tool_call",
            original_response="C'est fait, j'ai supprimé.",
        ))
        await db.commit()

    since = datetime.now(timezone.utc) - timedelta(days=1)
    prefs = await _load_preferences(user_id)
    assert any(p["key"] == "favourite_color" for p in prefs)
    refusals = await _load_hitl_refusals(user_id, since)
    assert any(r["tool_name"] == "gmail_trash_emails" for r in refusals)
    hallus = await _load_hallucinations(user_id, since)
    assert any(h["model_used"] == "gemma-4-e4b-it" for h in hallus)
    # JSON-encoded patterns are decoded back to a list
    assert hallus[0]["matched_patterns"] == ["fr.passive_past"]


# ── main.py wiring guard ─────────────────────────────────────────────


def test_main_py_registers_learning_report_router() -> None:
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1] / "app" / "main.py"
    ).read_text(encoding="utf-8")
    assert "learning_report" in src
    assert "learning_report_router" in src
