# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/pool_watch.py
# @brief      Une sonde sur le pool de connexions : quand il sature, dire
#             QUI tient les connexions, pas seulement qu'il est plein.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Le 03/09/2026 à 20:19, pendant une mission libre de 96 actions :

    sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10
    reached, connection timed out, timeout 30.00

Toute l'API a rendu 500 pendant cinq minutes — jusqu'à `/api/hitl/pending`
— puis tout est reparti seul. La base SQLite, elle, était libre (aucun verrou
d'écriture, lectures instantanées) : ce sont des CONNEXIONS du pool que des
coroutines tenaient, pas un verrou. Sans photo des tâches en vol à ce
moment-là, impossible de dire lesquelles.

Cette sonde relit le pool toutes les ``INTERVALLE_S`` secondes et, quand il
est presque plein, journalise la pile de chaque tâche asyncio en vol — une
fois par ``ACCALMIE_S``, pour ne pas noyer le journal. Elle ne corrige rien :
elle nomme.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback

logger = logging.getLogger(__name__)

INTERVALLE_S = 15.0
SEUIL = 0.9          # part du pool (taille + débordement) tenue = « saturé »
ACCALMIE_S = 300.0   # au plus un cliché toutes les cinq minutes
_PROFONDEUR = 6      # lignes de pile par tâche


def est_sature(statut: dict, seuil: float = SEUIL) -> bool:
    """Le pool est-il presque plein ? ``statut`` vient de ``database.pool_status``."""
    capacite = int(statut.get("size", 0)) + int(statut.get("max_overflow", 0))
    if capacite <= 0:
        return False
    return int(statut.get("checked_out", 0)) >= capacite * seuil


def cliche_des_taches(taches, profondeur: int = _PROFONDEUR, maxi: int = 60) -> str:
    """Une ligne de titre puis la pile courte de chaque tâche en vol.

    Les tâches sans pile (terminées, ou en attente sans frame) sont comptées
    mais pas détaillées : c'est le sommet de pile des autres qui dit où elles
    attendent."""
    lignes: list[str] = []
    detaillees = 0
    for t in taches:
        if detaillees >= maxi:
            break
        try:
            nom = t.get_name()
            frames = t.get_stack(limit=profondeur)
        except Exception:  # noqa: BLE001 — une tâche illisible ne fait pas taire la sonde
            continue
        if not frames:
            continue
        detaillees += 1
        lignes.append(f"- {nom}")
        for f in frames:
            lignes.append("    " + "".join(traceback.format_stack(f, limit=1)).rstrip().split("\n")[0].strip())
    tete = f"{len(list(taches))} tâche(s) en vol, {detaillees} avec une pile :"
    return tete + ("\n" + "\n".join(lignes) if lignes else "")


async def surveiller_le_pool(
    *, intervalle_s: float = INTERVALLE_S, seuil: float = SEUIL, accalmie_s: float = ACCALMIE_S,
) -> None:
    """Boucle de fond : lit le pool, journalise un cliché quand il sature."""
    from app.database import pool_status

    dernier_cliche = 0.0
    while True:
        try:
            statut = pool_status()
            if est_sature(statut, seuil) and time.monotonic() - dernier_cliche >= accalmie_s:
                dernier_cliche = time.monotonic()
                taches = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                logger.warning(
                    "[pool] saturé — %s ; %s",
                    ", ".join(f"{k}={v}" for k, v in statut.items()),
                    cliche_des_taches(taches),
                )
        except Exception as exc:  # noqa: BLE001 — une sonde ne fait jamais tomber le serveur
            logger.debug("[pool] sonde muette : %s", exc)
        await asyncio.sleep(intervalle_s)
