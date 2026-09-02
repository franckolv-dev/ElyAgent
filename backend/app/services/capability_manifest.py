# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/capability_manifest.py
# @brief      CapabilityManifest — fiche d'identité commune de toute capacité.
# @license    Elastic License 2.0
# =============================================================================
"""Manifeste de capacité — le premier contrat du substrat de confiance (P1/J1).

Une *capacité* (outil interne, outil MCP, plus tard plugin/nœud) est décrite
par un descripteur déclaratif commun : ce qu'elle lit, ce qu'elle change, si
c'est réversible, et quelle approbation elle exige. Le moteur de politique
(le gate HITL de ``tool_node``) lit ce manifeste **au lieu** de s'appuyer sur
des ensembles ad-hoc et un scan de mots-clés dispersés.

Stratégie V1 (cf. cadrage §6) : **dérivation à la volée + surcharges en code**,
zéro migration. Un manifeste par défaut est déduit des signaux existants
(``ALWAYS_CRITICAL_TOOLS``, préfixe ``mcp__``) ; quelques outils sensibles ont
une surcharge explicite (effets, compensation, permissions).

INVARIANT : derrière le flag ``trust_substrate_enabled`` (OFF par défaut), la
décision HITL dérivée doit être **identique** au comportement actuel pour tous
les outils connus — ce module ne change pas la sécurité, il l'unifie.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel, Field


class Effect(str, Enum):
    READ = "read"                          # lecture, aucun effet de bord
    LOCAL_ONLY = "local_only"              # effet local à la machine
    EXTERNAL_MUTATION = "external_mutation"  # modifie une ressource externe
    DESTRUCTIVE = "destructive"           # suppression / irréversible sans compensation
    COMMS_EXTERNAL = "comms_external"     # communication vers un tiers (mail, message)


class Approval(str, Enum):
    ALWAYS = "always"          # toujours une confirmation humaine
    RISK_BASED = "risk_based"  # confirmation selon le risque / contenu
    NEVER = "never"            # jamais (lecture sûre)


class Idempotency(str, Enum):
    SUPPORTED = "supported"
    NONE = "none"


class CapabilityManifest(BaseModel):
    """Descripteur déclaratif d'une capacité (cf. cadrage §4.1)."""

    id: str                                   # nom d'outil (local_name pour MCP)
    origin: str = "builtin"                   # builtin | mcp | plugin | node | learned
    version: int = 1
    effects: list[Effect] = Field(default_factory=list)
    data_reads: list[str] = Field(default_factory=list)
    data_writes: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    approval: Approval = Approval.RISK_BASED
    idempotency: Idempotency = Idempotency.NONE
    compensation: Optional[str] = None        # référence d'une compensation (J2+/Reversible Journal)
    runtime: str = "backend"                  # backend | sandbox | node | remote
    observability: str = "full"
    # True = dérivé automatiquement des signaux existants ;
    # False = surcharge explicite et auditée.
    derived: bool = True


