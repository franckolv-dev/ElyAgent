# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/local_abandonne.py
# @brief      Une voie locale abandonnée ne laisse rien à l'écran.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le signal « la voie locale vient d'être abandonnée », et le retrait de ce
qu'elle avait déjà streamé.

19/09/2026 — MiniCPM, coupé par son délai de 25 s au milieu d'un appel d'outil,
laissait `<function name="web_search"><param name="query">heure actuelle
Californie` devant la réponse de GPT-5.6, à l'écran et dans l'historique. Le
routeur du chat ajoute chaque token streamé à la réponse ; rien ne retirait
ceux d'un modèle qu'on venait d'écarter.

Le signal passe DANS le flux d'événements du graphe, et pas par la file du
toast de repli : celle-ci n'est lue qu'en fin de tour, trop tard pour savoir
quels tokens retirer. Ici il arrive à sa place chronologique, après les tokens
du local et avant ceux du cloud.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

EVENEMENT = "ely.local_abandonne"


async def signaler() -> None:
    """Émet le signal dans le flux du graphe. Ne lève jamais.

    Hors d'un graphe (tâche planifiée sans flux, test unitaire du nœud), il n'y
    a personne à prévenir : l'émission échoue et c'est sans conséquence.
    """
    try:
        from langchain_core.callbacks.manager import adispatch_custom_event

        await adispatch_custom_event(EVENEMENT, {})
    except Exception as exc:  # noqa: BLE001
        logger.debug("abandon du local non signalé au flux (%s)", exc)


def retirer_le_passage(
    ai_content: str, synthese: str, marque: tuple[int, int],
) -> tuple[str, str, str]:
    """Retire ce qui a été streamé depuis `marque`. Rend (complet, synthèse, retiré).

    `marque` = les longueurs des deux tampons au début du dernier appel de
    modèle. `on_tool_start` vide la synthèse entre-temps : la marque peut donc
    dépasser sa longueur, d'où les `min`.
    """
    debut_ai = min(marque[0], len(ai_content))
    debut_synthese = min(marque[1], len(synthese))
    return ai_content[:debut_ai], synthese[:debut_synthese], ai_content[debut_ai:]
