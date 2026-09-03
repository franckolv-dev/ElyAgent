# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_auth_revoke_idempotent.py
# @brief      Révocation refresh idempotente — refresh concurrents ≠ 500.
# @license    MIT
# =============================================================================
"""Révocation de refresh token idempotente (blacklist ``revoked_tokens``).

Bug prod (18/07/2026) : deux onglets relancent POST /auth/refresh en même
temps après un restart backend. Les deux requêtes passent le check de
blacklist avant que l'une ne committe, puis tentent le même INSERT →
``sqlite3.IntegrityError UNIQUE constraint failed: revoked_tokens.jti`` → 500.
L'issue métier est pourtant identique (le jti est bien révoqué) : révoquer un
jti déjà révoqué doit être un succès silencieux, pas une 500.

Hermétique : engine SQLite dédié sur fichier temp, handlers appelés
directement (une session par « requête », comme get_db en prod).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """Sessions indépendantes sur un fichier SQLite temp (≈ deux requêtes réelles)."""
    import app.models  # noqa: F401 — enregistre toutes les tables sur Base.metadata
    from app.database import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth_test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_revoke_same_jti_twice_no_error_single_row(session_factory):
    """Deux révocations du même jti → pas d'exception, une seule ligne."""
    from app.models.revoked_token import RevokedToken
    from app.routers.auth import _revoke_refresh_jti

    expires = datetime.now(timezone.utc) + timedelta(days=30)

    # Deux sessions distinctes : la seconde n'a jamais vu la ligne de la
    # première (même situation que deux requêtes concurrentes en prod).
    async with session_factory() as db1:
        await _revoke_refresh_jti(db1, "jti-race", expires)
    async with session_factory() as db2:
        await _revoke_refresh_jti(db2, "jti-race", expires)  # levait IntegrityError

    async with session_factory() as db:
        rows = (
            await db.execute(select(RevokedToken).where(RevokedToken.jti == "jti-race"))
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_concurrent_refresh_same_cookie_both_succeed(session_factory):
    """Deux POST /auth/refresh en parallèle avec le même cookie → aucun 500.

    Reproduit le scénario prod : les deux handlers passent le check de
    blacklist avant le premier commit, puis insèrent le même jti.
    """
    from fastapi import Response

    from app.auth.jwt import create_refresh_token
    from app.models.revoked_token import RevokedToken
    from app.models.user import User
    from app.routers.auth import refresh

    async with session_factory() as db:
        db.add(
            User(
                id="u-refresh",
                username="refresh-user",
                email="refresh@test.local",
                hashed_password="x",
                role="user",
            )
        )
        await db.commit()

    token = create_refresh_token({"sub": "u-refresh"})

    async def one_refresh():
        async with session_factory() as db:
            return await refresh(Response(), refresh_token=token, db=db)

    # Avant le fix : le perdant lève IntegrityError (UNIQUE jti) → 500 ASGI.
    res_a, res_b = await asyncio.gather(one_refresh(), one_refresh())
    assert res_a.access_token
    assert res_b.access_token

    async with session_factory() as db:
        count = (
            await db.execute(select(func.count()).select_from(RevokedToken))
        ).scalar_one()
    assert count == 1
