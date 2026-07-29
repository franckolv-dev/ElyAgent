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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)


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
    # PostgreSQL / other (B-5, revue 2026-06-10) — le pool par défaut
    # (5+10) serait le premier goulot invisible après une migration : gels
    # de 30 s aléatoires quand crons + WS + webhooks dépassent 15 connexions.
    # pool_pre_ping écarte les connexions mortes (restart du serveur PG).
    return create_async_engine(
        url,
        echo=False,
        pool_size=20,
        max_overflow=30,
        pool_timeout=30,
        pool_pre_ping=True,
    )


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
        # `create_all` crée les tables MANQUANTES. Il ne fait évoluer aucune
        # table existante — c'est Alembic qui s'en charge, et lui seul.
        #
        # Ici vivait `_safe_columns` : 19 `ALTER TABLE … ADD COLUMN` rejoués à
        # chaque démarrage, échouant chacun sur « duplicate column ». Béquille
        # d'avant Alembic, mesurée sans effet le 29/07 (les 19 colonnes sont
        # dans les modèles ET dans la base de production).
        #
        # ⚠️ Ne pas la faire renaître : une nouvelle colonne se déclare dans
        # son modèle et se propage par une révision Alembic. Un second chemin
        # de migration laisse le schéma diverger en silence — c'est ce drift
        # qui avait produit le bug `critic_run_at` (676 AttributeError en
        # production).
        await conn.run_sync(Base.metadata.create_all)