# ── Surcharges explicites (2-3 outils sensibles, cf. cadrage §6 Q3) ──────────
# On documente finement les effets/compensation/permissions là où ça compte le
# plus. Les valeurs d'``approval`` restent alignées sur le comportement actuel
# (ces deux outils sont déjà dans ALWAYS_CRITICAL_TOOLS).
_OVERRIDES: dict[str, CapabilityManifest] = {
    "drive_delete_file": CapabilityManifest(
        id="drive_delete_file", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION, Effect.DESTRUCTIVE],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.ALWAYS,
        idempotency=Idempotency.NONE,
        compensation="restore_from_trash",
        derived=False,
    ),
    "gmail_send_email": CapabilityManifest(
        id="gmail_send_email", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION, Effect.COMMS_EXTERNAL],
        data_writes=["sent_email"],
        permissions=["google.gmail.send"],
        approval=Approval.ALWAYS,
        idempotency=Idempotency.NONE,   # ré-envoyer = nuisible → pas de retry aveugle
        compensation=None,              # un mail envoyé ne se « dé-supprime » pas
        derived=False,
    ),
    # Réversibles par SNAPSHOT (J3) — non destructifs, approbation INCHANGÉE
    # (risk_based, comme la dérivation) ; on ajoute juste la compensation.
    "drive_rename_file": CapabilityManifest(
        id="drive_rename_file", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        compensation="restore_name",       # restaure l'ancien nom (snapshot pré-exéc)
        derived=False,
    ),
    "drive_move_file": CapabilityManifest(
        id="drive_move_file", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        compensation="restore_parents",    # restaure les anciens parents (snapshot)
        derived=False,
    ),
    # ── « Annuler partout » (audit du 02/09/2026) ───────────────────────────
    # INVARIANT PRÉSERVÉ : aucune de ces surcharges ne change l'approbation.
    # ``gmail_trash_emails`` est déjà dans ALWAYS_CRITICAL_TOOLS (→ ALWAYS) ;
    # toutes les autres restent sur ce que la dérivation donnait (RISK_BASED).
    # On n'ajoute qu'une chose : de quoi défaire.
    #
    # ⚠️ « compensation déclarée » ne veut pas dire « annulation garantie ». La
    # fenêtre dure sept jours, et trois de ces compensations REFUSENT de
    # s'exécuter si la cible a changé depuis (libellé qui classe des messages,
    # événement qui a gagné des invités, note écrite depuis) : le revert lève
    # alors ``CompensationRefused`` et l'entrée passe en ``revert_failed``.
    # Toute surface qui affiche « annulable » doit dire « annulable, sauf si… ».
    "gmail_trash_emails": CapabilityManifest(
        id="gmail_trash_emails", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION, Effect.DESTRUCTIVE],
        data_writes=["remote_email"],
        permissions=["google.gmail.modify"],
        approval=Approval.ALWAYS,
        compensation="untrash_messages",   # la corbeille Gmail EST le snapshot
        derived=False,
    ),
    "gmail_create_label": CapabilityManifest(
        id="gmail_create_label", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["gmail_label"],
        permissions=["google.gmail.labels"],
        approval=Approval.RISK_BASED,
        compensation="delete_created_label",
        derived=False,
    ),
    "calendar_create_event": CapabilityManifest(
        id="calendar_create_event", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["calendar_event"],
        permissions=["google.calendar.events"],
        approval=Approval.RISK_BASED,
        compensation="delete_created_event",
        derived=False,
    ),
    "drive_create_file": CapabilityManifest(
        id="drive_create_file", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        compensation="trash_created_file",
        derived=False,
    ),
    "drive_create_folder": CapabilityManifest(
        id="drive_create_folder", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        # ⚠️ Pas d'`idempotency` ici, bien que l'outil réutilise un dossier de
        # même nom : la déclarer ferait rejouer un résultat en CACHE au lieu
        # d'exécuter l'outil (cf. idempotency_store). Ce lot n'ajoute que de
        # quoi défaire, il ne touche pas à l'exécution.
        compensation="trash_created_folder",
        derived=False,
    ),
    "drive_upload_local_file": CapabilityManifest(
        id="drive_upload_local_file", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        compensation="trash_created_file",
        derived=False,
    ),
    "drive_copy_file": CapabilityManifest(
        id="drive_copy_file", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        compensation="trash_created_file",   # la COPIE, jamais l'original
        derived=False,
    ),
    "sheets_create_spreadsheet": CapabilityManifest(
        id="sheets_create_spreadsheet", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        compensation="trash_created_file",
        derived=False,
    ),
    "docs_create_document": CapabilityManifest(
        id="docs_create_document", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["remote_file"],
        permissions=["google.drive.write"],
        approval=Approval.RISK_BASED,
        compensation="trash_created_file",
        derived=False,
    ),
    "tasks_create": CapabilityManifest(
        id="tasks_create", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["task"],
        permissions=["google.tasks.write"],
        approval=Approval.RISK_BASED,
        compensation="delete_created_task",
        derived=False,
    ),
    "tasks_complete": CapabilityManifest(
        id="tasks_complete", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["task"],
        permissions=["google.tasks.write"],
        approval=Approval.RISK_BASED,
        compensation="restore_task_status",   # instantané : le statut d'avant
        derived=False,
    ),
    "contacts_create": CapabilityManifest(
        id="contacts_create", origin="builtin",
        effects=[Effect.EXTERNAL_MUTATION],
        data_writes=["contact"],
        permissions=["google.contacts.write"],
        approval=Approval.RISK_BASED,
        compensation="delete_created_contact",
        derived=False,
    ),
    "notes_create": CapabilityManifest(
        id="notes_create", origin="builtin",
        effects=[Effect.LOCAL_ONLY],          # la base d'Ely, rien chez un tiers
        data_writes=["local_note"],
        approval=Approval.RISK_BASED,
        compensation="delete_created_note",
        derived=False,
    ),
    # Témoin de lecture sûre : aucun effet de bord, jamais de confirmation.
    "web_search": CapabilityManifest(
        id="web_search", origin="builtin",
        effects=[Effect.READ],
        data_reads=["public_web"],
        approval=Approval.NEVER,
        idempotency=Idempotency.SUPPORTED,
        derived=False,
    ),
}

