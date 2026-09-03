# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_licence_service.py
# @brief      Tests for licence_service — MIT (info-only)
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Unit tests for the licence service after the 22 May 2026 pivot.

Pre-pivot this suite verified tier activation (free / pro / business /
enterprise), the click-wrap consent flow, max-user enforcement, and
the activation-supersedes-previous invariant. None of that exists
anymore — there is a single MIT licence, no activation, no
tiers, no max-user cap.

We keep a few sanity tests :
  - ``check_user_creation_allowed`` always returns ``(True, None)``
  - ``get_licence_status`` returns the expected static shape
  - ``get_active_licence`` returns ``None`` (legacy no-op)

The ``Licence`` SQLAlchemy table is kept (forensic history) and is
exercised by ``create_all`` in the fixture below so a sanity smoke test
catches breakage at startup.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
# Importing the model registers it on Base.metadata (required for create_all).
from app.models import licence as _licence  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.services import licence_service


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
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


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_user_creation_always_allowed_no_users(session):
    """Empty DB, no users yet — MIT has no cap, must allow."""
    allowed, msg = await licence_service.check_user_creation_allowed(session)
    assert allowed is True
    assert msg is None


@pytest.mark.asyncio
async def test_check_user_creation_always_allowed_with_users(session):
    """Even with users already in DB, no cap applies."""
    from app.models.user import User
    for i in range(5):
        session.add(User(
            username=f"u{i}", email=f"u{i}@x.test", hashed_password="x", role="user",
        ))
    await session.commit()
    allowed, msg = await licence_service.check_user_creation_allowed(session)
    assert allowed is True
    assert msg is None


@pytest.mark.asyncio
async def test_get_active_licence_returns_none(session):
    """Legacy alias — must not crash, must return None now that there
    is no active licence row to look up."""
    assert await licence_service.get_active_licence(session) is None


@pytest.mark.asyncio
async def test_get_licence_status_shape_is_stable(session):
    """The Settings panel + Sidebar banner read this. Pin the exact
    keys so a refactor that drops a field can't silently break the UI."""
    status = await licence_service.get_licence_status(session)
    assert status["license"] == "MIT"
    assert status["name"] == "MIT"
    assert status["url"].startswith("https://opensource.org/")
    assert "agent-ely.fr" in status["summary_url"]
    assert isinstance(status["free_for"], list)
    assert isinstance(status["forbidden"], list)
    assert len(status["free_for"]) >= 1
    assert len(status["forbidden"]) >= 1


@pytest.mark.asyncio
async def test_get_licence_status_does_not_depend_on_db_rows(session):
    """Whether or not the legacy ``licences`` table has historic rows
    must not change the returned status — it's a fixed payload."""
    # Insert some legacy rows that would have meant something pre-pivot
    from app.models.licence import Licence
    session.add(Licence(
        tier="pro", customer_label="ghost", is_active=True, max_users=5,
    ))
    await session.commit()
    status = await licence_service.get_licence_status(session)
    assert status["license"] == "MIT"
    # No tier, max_users, customer_label leak into the response
    assert "tier" not in status
    assert "max_users" not in status
    assert "customer_label" not in status
