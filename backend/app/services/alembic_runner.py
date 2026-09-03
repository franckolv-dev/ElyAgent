# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/alembic_runner.py
# @brief      Migrations Alembic au boot (B-4, revue 2026-06-10).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Boot-time Alembic integration.

Avant ce module, toute évolution de schéma passait par ``create_all`` +
une liste d'``ALTER TABLE`` ad hoc dont les exceptions étaient avalées —
drift silencieux modèle/DB (le bug ``critic_run_at`` : colonne en DB,
jamais sur le modèle, 676 erreurs en prod) et aucune migration
transformante possible (NOT NULL, renommage, backfill).

Stratégie d'adoption douce :
- les bases existantes (et fraîches, créées par ``create_all``) sont
  **stampées** sur la révision baseline ``0001_baseline`` au premier boot ;
- les révisions POSTÉRIEURES à la baseline sont appliquées par
  ``upgrade head`` à chaque boot ;
- les commandes Alembic sont synchrones et ``env.py`` fait son propre
  ``asyncio.run`` → exécution dans un thread (``asyncio.to_thread``)
  pour ne pas entrer en collision avec l'event loop du lifespan.

Best-effort : un échec de migration est loggé CRITIQUE mais ne tue pas
le boot (le schéma create_all reste fonctionnel) — l'opérateur décide.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/


def _alembic_config():
    from alembic.config import Config

    ini = _BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    return cfg


def _has_version_table_sync() -> bool:
    """Vérifie l'existence de ``alembic_version`` via une connexion sync
    courte et dédiée (on est dans un thread, pas sur la loop)."""
    import sqlalchemy as sa

    from app.config import get_settings

    url = get_settings().database_url
    sync_url = url.replace("+aiosqlite", "").replace("+asyncpg", "")
    engine = sa.create_engine(sync_url)
    try:
        with engine.connect() as conn:
            return sa.inspect(conn).has_table("alembic_version")
    finally:
        engine.dispose()


def migrations_current_sync() -> bool:
    """La base est-elle au head des révisions ? Pour `/health/deep`.

    ``ensure_migrations`` est best-effort : un échec au boot (ex. image
    Docker sans ``migrations/`` — vécu v1.17.0, missions.spec_yaml jamais
    créée → 500) ne laissait AUCUNE trace hors d'un CRITICAL dans les
    logs. La sonde profonde expose désormais ce drift au monitoring.
    """
    import sqlalchemy as sa

    from alembic.script import ScriptDirectory

    from app.config import get_settings

    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    url = get_settings().database_url
    sync_url = url.replace("+aiosqlite", "").replace("+asyncpg", "")
    engine = sa.create_engine(sync_url)
    try:
        with engine.connect() as conn:
            if not sa.inspect(conn).has_table("alembic_version"):
                return False
            current = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
            return current == head
    finally:
        engine.dispose()


def _stamp_or_upgrade_sync() -> str:
    from alembic import command

    cfg = _alembic_config()
    if not _has_version_table_sync():
        # Base jamais vue par Alembic : on la déclare au niveau BASELINE
        # (pas head !) puis on upgrade. Stamper head sauterait les
        # révisions post-baseline sur une base EXISTANTE (colonne manquante
        # à jamais — le piège classique de l'adoption). Les installs
        # fraîches créées par create_all ont déjà tout : les révisions
        # post-baseline sont écrites défensives (vérif d'existence) et
        # no-opent proprement. Convention documentée dans 0002.
        command.stamp(cfg, "0001_baseline")
        command.upgrade(cfg, "head")
        return "stamped+upgraded"
    command.upgrade(cfg, "head")
    return "upgraded"


async def ensure_migrations() -> str:
    """Stampe ou upgrade la base. Retourne "stamped" | "upgraded" | "skipped"."""
    try:
        outcome = await asyncio.to_thread(_stamp_or_upgrade_sync)
        logger.info("alembic: %s (head)", outcome)
        return outcome
    except Exception as exc:
        logger.critical(
            "alembic: migration échouée — le schéma create_all reste "
            "fonctionnel mais les révisions ne sont PAS appliquées : %s", exc,
        )
        return "skipped"
