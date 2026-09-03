# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/singleton_guard.py
# @brief      Verrou mono-process au démarrage (revue 2026-06-10, A-7).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Boot-time single-process lock.

L'architecture ELY est volontairement mono-process : HITL pendants,
ws_registry, caches PII, 4 APScheduler, bots de channels et subprocess MCP
vivent dans la RAM du process. Lancer ``--workers 2`` (ou deux conteneurs
sur le même volume) casse silencieusement au moins 8 composants — HITL
split-brain (Allow → 404), crons en double, Telegram 409, double tick de
missions… (constat A-7 de la revue multi-utilisateurs).

Ce module transforme l'hypothèse implicite en INVARIANT vérifié : un
``flock`` exclusif non bloquant est pris au boot sur un fichier à côté de
la base SQLite (donc partagé entre conteneurs montant le même volume). Si
le verrou est déjà tenu, le boot ÉCHOUE avec un message explicite plutôt
que de corrompre l'état en silence.

Échappatoire documentée : ``ELY_ALLOW_MULTIPROCESS=true`` — réservée au
jour où l'état partagé (HITL, registry) aura été externalisé (chemin
Postgres/instances multiples, cf. Phase 3 du rapport).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_lock_handle = None  # référence forte — le flock vit tant que le process vit


def _lock_path() -> Path:
    from app.config import get_settings

    url = get_settings().database_url
    if "sqlite" in url:
        db_path = Path(url.split("sqlite+aiosqlite:///")[-1])
        if db_path.parent.is_dir():
            return db_path.parent / ".ely-singleton.lock"
    import tempfile
    return Path(tempfile.gettempdir()) / "ely-singleton.lock"


def acquire_singleton_lock() -> bool:
    """Prend le verrou exclusif. ``RuntimeError`` si un autre process le tient.

    Retourne False (sans verrouiller) quand l'échappatoire env est posée ou
    quand la plateforme n'a pas ``fcntl`` (Windows dev) — on logge et on
    continue, le verrou est un garde-fou, pas une feature.
    """
    global _lock_handle

    if os.environ.get("ELY_ALLOW_MULTIPROCESS", "").lower() in ("1", "true", "yes"):
        logger.warning(
            "ELY_ALLOW_MULTIPROCESS actif — verrou mono-process désactivé. "
            "Assure-toi que l'état partagé (HITL, ws_registry, schedulers) "
            "est externalisé, sinon comportement split-brain garanti."
        )
        return False

    try:
        import fcntl
    except ImportError:  # plateforme sans flock — best-effort
        logger.warning("fcntl indisponible — verrou mono-process non appliqué")
        return False

    path = _lock_path()
    handle = open(path, "a+")  # noqa: SIM115 — doit survivre à la fonction
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError(
            f"\n\n⛔  Un autre process backend ELY tient déjà le verrou "
            f"({path}).\n"
            "L'architecture est mono-process : HITL, registres WebSocket, "
            "schedulers et bots vivent en RAM — un 2e worker provoquerait "
            "un split-brain silencieux (constat A-7, revue 2026-06-10).\n"
            "  - uvicorn doit tourner SANS --workers N ;\n"
            "  - un seul conteneur backend par volume de données ;\n"
            "  - échappatoire (état externalisé uniquement) : "
            "ELY_ALLOW_MULTIPROCESS=true\n"
        )
    handle.truncate(0)
    handle.write(str(os.getpid()))
    handle.flush()
    _lock_handle = handle
    logger.info("Verrou mono-process acquis (%s, pid %d)", path, os.getpid())
    return True


def release_singleton_lock() -> None:
    """Libération explicite (tests) — sinon l'OS libère à la mort du process."""
    global _lock_handle
    if _lock_handle is not None:
        try:
            import fcntl
            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        _lock_handle.close()
        _lock_handle = None
