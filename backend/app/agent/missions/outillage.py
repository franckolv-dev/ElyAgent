# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/outillage.py
# @brief      Les familles d'outils d'une mission : choisies une fois au
#             premier passage par le petit modèle local, relues ensuite dans
#             le workspace, élargies par ce que `find_tool` découvre.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Pourquoi des FAMILLES et pas des outils.

Mission « Nettoyage mails », 04/09/2026 : 118 actions, 5 M tokens pour une
boîte qui contenait trois mails — ~45 000 tokens par action, le catalogue
complet (227 outils) dans chaque prompt. Le profil `mission` (#323) avait
été choisi parce que le filtre de mots-clés laissait 119 outils injoignables
et qu'une mission n'a personne à qui dire « je n'ai pas l'outil ».

Mesuré la veille sur les traces réelles : le sélecteur local (#302) choisi
outil par outil manque ce que la mission utilise vraiment
(`gmail_raw_api_call`, `session_todo`, `web_search`…). Le même sélecteur,
lu par FAMILLES — le préfixe du nom, `gmail_`, `contacts_`, `scheduler_` —
plus un noyau fixe, ne manque rien : 36 outils pour les mails, 75 pour la
prospection.

Trois règles :
1. la sélection se fait UNE fois, au premier passage, et se relit dans
   ``OUTILS.json`` : le prompt reste stable d'un passage à l'autre (cache) ;
2. un sélecteur qui doute rend tout — aucune restriction, comme avant ;
3. ``find_tool`` reste le filet : un outil découvert entre avec sa famille.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

from app.agent.tool_selector import CORE_TOOLS, select_tools

logger = logging.getLogger(__name__)

# Ce qu'une mission garde quoi qu'il arrive. `find_tool` est la porte vers le
# reste du catalogue ; `session_todo` porte le plan ; `web_search` répond à
# la question que tout objectif finit par poser ; `report_missing_capability`
# évite le tour inutile quand rien n'existe.
NOYAU_MISSION: frozenset[str] = CORE_TOOLS | frozenset({
    "session_todo", "web_search", "report_missing_capability",
})

# Les familles branchées quoi qu'il arrive. `web_*` (6 outils) : recherche,
# actualités, lecture de page — ce que toute mission finit par faire, et ce
# que le rejeu des traces passées a vu manquer (`web_search_news`).
FAMILLES_NOYAU: frozenset[str] = frozenset({"web"})

_FICHIER = "OUTILS.json"


@dataclass
class Outillage:
    familles: list[str]
    outils: list[str]
    choisis: list[str]


def famille(nom: str) -> str:
    """Le préfixe du nom (« gmail_raw_api_call » → « gmail »)."""
    return (nom or "").split("_", 1)[0]


def _noms(catalogue: Sequence[Any]) -> list[str]:
    return [getattr(t, "name", "") for t in catalogue]


def _outils_des_familles(familles: set[str], catalogue: Sequence[Any]) -> list[str]:
    return sorted(
        n for n in _noms(catalogue)
        if famille(n) in familles or famille(n) in FAMILLES_NOYAU or n in NOYAU_MISSION
    )


async def choisir_l_outillage(goal: str, catalogue: Sequence[Any]) -> Optional[Outillage]:
    """Les familles d'outils que l'objectif appelle, ou ``None`` si le
    sélecteur n'a pas tranché (pas de modèle, réponse illisible) : dans ce
    cas la mission garde tout le catalogue."""
    choisis = await select_tools(goal, catalogue, include_core=True)
    if len(choisis) >= len(catalogue):
        return None
    noms_choisis = _noms(choisis)
    familles = {famille(n) for n in noms_choisis if n not in NOYAU_MISSION}
    if not familles:
        return None
    return Outillage(
        familles=sorted(familles),
        outils=_outils_des_familles(familles, catalogue),
        choisis=noms_choisis,
    )


# ── Persistance dans le workspace ────────────────────────────────────────────


def _chemin(mission_id: str):
    from app.services.mission_workspace import ensure_workspace

    return ensure_workspace(mission_id) / _FICHIER


def lire(mission_id: str) -> Optional[Outillage]:
    try:
        brut = json.loads(_chemin(mission_id).read_text(encoding="utf-8"))
        return Outillage(
            familles=list(brut.get("familles") or []),
            outils=list(brut.get("outils") or []),
            choisis=list(brut.get("choisis") or []),
        )
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 — un fichier abîmé vaut « pas de sélection »
        logger.warning("outillage %s : fichier illisible (%s)", mission_id[:8], exc)
        return None


def ecrire(mission_id: str, outillage: Outillage) -> None:
    _chemin(mission_id).write_text(
        json.dumps(asdict(outillage), ensure_ascii=False, indent=1), encoding="utf-8",
    )


async def outillage_de_la_mission(
    mission_id: str, goal: str, catalogue: Sequence[Any],
) -> Optional[list[str]]:
    """Les noms d'outils à brancher pour cette mission, ou ``None`` = tout.

    Choisis au premier appel et écrits dans le workspace ; relus ensuite.
    Le carnet reçoit la ligne de choix : Franck doit pouvoir voir POURQUOI un
    outil manque avant d'accuser le modèle.
    """
    existant = lire(mission_id)
    if existant is not None:
        return existant.outils or None

    try:
        choix = await choisir_l_outillage(goal, catalogue)
    except Exception as exc:  # noqa: BLE001 — échouer OUVERT : tout le catalogue
        logger.warning("outillage %s : sélection en échec (%s) — catalogue complet", mission_id[:8], exc)
        return None
    if choix is None:
        logger.info("outillage %s : le sélecteur n'a pas tranché — catalogue complet", mission_id[:8])
        return None

    ecrire(mission_id, choix)
    logger.info(
        "outillage %s : familles %s → %d outils sur %d (choisis : %s)",
        mission_id[:8], choix.familles, len(choix.outils), len(catalogue), choix.choisis,
    )
    try:
        from app.services.mission_workspace import carnet_append_section

        carnet_append_section(
            mission_id, "Outils",
            f"Familles retenues : {', '.join(choix.familles)} — "
            f"{len(choix.outils)} outils sur {len(catalogue)}. "
            f"`find_tool` ouvre le reste du catalogue.",
        )
    except Exception as exc:  # noqa: BLE001 — le carnet n'est pas bloquant
        logger.debug("outillage %s : carnet non écrit (%s)", mission_id[:8], exc)
    return choix.outils


def elargir(mission_id: str, decouverts: Sequence[str], catalogue: Sequence[Any]) -> list[str]:
    """Un outil découvert par ``find_tool`` entre avec toute sa famille, pour
    le reste de la mission. Rend la liste à brancher désormais."""
    existant = lire(mission_id)
    if existant is None:
        return []
    familles = set(existant.familles) | {famille(n) for n in decouverts if n}
    if familles == set(existant.familles):
        return existant.outils
    nouveau = Outillage(
        familles=sorted(familles),
        outils=_outils_des_familles(familles, catalogue),
        choisis=existant.choisis,
    )
    ecrire(mission_id, nouveau)
    logger.info(
        "outillage %s : élargi par find_tool à %s (%d outils)",
        mission_id[:8], nouveau.familles, len(nouveau.outils),
    )
    return nouveau.outils


__all__ = [
    "FAMILLES_NOYAU",
    "NOYAU_MISSION",
    "Outillage",
    "choisir_l_outillage",
    "elargir",
    "famille",
    "lire",
    "outillage_de_la_mission",
]
