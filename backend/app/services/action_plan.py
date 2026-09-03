# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/action_plan.py
# @brief      ActionPlan canonique + empreinte — « l'approuvé == l'exécuté ».
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Plan d'action canonique + empreinte (P1/J2).

Avant une approbation, on normalise l'action complète en un objet stable et on
en calcule une **empreinte** (sha256). L'approbation est liée à cette empreinte ;
juste avant l'exécution, on re-vérifie que l'action est restée identique. Toute
divergence force une nouvelle approbation (fail-closed).

Surface couverte par l'empreinte = ce que l'utilisateur VOIT et approuve : le
nom de la capacité, sa version, les arguments **affichés** (``display_args``,
calculés AVANT la résolution ``vault://`` → l'empreinte ne contient jamais de
secret en clair), les effets déclarés par le manifeste, et l'utilisateur.

⚠️ L'objet ``ActionPlan`` peut contenir de la PII (un destinataire, un corps de
message) dans ``arguments`` : il vit en mémoire, **on ne logge que l'empreinte**
(un hash), jamais le plan brut. L'empreinte alimente aussi les clés
d'idempotence (J3) et la corrélation des événements (J4).
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from pydantic import BaseModel, Field


class ActionPlan(BaseModel):
    capability_id: str
    version: int = 1
    arguments: dict = Field(default_factory=dict)   # = display_args (sans creds/secret)
    effects: list[str] = Field(default_factory=list)
    user_id: str = ""
    conversation_id: Optional[str] = None


def build_action_plan(
    tool_name: str,
    display_args: dict,
    user_id: str,
    conversation_id: Optional[str] = None,
) -> ActionPlan:
    """Construit le plan canonique d'une action, en lisant le manifeste."""
    from app.services.capability_manifest import get_manifest

    manifest = get_manifest(tool_name)
    return ActionPlan(
        capability_id=tool_name,
        version=manifest.version,
        arguments=dict(display_args or {}),
        effects=sorted(e.value for e in manifest.effects),
        user_id=user_id or "",
        conversation_id=conversation_id,
    )


def fingerprint(plan: ActionPlan) -> str:
    """Empreinte stable de l'action approuvée/à exécuter.

    Indépendante de l'ordre des clés (``sort_keys``). Lie l'action à son
    auteur (``user_id``) — un plan approuvé pour un utilisateur ne peut pas
    être exécuté pour un autre. Ne dépend PAS de la conversation."""
    payload = json.dumps(
        {
            "capability_id": plan.capability_id,
            "version": plan.version,
            "arguments": plan.arguments,
            "effects": sorted(plan.effects),
            "user_id": plan.user_id,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,   # filet pour un argument non sérialisable
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify(approved_fingerprint: str, current_plan: ActionPlan) -> bool:
    """True si l'action courante correspond exactement à celle approuvée."""
    return bool(approved_fingerprint) and approved_fingerprint == fingerprint(current_plan)
