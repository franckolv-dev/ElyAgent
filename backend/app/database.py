# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/database.py
# @brief      Async SQLAlchemy database setup
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# Engine and session factory are module-level singletons.
# get_settings() uses lru_cache so Settings is only constructed once;
# pydantic-settings reads .env at that moment, which happens when this
# module is first imported (during the uvicorn startup sequence, after
# the working directory is already correct).
engine = create_async_engine(get_settings().database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    # Make sure every model is imported so create_all sees its table.
    # The package __init__ already imports all of them — this just makes
    # the dependency explicit and prevents import-order pitfalls when a
    # model-only file is added without re-exporting it.
    from app import models  # noqa: F401  (registers tables with Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight idempotent column adds — SQLAlchemy's create_all does NOT
        # alter existing tables, so when a model gains a new column we patch it
        # here. Each entry is (table, column_name, ddl_type_with_default).
        # Wrapped in try/except so a duplicate-column error never breaks boot.
        from sqlalchemy import text
        _safe_columns = [
            ("users", "language", "VARCHAR(2) NOT NULL DEFAULT 'fr'"),
            ("users", "hitl_preferred_channel", "VARCHAR(20)"),
        ]
        for _table, _col, _ddl in _safe_columns:
            try:
                await conn.execute(text(f"ALTER TABLE {_table} ADD COLUMN {_col} {_ddl}"))
            except Exception:
                # Column already exists — SQLite raises OperationalError, that's
                # the steady-state on every restart after the initial migration.
                pass
