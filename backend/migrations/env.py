# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/migrations/env.py
# @brief      Environnement Alembic async (B-4, revue 2026-06-10).
# @license    Elastic License 2.0
# =============================================================================
"""Alembic async environment.

L'URL vient de ``app.config.get_settings().database_url`` (une seule
source de vérité avec l'application) ; la métadonnée cible est le
``Base.metadata`` de l'app — ``--autogenerate`` voit donc exactement les
modèles réels.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False : le défaut de fileConfig DÉSACTIVE
    # tous les loggers déjà créés — au boot in-process (alembic_runner)
    # ça éteindrait les loggers de l'app entière (et ça rendait muets les
    # tests caplog exécutés après une migration).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Importe tous les modèles pour que Base.metadata soit complet
from app import models  # noqa: F401,E402
from app.config import get_settings  # noqa: E402
from app.database import Base  # noqa: E402

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Mode offline — émet le SQL sans connexion."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_url().startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # batch mode : indispensable pour ALTER sur SQLite
        render_as_batch=_url().startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
