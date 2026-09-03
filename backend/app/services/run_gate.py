# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/run_gate.py
# @brief      Cap de runs agent concurrents par utilisateur
#             (revue multi-utilisateurs 2026-06-10, constat B-15).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Per-user concurrent agent-run gate.

Sans borne, 1 user × 10 onglets = 10 runs LLM concurrents : coût cloud
multiplié, RAM, contention SQLite — et les autres utilisateurs paient la
facture en latence. Chaque run de chat/voice acquiert le sémaphore de son
user avant de démarrer ; au-delà de ``ELY_MAX_AGENT_RUNS_PER_USER``
(défaut 2), les runs supplémentaires du MÊME user font la queue sans
impacter les autres.

Le dict de sémaphores croît avec le nombre d'utilisateurs actifs du
process (quelques dizaines d'entrées au pire) — pas d'éviction nécessaire.
"""
from __future__ import annotations

import asyncio
import os

MAX_RUNS_PER_USER = max(1, int(os.environ.get("ELY_MAX_AGENT_RUNS_PER_USER", "2")))

_semaphores: dict[str, asyncio.Semaphore] = {}


def get_user_run_semaphore(user_id: str) -> asyncio.Semaphore:
    sem = _semaphores.get(user_id)
    if sem is None:
        sem = asyncio.Semaphore(MAX_RUNS_PER_USER)
        _semaphores[user_id] = sem
    return sem
