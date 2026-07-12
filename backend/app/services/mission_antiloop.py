# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_antiloop.py
# @brief      Missions autonomes J5 — anti-boucle D4 : détection d'un appel
#             d'outil identique répété en échec (cooldown + stratégie alterne).
# @license    Elastic License 2.0
# =============================================================================
"""Anti-boucle pathologique des missions autonomes (cadrage D4).

« Le même outil qui échoue 3 fois de suite avec les mêmes arguments →
cooldown + obligation de stratégie alternative (pas d'arrêt). » On lit
l'historique persisté (``mission_steps``, phase ``act``) et on compte les
échecs CONSÉCUTIFS LES PLUS RÉCENTS de même signature (outil + args). Le
gate d'``act_node`` refuse alors le prochain appel identique et pousse le
LLM à diverger. Best-effort : un incident de lecture ne bloque jamais une
mission (renvoie 0 = « pas de boucle détectée »).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Final

from sqlalchemy import desc, select

from app.database import async_session
from app.models.mission import MissionStep

logger = logging.getLogger(__name__)

COOLDOWN_THRESHOLD: Final[int] = 3
_SCAN_WINDOW: Final[int] = 12   # profondeur de lecture des steps act récents


def call_signature(tool_name: str, tool_input: dict | None) -> str:
    """Empreinte stable d'un appel (outil + args), insensible à l'ordre des
    clés. ``None`` et ``{}`` donnent la même signature."""
    canon = json.dumps(tool_input or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{tool_name}\x00{canon}".encode("utf-8")).hexdigest()[:16]


async def consecutive_identical_failures(
    mission_id: str, tool_name: str, tool_input: dict | None,
) -> int:
    """Nombre d'échecs ``act`` consécutifs (les plus récents) dont la
    signature vaut ``call_signature(tool_name, tool_input)``. S'arrête au
    premier appel d'outil qui diffère OU qui a réussi. 0 sur erreur."""
    target = call_signature(tool_name, tool_input)
    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(MissionStep)
                .where(
                    MissionStep.mission_id == mission_id,
                    MissionStep.phase == "act",
                    MissionStep.tool_name.isnot(None),
                )
                .order_by(desc(MissionStep.iteration))
                .limit(_SCAN_WINDOW)
            )).scalars().all()
    except Exception as exc:  # noqa: BLE001 — l'anti-boucle ne casse pas une mission
        logger.debug("Anti-boucle : lecture steps %s impossible : %s", mission_id, exc)
        return 0

    count = 0
    for s in rows:
        if call_signature(s.tool_name or "", s.tool_input) != target:
            break            # appel différent → la série est rompue
        if s.success:
            break            # un succès identique rompt aussi la série
        count += 1
    return count
