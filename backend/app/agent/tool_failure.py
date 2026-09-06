# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_failure.py
# @brief      La seule définition de « ce retour d'outil dit un échec ».
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Un outil d'Ely signale son échec en TEXTE, sans lever (« Erreur : … »).

Trois lecteurs en dépendent : la garde anti-rejeu (``replay_guard``), le
journal réversible (``journal_service``) et, depuis l'audit GPT-6 F02
(06/09/2026), la passerelle elle-même — qui comptait ces textes comme des
succès. Une seule liste de préfixes, lue partout : un outil qui change sa
formulation casse les trois d'un coup, et un test le dit.
"""
from __future__ import annotations

ECHEC_PREFIXES: tuple[str, ...] = ("erreur", "error", "échec", "echec")


def dit_un_echec(texte: object) -> bool:
    """Ce retour d'outil annonce-t-il que l'action n'a PAS abouti ?"""
    return str(texte or "").lstrip().lower().startswith(ECHEC_PREFIXES)
