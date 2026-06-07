# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_sovereignty_routing.py
# @brief      PII-sovereignty routing — ContextVar + tier config override.
# @license    Elastic License 2.0
# =============================================================================
"""When User.sovereignty_strict is on and a ContextVar reflects it, tier-B/C
calls must route to the Mistral EU chain instead of the default cloud chain.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"sov-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"sov_{uid}", email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        from app.models.user import User as _U
        await db.execute(delete(_U).where(_U.id == uid))
        await db.commit()


# ── User model has the field ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_sovereignty_default_false(_user):
    from app.models.user import User

    async with async_session() as db:
        u = (await db.execute(select(User).where(User.id == _user))).scalar_one()
    assert u.sovereignty_strict is False


# ── ContextVar override of tier config ───────────────────────────────────────


def _seed_mistral_instances(monkeypatch, *, with_large=True, with_medium=True, with_small=True):
    """Stub the LLM instance cache with fake Mistral entries so the routing
    override can be exercised without touching the real DB.

    Also reset ``_tier_config`` to empty so ``get_tier_config()`` falls back to
    ``DEFAULT_TIER_CONFIG`` (i.e. the full tier list). Without this, another
    test can leave behind a partial ``_tier_config`` that doesn't contain
    ``simple``/``maintenance`` and breaks our assertions about unchanged tiers.
    """
    from app.services import llm_provider

    cache: dict[str, dict] = {}
    if with_large:
        cache["inst-mistral-large"] = {"provider": "mistral", "model": "mistral-large-latest"}
    if with_medium:
        cache["inst-mistral-medium"] = {"provider": "mistral", "model": "mistral-medium-latest"}
    if with_small:
        cache["inst-mistral-small"] = {"provider": "mistral", "model": "mistral-small-latest"}
    # Add a non-Mistral instance to make sure it's filtered out.
    cache["inst-deepseek"] = {"provider": "deepseek", "model": "deepseek-v4-flash"}
    monkeypatch.setattr(llm_provider, "_instance_cache", cache)
    # Isolate from any leftover _tier_config a previous test may have set.
    monkeypatch.setattr(llm_provider, "_tier_config", {})


def test_get_sovereign_provider_ids_orders_largest_first(monkeypatch):
    _seed_mistral_instances(monkeypatch)
    from app.services.sovereignty import get_sovereign_provider_ids

    chain = get_sovereign_provider_ids()
    assert chain == ["inst-mistral-large", "inst-mistral-medium", "inst-mistral-small"]


def test_get_sovereign_provider_ids_empty_when_no_mistral(monkeypatch):
    from app.services import llm_provider

    monkeypatch.setattr(llm_provider, "_instance_cache", {
        "inst-deepseek": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    })
    from app.services.sovereignty import get_sovereign_provider_ids

    assert get_sovereign_provider_ids() == []


def test_tier_config_unchanged_when_flag_off(monkeypatch):
    _seed_mistral_instances(monkeypatch)
    from app.services.llm_provider import get_tier_config
    from app.services.sovereignty import SOVEREIGNTY_STRICT

    SOVEREIGNTY_STRICT.set(False)
    cfg = get_tier_config()
    assert "deepseek" not in cfg.get("medium", {}).get("providers", []) or \
           cfg["medium"]["providers"] != ["inst-mistral-large", "inst-mistral-medium", "inst-mistral-small"]


def test_tier_config_overrides_medium_and_complex_when_flag_on(monkeypatch):
    _seed_mistral_instances(monkeypatch)
    from app.services.llm_provider import get_tier_config
    from app.services.sovereignty import SOVEREIGNTY_STRICT

    SOVEREIGNTY_STRICT.set(True)
    try:
        cfg = get_tier_config()
        # MEDIUM and COMPLEX get the Mistral chain.
        for tier in ("medium", "complex"):
            assert cfg[tier]["providers"] == [
                "inst-mistral-large", "inst-mistral-medium", "inst-mistral-small",
            ], f"tier {tier} not overridden: {cfg[tier]}"
            assert cfg[tier]["fallback_enabled"] is True
        # SIMPLE and MAINTENANCE are unaffected (already local).
        assert cfg["simple"]["providers"] == ["ollama"]
        assert cfg["maintenance"]["providers"] == ["ollama"]
    finally:
        SOVEREIGNTY_STRICT.set(False)


def test_tier_config_graceful_fallback_when_no_mistral(monkeypatch):
    """Flag on but no Mistral configured → keep the original chain (no crash)."""
    from app.services import llm_provider

    monkeypatch.setattr(llm_provider, "_instance_cache", {
        "inst-deepseek": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    })
    monkeypatch.setattr(llm_provider, "_tier_config", {})  # see _seed_mistral_instances
    from app.services.llm_provider import get_tier_config
    from app.services.sovereignty import SOVEREIGNTY_STRICT

    SOVEREIGNTY_STRICT.set(True)
    try:
        cfg = get_tier_config()
        # MEDIUM keeps whatever default the user had (not the Mistral chain).
        assert "inst-mistral-large" not in cfg["medium"]["providers"]
    finally:
        SOVEREIGNTY_STRICT.set(False)


def test_tier_config_drops_only_missing_mistral_models(monkeypatch):
    """Only Mistral Large + Small configured → chain has 2 entries, in order."""
    _seed_mistral_instances(monkeypatch, with_medium=False)
    from app.services.llm_provider import get_tier_config
    from app.services.sovereignty import SOVEREIGNTY_STRICT

    SOVEREIGNTY_STRICT.set(True)
    try:
        cfg = get_tier_config()
        assert cfg["medium"]["providers"] == ["inst-mistral-large", "inst-mistral-small"]
    finally:
        SOVEREIGNTY_STRICT.set(False)


# ── Endpoint round-trip ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_patch_persists(_user, monkeypatch):
    _seed_mistral_instances(monkeypatch)
    from app.models.user import User
    from app.routers.sovereignty_prefs import (
        SovereigntyPrefsPatch,
        get_sovereignty_prefs,
        update_sovereignty_prefs,
    )

    async with async_session() as db:
        user = (await db.execute(select(User).where(User.id == _user))).scalar_one()

    # GET initial = false + mistral_configured=True (seeded)
    out = await get_sovereignty_prefs(current_user=user)
    assert out.sovereignty_strict is False
    assert out.mistral_configured is True

    # PATCH to True
    out = await update_sovereignty_prefs(
        body=SovereigntyPrefsPatch(sovereignty_strict=True),
        current_user=user,
    )
    assert out.sovereignty_strict is True

    # GET after PATCH (re-fetch user from DB)
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.id == _user))).scalar_one()
    out = await get_sovereignty_prefs(current_user=user)
    assert out.sovereignty_strict is True


@pytest.mark.asyncio
async def test_endpoint_signals_when_no_mistral(_user, monkeypatch):
    """Surface mistral_configured=False so the UI can warn the user."""
    from app.services import llm_provider

    monkeypatch.setattr(llm_provider, "_instance_cache", {})
    from app.models.user import User
    from app.routers.sovereignty_prefs import get_sovereignty_prefs

    async with async_session() as db:
        user = (await db.execute(select(User).where(User.id == _user))).scalar_one()

    out = await get_sovereignty_prefs(current_user=user)
    assert out.mistral_configured is False
