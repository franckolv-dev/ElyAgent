# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_licence_service.py
# @brief      Unit tests for licence_service (Phase 1)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Unit tests for the licence service.

Mirrors the in-memory-SQLite + StaticPool fixture pattern used by
``tests/test_arena_service.py`` so each test gets a clean schema.

Run :  cd backend && uv run python -m pytest tests/test_licence_service.py -v
"""
from __future__ import annotations

from datetime import datetime, timezone  # noqa: F401
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
# Importing the model registers it on Base.metadata (required for create_all).
from app.models import licence as _licence  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.models.licence import Licence
from app.models.user import User
from app.services import licence_service


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Yield a single ``AsyncSession`` bound to a throwaway in-memory DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s

    await engine.dispose()


async def _make_user(session: AsyncSession, *, role: str = "admin", suffix: str = "") -> User:
    u = User(
        username=f"admin{suffix}",
        email=f"admin{suffix}@example.com",
        hashed_password="x",
        role=role,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return u


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_free_tier_activation_creates_row(session):
    admin = await _make_user(session)
    lic = await licence_service.activate_free_tier(
        session, admin_user_id=admin.id, consent=True
    )
    await session.commit()

    assert lic.tier == "free"
    assert lic.max_users == 4
    assert lic.consent_personal_use is True
    assert lic.licence_key is None
    assert lic.is_active is True
    assert lic.customer_label == "Personal/Family use"


@pytest.mark.asyncio
async def test_free_tier_requires_consent(session):
    admin = await _make_user(session)
    with pytest.raises(ValueError):
        await licence_service.activate_free_tier(
            session, admin_user_id=admin.id, consent=False
        )


@pytest.mark.asyncio
async def test_free_tier_idempotent(session):
    admin = await _make_user(session)
    a = await licence_service.activate_free_tier(session, admin_user_id=admin.id, consent=True)
    await session.commit()
    b = await licence_service.activate_free_tier(session, admin_user_id=admin.id, consent=True)
    assert a.id == b.id


@pytest.mark.asyncio
async def test_paid_activation_stores_key_raw(session):
    admin = await _make_user(session)
    lic = await licence_service.activate_paid_tier(
        session,
        admin_user_id=admin.id,
        tier="business",
        licence_key="ABC-DEF-GHI-JKL-MNO",
        customer_label="Acme Corp",
    )
    await session.commit()

    assert lic.tier == "business"
    assert lic.max_users == 25
    assert lic.licence_key == "ABC-DEF-GHI-JKL-MNO"
    assert lic.customer_label == "Acme Corp"
    assert lic.is_active is True


@pytest.mark.asyncio
async def test_paid_activation_rejects_unknown_tier(session):
    admin = await _make_user(session)
    with pytest.raises(ValueError):
        await licence_service.activate_paid_tier(
            session,
            admin_user_id=admin.id,
            tier="ultra_mega",
            licence_key="X",
            customer_label="X",
        )


@pytest.mark.asyncio
async def test_paid_activation_rejects_empty_key(session):
    admin = await _make_user(session)
    with pytest.raises(ValueError):
        await licence_service.activate_paid_tier(
            session,
            admin_user_id=admin.id,
            tier="pro",
            licence_key="   ",
            customer_label="Acme",
        )


@pytest.mark.asyncio
async def test_new_activation_supersedes_previous(session):
    admin = await _make_user(session)

    await licence_service.activate_free_tier(session, admin_user_id=admin.id, consent=True)
    await session.commit()

    new = await licence_service.activate_paid_tier(
        session,
        admin_user_id=admin.id,
        tier="pro",
        licence_key="KEY",
        customer_label="Acme",
    )
    await session.commit()

    # Re-query — there must be exactly one active row, the new one.
    from sqlalchemy import select, func
    active_count = await session.scalar(
        select(func.count(Licence.id)).where(Licence.is_active.is_(True))
    )
    assert active_count == 1

    active = await licence_service.get_active_licence(session)
    assert active is not None
    assert active.id == new.id
    assert active.tier == "pro"


@pytest.mark.asyncio
async def test_check_user_creation_first_admin_bypass(session):
    # No users, no licence → bootstrap admin must be allowed through.
    allowed, err = await licence_service.check_user_creation_allowed(session)
    assert allowed is True
    assert err is None


@pytest.mark.asyncio
async def test_check_user_creation_blocks_when_at_limit(session):
    # Free tier (max 4) → create 4 users, 5th must be blocked.
    admin = await _make_user(session)
    await licence_service.activate_free_tier(session, admin_user_id=admin.id, consent=True)
    await session.commit()

    # We already have 1 user (admin).  Add 3 more so we're at 4/4.
    for i in range(3):
        session.add(
            User(
                username=f"user{i}",
                email=f"u{i}@example.com",
                hashed_password="x",
                role="user",
            )
        )
    await session.commit()

    allowed, err = await licence_service.check_user_creation_allowed(session)
    assert allowed is False
    assert err is not None
    assert "4 utilisateurs" in err
    assert "free" in err


@pytest.mark.asyncio
async def test_check_user_creation_allows_when_under_limit(session):
    admin = await _make_user(session)
    await licence_service.activate_paid_tier(
        session,
        admin_user_id=admin.id,
        tier="business",
        licence_key="K",
        customer_label="Acme",
    )
    await session.commit()

    allowed, err = await licence_service.check_user_creation_allowed(session)
    assert allowed is True
    assert err is None


@pytest.mark.asyncio
async def test_check_user_creation_unlimited_for_enterprise(session):
    admin = await _make_user(session)
    await licence_service.activate_paid_tier(
        session,
        admin_user_id=admin.id,
        tier="enterprise",
        licence_key="K",
        customer_label="MegaCorp",
    )
    await session.commit()

    # Add a few more users — should still be allowed.
    for i in range(10):
        session.add(
            User(
                username=f"u{i}",
                email=f"u{i}@example.com",
                hashed_password="x",
                role="user",
            )
        )
    await session.commit()

    allowed, err = await licence_service.check_user_creation_allowed(session)
    assert allowed is True
    assert err is None


@pytest.mark.asyncio
async def test_check_user_creation_blocks_without_licence(session):
    # Bootstrap admin already exists, but no licence has been activated yet.
    await _make_user(session)
    allowed, err = await licence_service.check_user_creation_allowed(session)
    assert allowed is False
    assert err is not None
    assert "licence" in err.lower()


@pytest.mark.asyncio
async def test_status_when_not_provisioned(session):
    status = await licence_service.get_licence_status(session)
    assert status["is_provisioned"] is False
    assert status["tier"] is None
    assert status["max_users"] is None
    assert status["current_users"] == 0


@pytest.mark.asyncio
async def test_status_reports_current_users(session):
    admin = await _make_user(session)
    await licence_service.activate_free_tier(session, admin_user_id=admin.id, consent=True)
    await session.commit()

    status = await licence_service.get_licence_status(session)
    assert status["is_provisioned"] is True
    assert status["tier"] == "free"
    assert status["max_users"] == 4
    assert status["current_users"] == 1
    assert status["consent_personal_use"] is True
