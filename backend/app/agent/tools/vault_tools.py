# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/vault_tools.py
# @brief      Le coffre vu par le modèle : des étiquettes, jamais des valeurs.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Lot 3 (07/09/2026) — créer un compte pour l'utilisateur, sous son accord.

Le coffre (AES-GCM, Argon2id) existait, et la passerelle résolvait déjà toute
valeur ``vault://label`` dans les arguments d'un outil. Mais le modèle ne
pouvait ni savoir quelles étiquettes existent, ni en créer une : « utiliser
mes identifiants » n'avait aucun chemin, et « crée le compte toi-même » non
plus — un mot de passe ne doit JAMAIS transiter par le prompt.

Deux outils, et un invariant : **aucune valeur ne sort du coffre par ici**.
- ``vault_list_labels`` rend les étiquettes et leurs mémos ;
- ``vault_generate_secret`` fabrique un mot de passe fort, le range sous une
  étiquette, et ne rend que la référence ``vault://label`` à passer à
  ``browser_fill`` (ou tout autre outil) — la passerelle résout, puis
  remasque le résultat.

Le coffre se déverrouille avec le mot de passe maître de l'utilisateur, en
RAM, et se reverrouille seul après 30 min d'inactivité. Verrouillé, ces
outils le disent et renvoient vers ``ask_user`` : une mission ne peut pas
l'ouvrir, seul l'utilisateur le peut (Réglages › Mon compte › Coffre).
"""
from __future__ import annotations

import logging
import re
import secrets
import string
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)

# Même règle que l'API du coffre (`StoreSecretRequest.label`).
_ETIQUETTE = re.compile(r"^[a-zA-Z0-9_\-.]{1,120}$")
_ALPHABET = string.ascii_letters + string.digits + "!#$%&*+-=?@^_~"

_VERROUILLE = (
    "⛔ Coffre verrouillé. Seul l'utilisateur peut le déverrouiller "
    "(Réglages › Mon compte › Coffre). En mission : appelle ask_user pour le "
    "lui demander, puis reprends."
)


def etiquette_valide(label: str) -> bool:
    return bool(_ETIQUETTE.match(label or ""))


def _mot_de_passe(longueur: int = 24) -> str:
    """Un mot de passe fort : chaque classe de caractères y figure."""
    while True:
        mdp = "".join(secrets.choice(_ALPHABET) for _ in range(longueur))
        if (any(c.islower() for c in mdp) and any(c.isupper() for c in mdp)
                and any(c.isdigit() for c in mdp)
                and any(c in string.punctuation for c in mdp)):
            return mdp


@register(
    domain=Domain.UNIVERSAL,
    skill_name="vault_labels",
    skill_display_name="Coffre — étiquettes",
    skill_description="Lister les secrets du coffre par leur étiquette, sans jamais lire leur valeur.",
    skill_icon="🔐",
)
@tool
async def vault_list_labels(user_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Liste les secrets du coffre de l'utilisateur : étiquettes et mémos, JAMAIS les valeurs.

    Sers-t'en avant de te connecter quelque part : si un secret existe pour
    ce site, passe `vault://<étiquette>` comme valeur à `browser_fill` (ou à
    tout outil) — la passerelle le remplace par la vraie valeur, que tu ne
    vois jamais. Le mémo dit à quoi sert le secret (site, identifiant).
    """
    from app.services.vault_service import get_vault_service

    vault = get_vault_service()
    entrees = await vault.list_secrets(user_id)
    etat = _VERROUILLE if vault.is_locked(user_id) else "Coffre déverrouillé."
    if not entrees:
        return (
            f"Le coffre ne contient aucun secret. {etat}\nPour un nouveau "
            "compte, fabrique le mot de passe avec vault_generate_secret."
        )
    lignes = [
        f"- {e['label']}" + (f" — {e['hint']}" if e.get("hint") else "")
        for e in entrees
    ]
    return (
        f"{len(entrees)} secret(s) dans le coffre :\n" + "\n".join(lignes)
        + f"\n{etat}\nPour en utiliser un : passe « vault://{entrees[0]['label']} » "
        "(l'étiquette) comme valeur — jamais la valeur elle-même."
    )


@register(
    domain=Domain.UNIVERSAL,
    skill_name="vault_generate",
    skill_display_name="Coffre — nouveau secret",
    skill_description="Fabriquer un mot de passe fort et le ranger dans le coffre, sans jamais le lire.",
    skill_icon="🔐",
)
@tool
async def vault_generate_secret(
    label: str,
    hint: str = "",
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Fabrique un mot de passe fort, le range dans le coffre sous `label`, et rend sa référence.

    Pour créer un compte pour l'utilisateur : appelle-le, puis passe la
    référence rendue (`vault://<label>`) comme valeur du champ mot de passe
    à `browser_fill`. Tu ne vois JAMAIS le mot de passe, et tu ne dois
    jamais en demander un en clair à l'utilisateur. Refuse d'écraser une
    étiquette existante.

    Args:
        label: Étiquette du secret, lettres/chiffres/`-`/`_`/`.` (ex. `compte-senscritique`).
        hint: Mémo en clair pour l'utilisateur : le site et l'identifiant du compte.
    """
    from app.services.vault_service import get_vault_service

    if not etiquette_valide(label):
        return "Étiquette refusée : lettres, chiffres, « - », « _ » et « . » seulement (120 max)."
    vault = get_vault_service()
    if vault.is_locked(user_id):
        return _VERROUILLE
    if any(e["label"] == label for e in await vault.list_secrets(user_id)):
        return (
            f"Le secret « {label} » existe déjà : utilise « vault://{label} » tel "
            "quel, ou choisis une autre étiquette."
        )
    await vault.store_secret(user_id, label, _mot_de_passe(), (hint or "").strip()[:255] or None)
    logger.info("coffre : secret « %s » généré pour %s", label, (user_id or "")[:8])
    return (
        f"Mot de passe généré et rangé sous « {label} ». Référence à passer comme "
        f"valeur : vault://{label} — ne demande jamais la valeur, la passerelle la "
        "remplace au moment de l'appel."
    )
