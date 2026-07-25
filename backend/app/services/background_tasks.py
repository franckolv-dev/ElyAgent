# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/background_tasks.py
# @brief      Strong-referenced fire-and-forget task spawner
#             (revue multi-utilisateurs 2026-06-10, §4 mineurs).
# @license    Elastic License 2.0
# =============================================================================
"""Strong-referenced fire-and-forget task spawner.

``asyncio.create_task(...)`` only gives the event loop a WEAK reference to
the task: if the caller drops the returned handle (the classic
fire-and-forget idiom), the task can be garbage-collected mid-flight and
silently never complete. In ELY that meant learning signals, memory
extraction and FTS indexing could vanish under GC pressure — invisible in
mono-user, measurable with N users.

Pattern lifted from ``agent/sub_agents/factory.py`` (``_bg_tasks``), which
documented the hazard first; this module centralises it so every
fire-and-forget site uses the same registry and gets exception logging for
free.

Usage::

    from app.services.background_tasks import spawn
    spawn(record_signal(...), label="learning.hitl_refusal")
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_BG_TASKS: set[asyncio.Task] = set()


def spawn(
    coro: Coroutine[Any, Any, Any],
    *,
    label: str | None = None,
    detach_context: bool = False,
) -> asyncio.Task:
    """Schedule ``coro`` with a strong reference held until completion.

    Exceptions are logged (warning) instead of disappearing with the task.
    ``label`` defaults to the coroutine's qualname so drop-in replacements
    of bare ``asyncio.create_task(...)`` keep a meaningful name for free.
    Returns the task for callers that want to await/cancel it anyway.

    ``detach_context=True`` (C4-2d) : exécute la coroutine dans un contexte
    contextvars VIERGE. Indispensable pour les tâches de fond qui font leurs
    PROPRES appels LLM : ``create_task`` hérite sinon du contexte appelant,
    et LangChain propage son arbre de callbacks par contextvars — les tokens
    du LLM de fond partent alors dans le STREAM de l'appelant (bug réel
    19/07 : le code du générateur tier-S entrelacé caractère par caractère
    avec la réponse d'Ely dans le chat de l'utilisateur). Contrepartie : la
    tâche perd aussi les vars de corrélation — passer tout par arguments.
    """
    import contextvars

    resolved = label or getattr(coro, "__qualname__", None) or "bg"
    if detach_context:
        task = asyncio.get_running_loop().create_task(
            coro, name=resolved, context=contextvars.Context(),
        )
    else:
        task = asyncio.create_task(coro, name=resolved)
    _BG_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _BG_TASKS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("Background task %r failed: %s", resolved, exc)

    task.add_done_callback(_done)
    return task


def pending_count() -> int:
    """Number of in-flight background tasks (observability helper)."""
    return len(_BG_TASKS)


async def drain(timeout: float = 5.0) -> int:
    """Attend la fin des tâches de fond en vol. Rend le nombre de terminées.

    ``pending_count()`` savait compter, il manquait de quoi attendre. Deux
    usages : un arrêt propre (ne pas couper une écriture en cours), et la fin
    de course dans les tests — une fixture qui supprime son utilisateur juste
    après un flux qui a spawné du travail peut voir ce travail ré-insérer une
    ligne enfant entre le DELETE des enfants et le DELETE du user.

    Ne propage jamais l'échec d'une tâche : ``spawn`` le journalise déjà, et
    un drain qui lève transformerait un arrêt propre en arrêt brutal. Au-delà
    de ``timeout``, on rend la main — un drain ne bloque jamais indéfiniment.
    """
    tasks = [t for t in _BG_TASKS if not t.done()]
    if not tasks:
        return 0
    done, _pending = await asyncio.wait(tasks, timeout=timeout)
    return len(done)