# Heuristique descriptive d'effets pour les outils ALWAYS dérivés.
_DESTRUCTIVE_HINTS = ("delete", "trash", "remove", "drop", "empty", "destroy")
_COMMS_HINTS = ("send", "reply", "message", "publish", "post")


def _always_effects(tool_name: str) -> list[Effect]:
    name = tool_name.lower()
    effects = [Effect.EXTERNAL_MUTATION]
    if any(h in name for h in _DESTRUCTIVE_HINTS):
        effects.append(Effect.DESTRUCTIVE)
    if any(h in name for h in _COMMS_HINTS):
        effects.append(Effect.COMMS_EXTERNAL)
    return effects


def _derive(tool_name: str) -> CapabilityManifest:
    """Manifeste par défaut déduit des signaux existants.

    Fidèle au comportement actuel : un outil de ``ALWAYS_CRITICAL_TOOLS`` →
    ``approval=always`` ; tout le reste → ``risk_based`` (le gate appliquera le
    même ``is_critical`` qu'aujourd'hui)."""
    from app.services.security_filter import ALWAYS_CRITICAL_TOOLS

    origin = "mcp" if tool_name.startswith("mcp__") else "builtin"
    if tool_name in ALWAYS_CRITICAL_TOOLS:
        return CapabilityManifest(
            id=tool_name, origin=origin,
            effects=_always_effects(tool_name),
            approval=Approval.ALWAYS,
            runtime=("remote" if origin == "mcp" else "backend"),
            derived=True,
        )
    return CapabilityManifest(
        id=tool_name, origin=origin,
        approval=Approval.RISK_BASED,
        runtime=("remote" if origin == "mcp" else "backend"),
        derived=True,
    )


def get_manifest(tool_name: str) -> CapabilityManifest:
    """Manifeste d'un outil : surcharge explicite si présente, sinon dérivé."""
    override = _OVERRIDES.get(tool_name)
    return override if override is not None else _derive(tool_name)


def manifest_requires_hitl(
    tool_name: str,
    crit_desc: str,
    is_critical: Callable[[str], bool],
) -> bool:
    """Décision HITL de base, pilotée par le manifeste (consommée par tool_node).

    - ``approval=always`` → toujours confirmer ;
    - ``approval=never``  → jamais ;
    - ``approval=risk_based`` → confirmer si l'analyse de risque le dit
      (``is_critical``), soit exactement la règle actuelle.

    Pour un outil connu, le résultat est identique à
    ``(tool_name in ALWAYS_CRITICAL_TOOLS) or is_critical(desc)``."""
    manifest = get_manifest(tool_name)
    if manifest.approval is Approval.ALWAYS:
        return True
    if manifest.approval is Approval.NEVER:
        return False
    return bool(is_critical(crit_desc))
