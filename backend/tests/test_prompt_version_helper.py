# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_prompt_version_helper.py
# @brief      Sprint 3.7 Jalon 3 — pin the prompt_version hash helper and
#             its wiring into mission_steps, feedback, and error_log writes.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""prompt_version contract — Sprint 3.7 Jalon 3.

What is pinned :
  - `prompt_hash` is deterministic and returns 8 hex chars
  - LRU cache reuses the same hash for the same input
  - Distinct inputs yield distinct hashes
  - `current_system_prompt_version()` reads the live _SYSTEM_PROMPT_BASE
  - mission_service.add_step writes `prompt_version` on the new step
  - feedback POST handler writes `prompt_version` on the new row
  - ErrorStore.store accepts an explicit `prompt_version` kwarg and
    falls back to current_system_prompt_version when omitted

The actual signal writers (Jalon 2) will reuse the same helper — these
tests guard the foundation so Jalon 2 lands on stable ground.
"""
from __future__ import annotations

import re

import pytest

from app.services.learning import current_system_prompt_version, prompt_hash
from app.services.learning import prompt_version as pv_module


@pytest.fixture(autouse=True)
def _reset_prompt_hash_cache():
    pv_module._clear_cache_for_tests()
    yield
    pv_module._clear_cache_for_tests()


# ── prompt_hash basics ────────────────────────────────────────────────


def test_prompt_hash_returns_8_hex_chars() -> None:
    h = prompt_hash("hello world")
    assert re.fullmatch(r"[0-9a-f]{8}", h), f"got {h!r}"


def test_prompt_hash_is_deterministic_across_calls() -> None:
    assert prompt_hash("same text") == prompt_hash("same text")


def test_prompt_hash_distinguishes_different_texts() -> None:
    assert prompt_hash("alpha") != prompt_hash("beta")


def test_prompt_hash_known_sha256_prefix() -> None:
    # `sha256("hello")` = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert prompt_hash("hello") == "2cf24dba"


def test_prompt_hash_handles_unicode() -> None:
    """French accents in our prompts must not crash hashing."""
    h1 = prompt_hash("Tu es Éli")
    h2 = prompt_hash("Tu es Ely")
    assert h1 != h2
    assert len(h1) == 8 and len(h2) == 8


def test_prompt_hash_cache_keeps_result_stable() -> None:
    """Same input across repeated calls hits the LRU cache and returns
    the same hash. Pinned because A/B testing depends on consistent hashes."""
    h_first = prompt_hash("fixed input")
    h_again = prompt_hash("fixed input")
    h_third = prompt_hash("fixed input")
    assert h_first == h_again == h_third


# ── current_system_prompt_version ─────────────────────────────────────


def test_current_system_prompt_version_returns_8_hex_chars() -> None:
    v = current_system_prompt_version()
    assert re.fullmatch(r"[0-9a-f]{8}", v), f"got {v!r}"


def test_current_system_prompt_version_matches_prompt_hash_of_base() -> None:
    """The convenience function must hash exactly the same constant the
    rest of the codebase uses as system prompt. If anyone splits or
    reorganizes _SYSTEM_PROMPT_BASE without updating this helper, the
    rate of mismatch between persisted prompt_versions and the active
    prompt grows silently — caught here."""
    from app.agent.nodes import _SYSTEM_PROMPT_BASE
    assert current_system_prompt_version() == prompt_hash(_SYSTEM_PROMPT_BASE)


# ── ErrorStore.store accepts prompt_version (Jalon 2 prep) ──────────


@pytest.mark.asyncio
async def test_error_store_uses_explicit_prompt_version(monkeypatch) -> None:
    """When the caller passes `prompt_version=...`, the row stores it
    verbatim — A/B testing later will pass the variant-specific hash."""
    from app.services.memory.error_store import ErrorStore

    captured_rows = []

    class _FakeSession:
        def add(self, row):
            captured_rows.append(row)

        async def flush(self):
            # Fake the auto-id assignment so .store() returns it
            for r in captured_rows:
                if r.id is None:
                    r.id = 1

    store = ErrorStore()
    result = await store.store(
        _FakeSession(),
        user_id="u1",
        tool_name="some_tool",
        args_redacted={"x": 1},
        error_type="ValueError",
        error_msg="boom",
        prompt_version="abcdef12",
    )
    assert result is not None
    assert len(captured_rows) == 1
    assert captured_rows[0].prompt_version == "abcdef12"


@pytest.mark.asyncio
async def test_error_store_falls_back_to_current_system_prompt_version() -> None:
    """No `prompt_version=` kwarg → store grabs the live system prompt
    hash automatically. Convenient default, pinned so it never silently
    inserts NULL."""
    from app.services.memory.error_store import ErrorStore

    captured_rows = []

    class _FakeSession:
        def add(self, row):
            captured_rows.append(row)

        async def flush(self):
            for r in captured_rows:
                if r.id is None:
                    r.id = 1

    store = ErrorStore()
    await store.store(
        _FakeSession(),
        user_id="u1",
        tool_name="some_tool",
        args_redacted={"x": 1},
        error_type="ValueError",
        error_msg="boom",
    )

    expected = current_system_prompt_version()
    assert captured_rows[0].prompt_version == expected


# ── Feedback router writes prompt_version (Jalon 3 wiring) ──────────


def test_feedback_router_imports_current_system_prompt_version() -> None:
    """Pin the wiring : the router's source must contain the import and
    pass `prompt_version=` to the model. Hermetic guard against a future
    refactor that drops the column accidentally."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "routers" / "feedback.py"
    ).read_text(encoding="utf-8")
    assert "current_system_prompt_version" in src
    assert "prompt_version=prompt_version" in src


# ── mission_service.add_step writes prompt_version (Jalon 3 wiring) ─


def test_mission_service_passes_prompt_version_to_step() -> None:
    """Same hermetic guard for the mission step writer."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "services" / "mission_service.py"
    ).read_text(encoding="utf-8")
    assert "current_system_prompt_version" in src
    assert "prompt_version=prompt_version" in src


# ── Models declare the prompt_version column ─────────────────────────


@pytest.mark.parametrize(
    "model_path,classname",
    [
        ("app.models.mission", "MissionStep"),
        ("app.models.feedback", "Feedback"),
        ("app.models.error_log", "ErrorLog"),
    ],
)
def test_existing_models_declare_prompt_version(model_path, classname) -> None:
    """The four new Sprint 3.7 tables (Jalon 1) already carry the column.
    These three pre-existing tables now must too — otherwise the
    _safe_columns ADD COLUMN at boot is invisible to SQLAlchemy and
    every write inserts NULL silently."""
    import importlib
    mod = importlib.import_module(model_path)
    klass = getattr(mod, classname)
    assert "prompt_version" in klass.__table__.columns, (
        f"{classname} must declare `prompt_version` to match _safe_columns "
        f"ADD COLUMN in database.py — otherwise the inserts insert NULL."
    )
