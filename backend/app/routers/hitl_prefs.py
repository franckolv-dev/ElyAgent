# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/hitl_prefs.py
# @brief      REST API for per-user HITL preferences
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""REST API for per-user HITL preferences.

Endpoints :
- ``GET  /hitl/preferences`` — list every critical tool with its current
  HITL state for the calling user (default = True if no override).
- ``PATCH /hitl/preferences`` — toggle HITL on/off for a specific tool.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.hitl_preference import HitlPreference
from app.models.user import User
from app.services.hitl_preferences import LOCKED_HITL_TOOLS
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS

router = APIRouter(prefix="/hitl", tags=["hitl"])


class HitlPrefOut(BaseModel):
    tool_name: str
    requires_confirmation: bool
    locked: bool = Field(
        ..., description="If true, the user CANNOT disable HITL for this tool (forced by system)."
    )
    description: str | None = Field(
        default=None, description="Short human-readable description of what the tool does."
    )


# Curated descriptions so the UI shows context next to each toggle.
# Keys must match tool names; missing keys fall back to the tool name itself.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "gmail_send_email": "Envoyer un email via Gmail",
    "gmail_reply_email": "Répondre à un email via Gmail",
    "gmail_send_with_attachment": "Envoyer un email avec pièce jointe",
    "gmail_create_draft": "Créer un brouillon Gmail",
    "gmail_batch_modify": "Modifier en lot jusqu'à 1000 emails (label/archive/trash)",
    "gmail_trash_emails": "Mettre des emails à la corbeille",
    "gmail_move_emails": "Déplacer des emails entre labels",
    "gmail_update_settings": "Modifier les réglages Gmail (signature, vacation, filtres, transfert)",
    "calendar_create_event": "Créer un événement dans Google Calendar",
    "calendar_update_event": "Modifier un événement Calendar",
    "calendar_delete_event": "Supprimer un événement Calendar",
    "calendar_quick_add": "Créer un événement Calendar via langage naturel",
    "calendar_create_meet_event": "Créer un événement Meet (visio + récurrence)",
    "drive_create_folder": "Créer un dossier Google Drive",
    "drive_create_file": "Créer un fichier Google Drive",
    "drive_update_file": "Mettre à jour un fichier Drive existant",
    "drive_delete_file": "Supprimer un fichier Drive",
    "drive_move_file": "Déplacer un fichier Drive",
    "drive_share_file": "Partager un fichier Drive (permissions externes)",
    "docs_create_document": "Créer un Google Doc",
    "docs_append_text": "Ajouter du texte à un Google Doc",
    "docs_replace_text": "Rechercher / remplacer dans un Google Doc",
    "docs_batch_update": "Modifications batch sur un Google Doc",
    "sheets_create_spreadsheet": "Créer une feuille de calcul Google Sheets",
    "sheets_update_cells": "Modifier des cellules dans Sheets",
    "sheets_delete_rows": "Supprimer des lignes dans Sheets",
    "sheets_batch_update": "Modifications batch sur Sheets (tri, format, validation)",
    "tasks_create": "Créer une tâche Google Tasks",
    "tasks_complete": "Marquer une tâche comme terminée",
    "tasks_delete": "Supprimer une tâche Google Tasks",
    "contacts_create": "Créer un contact Google",
    "contacts_update": "Modifier un contact Google",
    "contacts_delete": "Supprimer un contact Google",
    "contacts_batch_operations": "Opérations en lot sur les contacts (jusqu'à 200)",
    "ssh_execute": "Exécuter une commande SSH sur un serveur",
    "desktop_write_file": "Écrire un fichier sur le disque local",
    "desktop_delete_file": "Supprimer un fichier du disque local",
    "desktop_move_file": "Déplacer un fichier sur le disque local",
    "vault_unlock": "Déverrouiller le coffre-fort des secrets",
    "vault_set_secret": "Stocker un secret dans le coffre-fort",
}


@router.get("/preferences", response_model=list[HitlPrefOut])
async def list_preferences(current_user: User = Depends(get_current_user)) -> list[HitlPrefOut]:
    """Return one entry per tool in ALWAYS_CRITICAL_TOOLS with its HITL state.

    The default is "HITL on" — overrides come from ``hitl_preferences`` rows.
    Tools listed in ``LOCKED_HITL_TOOLS`` are always returned with
    ``requires_confirmation=true, locked=true`` regardless of the user
    override (defence-in-depth — the resolver also enforces this).
    """
    async with async_session() as db:
        rows = await db.execute(
            select(HitlPreference.tool_name, HitlPreference.requires_confirmation)
            .where(HitlPreference.user_id == current_user.id)
        )
        overrides = dict(rows.all())

    out: list[HitlPrefOut] = []
    for tool_name in sorted(ALWAYS_CRITICAL_TOOLS):
        is_locked = tool_name in LOCKED_HITL_TOOLS
        # Locked tools ignore overrides
        if is_locked:
            requires = True
        else:
            requires = bool(overrides.get(tool_name, True))
        out.append(HitlPrefOut(
            tool_name=tool_name,
            requires_confirmation=requires,
            locked=is_locked,
            description=_TOOL_DESCRIPTIONS.get(tool_name),
        ))
    return out


class HitlPrefUpdate(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=100)
    requires_confirmation: bool


@router.patch("/preferences")
async def update_preference(
    body: HitlPrefUpdate,
    current_user: User = Depends(get_current_user),
):
    """Toggle HITL for one tool. Locked tools are rejected with 400."""
    if body.tool_name in LOCKED_HITL_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tool '{body.tool_name}' is locked — HITL cannot be disabled. "
                "This protects against destructive / irreversible actions."
            ),
        )
    if body.tool_name not in ALWAYS_CRITICAL_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{body.tool_name}' is not a critical tool (HITL doesn't apply to it).",
        )

    async with async_session() as db:
        existing = await db.execute(
            select(HitlPreference).where(
                HitlPreference.user_id == current_user.id,
                HitlPreference.tool_name == body.tool_name,
            )
        )
        row = existing.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            row = HitlPreference(
                user_id=current_user.id,
                tool_name=body.tool_name,
                requires_confirmation=body.requires_confirmation,
                updated_at=now,
            )
            db.add(row)
        else:
            row.requires_confirmation = body.requires_confirmation
            row.updated_at = now
        await db.commit()

    return {
        "tool_name": body.tool_name,
        "requires_confirmation": body.requires_confirmation,
    }
