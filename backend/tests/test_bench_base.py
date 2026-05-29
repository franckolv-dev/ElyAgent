# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_bench_base.py
# @brief      Sprint 3.7.3 J1 — unit tests for bench/scenarios/_base.py
# @license    Elastic License 2.0
# =============================================================================
"""Pin the contract of the bench scenario helper module.

These are pure-function tests (anonymisation, tag normalisation, check
conversion) plus one async integration test for the throwaway_user
context manager.

Important: the unit tests run inside pytest, the bench harness runs
standalone. The two suites share the helper module so we ping its
behaviour from both sides to catch breakage early.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Make `bench.scenarios._base` importable from pytest (which lives under
# backend/) without polluting sys.path globally.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────
# normalise_tags + tags_intersect
# ─────────────────────────────────────────────────────────────────────────


def test_normalise_tags_default_when_missing() -> None:
    from bench.scenarios._base import DEFAULT_TAGS, normalise_tags
    assert normalise_tags(None)   == list(DEFAULT_TAGS)
    assert normalise_tags([])     == list(DEFAULT_TAGS)
    assert normalise_tags("")     == list(DEFAULT_TAGS)


def test_normalise_tags_accepts_string_form() -> None:
    """A scenario author may write ``TAGS = "shallow"`` instead of a list."""
    from bench.scenarios._base import normalise_tags
    assert normalise_tags("shallow") == ["shallow"]
    assert normalise_tags("MEDIUM")  == ["medium"]  # case-insensitive


def test_normalise_tags_drops_unknown_values() -> None:
    """Unknown tags are forward-compatible: silently dropped, no raise."""
    from bench.scenarios._base import normalise_tags
    assert normalise_tags(["shallow", "exotic", "deep"]) == ["shallow", "deep"]


def test_normalise_tags_deduplicates() -> None:
    from bench.scenarios._base import normalise_tags
    assert normalise_tags(["shallow", "shallow", "deep"]) == ["shallow", "deep"]


def test_normalise_tags_all_unknown_falls_back_to_default() -> None:
    """All-junk input should not yield an empty list — the harness needs
    SOMETHING to filter on. We fall back to the documented default."""
    from bench.scenarios._base import DEFAULT_TAGS, normalise_tags
    assert normalise_tags(["nope", "zzz"]) == list(DEFAULT_TAGS)


def test_tags_intersect_matches_on_any_overlap() -> None:
    from bench.scenarios._base import tags_intersect
    assert tags_intersect(["shallow"], ["shallow", "medium"]) is True
    assert tags_intersect(["deep"],    ["shallow", "medium"]) is False
    assert tags_intersect([],          ["shallow"])           is False


# ─────────────────────────────────────────────────────────────────────────
# anonymise_text
# ─────────────────────────────────────────────────────────────────────────


def test_anonymise_text_handles_none_and_empty() -> None:
    from bench.scenarios._base import anonymise_text
    assert anonymise_text(None) == ""
    assert anonymise_text("")   == ""


def test_anonymise_text_scrubs_email() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text("Envoyer à franck.ollivier@example.com SVP")
    assert "franck.ollivier" not in out
    assert "<email>" in out


def test_anonymise_text_scrubs_phone() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text("Appelez moi au +33 6 12 34 56 78")
    assert "12 34 56 78" not in out
    assert "<phone>" in out


def test_anonymise_text_scrubs_iban() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text("Mon IBAN FR7630006000011234567890189 svp")
    assert "FR7630006000011234567890189" not in out
    assert "<iban>" in out


def test_anonymise_text_scrubs_url_and_gmaps() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text(
        "RDV https://google.fr/maps/place/Tour+Eiffel/@48.8584 demain"
    )
    # Either <maps> (more specific) or <url> (fallback) is acceptable.
    assert "google.fr" not in out
    assert any(token in out for token in ("<maps>", "<url>"))


def test_anonymise_text_preserves_innocuous_text() -> None:
    """Pure prose with no PII shouldn't be altered."""
    from bench.scenarios._base import anonymise_text
    text = "L'utilisateur a refusé la suppression des mails marketing."
    assert anonymise_text(text) == text


# ─────────────────────────────────────────────────────────────────────────
# from_checks
# ─────────────────────────────────────────────────────────────────────────


def test_from_checks_all_pass_marks_pass_true() -> None:
    from bench.scenarios._base import from_checks
    out = from_checks({"a": True, "b": True})
    assert out["pass"] is True
    assert out["checks"] == {"a": True, "b": True}
    assert "failed_checks" not in out  # only present on failure


def test_from_checks_any_fail_lists_failed_keys() -> None:
    from bench.scenarios._base import from_checks
    out = from_checks({"a": True, "b": False, "c": False})
    assert out["pass"] is False
    assert out["failed_checks"] == ["b", "c"]


def test_from_checks_passes_extra_through() -> None:
    """Caller's metadata must reach the result dict untouched."""
    from bench.scenarios._base import from_checks
    out = from_checks({"a": True}, signal_id=42, reason="check")
    assert out["signal_id"] == 42
    assert out["reason"]    == "check"


# ─────────────────────────────────────────────────────────────────────────
# throwaway_user (real DB integration)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_throwaway_user_creates_and_cleans_up() -> None:
    """Smoke the context manager: user exists during the block, gone after."""
    from sqlalchemy import select
    from app.database import async_session
    from app.models.user import User
    from bench.scenarios._base import throwaway_user

    async with throwaway_user(prefix="bench_unittest") as uid:
        assert uid.startswith("bench_unittest_")
        async with async_session() as db:
            u = (await db.execute(
                select(User).where(User.id == uid)
            )).scalar_one_or_none()
            assert u is not None, "user should exist inside the block"

    # After exit, the row must be gone.
    async with async_session() as db:
        u = (await db.execute(
            select(User).where(User.id == uid)
        )).scalar_one_or_none()
        assert u is None, "user should be wiped on context exit"


@pytest.mark.asyncio
async def test_throwaway_user_cleans_user_scoped_artefacts() -> None:
    """If the scenario writes user-scoped rows, the cleanup must wipe them
    so re-runs stay idempotent."""
    from sqlalchemy import select
    from app.database import async_session
    from app.models.hitl_refusal import HitlRefusal
    from app.services.learning import record_hitl_refusal
    from bench.scenarios._base import throwaway_user

    async with throwaway_user(prefix="bench_scope") as uid:
        await record_hitl_refusal(
            user_id=uid,
            conversation_id="conv-cleanup",
            tool_name="dummy",
            args={},
            action_description="x",
            decision="deny",
            reason="test",
        )
        async with async_session() as db:
            rows = (await db.execute(
                select(HitlRefusal).where(HitlRefusal.user_id == uid)
            )).scalars().all()
            assert len(rows) == 1

    # After exit, the row must be gone too.
    async with async_session() as db:
        rows = (await db.execute(
            select(HitlRefusal).where(HitlRefusal.user_id == uid)
        )).scalars().all()
        assert rows == []
