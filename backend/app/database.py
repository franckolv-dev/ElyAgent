# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/database.py
# @brief      Async SQLAlchemy database setup
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
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
def _make_engine():
    settings = get_settings()
    url = settings.database_url
    # SQLite-specific tuning — safe to apply, ignored for PostgreSQL URLs.
    if url.startswith("sqlite"):
        from sqlalchemy import event
        _engine = create_async_engine(
            url,
            echo=False,
            connect_args={
                "timeout": 30,          # busy-wait up to 30s instead of raising immediately
                "check_same_thread": False,
            },
        )
        # Enable WAL mode and increase cache on every new connection.
        # WAL allows concurrent readers while a write is in progress —
        # critical once several users are active simultaneously.
        @event.listens_for(_engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")   # ms — belt-and-suspenders
            cur.execute("PRAGMA synchronous=NORMAL")    # safe with WAL, faster than FULL
            cur.execute("PRAGMA cache_size=-32000")     # 32 MB page cache
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        return _engine
    # PostgreSQL / other — no special args needed.
    return create_async_engine(url, echo=False)


engine = _make_engine()
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
            ("users", "onboarding_completed_at", "DATETIME"),
            ("users", "onboarding_skipped_at", "DATETIME"),
            ("users", "onboarding_step", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "onboarding_skip_count", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "tts_auto_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
            # Hermes Chantier 1 (audit 2026-05-07) — sticky toolset profile
            # per conversation. NULL until first message auto-detects it.
            ("conversations", "toolset_profile", "VARCHAR(40)"),
            # Sprint 2.5 (memory cognitive multi-typed) — dreaming-style scoring
            # for short→long-term promotion. Inspired by OpenClaw memory-core.
            ("user_memory_logs", "recall_count", "INTEGER NOT NULL DEFAULT 0"),
            ("user_memory_logs", "last_recalled_at", "DATETIME"),
            # Sprint 3.7 Jalon 1 (auto-improvement) — prompt_version hash so
            # every learning signal can be correlated with the exact prompt
            # text active at the time. sha256(prompt)[:8], NULL for historical
            # rows written before this column existed.
            ("feedback", "prompt_version", "VARCHAR(16)"),
            ("mission_steps", "prompt_version", "VARCHAR(16)"),
            ("error_log", "prompt_version", "VARCHAR(16)"),
            # Sprint 3.7 Jalon 4 — LLM-as-judge bookkeeping : timestamp when
            # the post-mortem critic last ran for this mission. NULL = not yet.
            ("missions", "critic_run_at", "DATETIME"),
            # Sprint 4b V2 J1 — @tool Python generation. content_format
            # distinguishes V1 markdown playbooks from V2 python_tool source;
            # validation_report_json holds the 5-stage pipeline report.
            # Existing rows backfill to 'markdown_playbook' / '{}' via DEFAULT.
            ("learned_skills", "content_format", "VARCHAR(20) NOT NULL DEFAULT 'markdown_playbook'"),
            ("learned_skills", "validation_report_json", "TEXT NOT NULL DEFAULT '{}'"),
            # Mission autonomous mode (2026-06-04) — auto-approve non-floor HITL
            # for unattended runs. Existing missions stay non-autonomous (0).
            ("missions", "autonomous", "BOOLEAN NOT NULL DEFAULT 0"),
        ]
        for _table, _col, _ddl in _safe_columns:
            try:
                await conn.execute(text(f"ALTER TABLE {_table} ADD COLUMN {_col} {_ddl}"))
            except Exception:
                # Column already exists — SQLite raises OperationalError, that's
                # the steady-state on every restart after the initial migration.
                pass
