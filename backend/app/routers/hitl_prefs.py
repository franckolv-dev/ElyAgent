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

from fastapi import APIRouter, Depends, HTTPException, Header
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
# Bilingual (mai 2026 — bug rapporté : en mode UI anglais, les descriptions
# restaient en français parce qu'elles étaient hardcodées côté backend).
# Sélection FR/EN pilotée par le header Accept-Language envoyé par le frontend
# (next-intl le set automatiquement via le middleware locale).
# Keys must match tool names; missing keys fall back to the tool name itself.
_TOOL_DESCRIPTIONS_FR: dict[str, str] = {
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

_TOOL_DESCRIPTIONS_EN: dict[str, str] = {
    "gmail_send_email": "Send an email via Gmail",
    "gmail_reply_email": "Reply to an email via Gmail",
    "gmail_send_with_attachment": "Send an email with an attachment",
    "gmail_create_draft": "Create a Gmail draft",
    "gmail_batch_modify": "Batch-modify up to 1000 emails (label/archive/trash)",
    "gmail_trash_emails": "Move emails to Trash",
    "gmail_move_emails": "Move emails between labels",
    "gmail_update_settings": "Update Gmail settings (signature, vacation, filters, forwarding)",
    "calendar_create_event": "Create an event in Google Calendar",
    "calendar_update_event": "Update a Calendar event",
    "calendar_delete_event": "Delete a Calendar event",
    "calendar_quick_add": "Create a Calendar event via natural language",
    "calendar_create_meet_event": "Create a Meet event (video call + recurrence)",
    "drive_create_folder": "Create a Google Drive folder",
    "drive_create_file": "Create a Google Drive file",
    "drive_update_file": "Update an existing Drive file",
    "drive_delete_file": "Delete a Drive file",
    "drive_move_file": "Move a Drive file",
    "drive_share_file": "Share a Drive file (external permissions)",
    "docs_create_document": "Create a Google Doc",
    "docs_append_text": "Append text to a Google Doc",
    "docs_replace_text": "Find & replace inside a Google Doc",
    "docs_batch_update": "Batch updates on a Google Doc",
    "sheets_create_spreadsheet": "Create a Google Sheets spreadsheet",
    "sheets_update_cells": "Update cells in Sheets",
    "sheets_delete_rows": "Delete rows in Sheets",
    "sheets_batch_update": "Batch updates on Sheets (sort, format, validation)",
    "tasks_create": "Create a Google Tasks task",
    "tasks_complete": "Mark a task as completed",
    "tasks_delete": "Delete a Google Tasks task",
    "contacts_create": "Create a Google Contact",
    "contacts_update": "Update a Google Contact",
    "contacts_delete": "Delete a Google Contact",
    "contacts_batch_operations": "Batch operations on contacts (up to 200)",
    "ssh_execute": "Run an SSH command on a server",
    "desktop_write_file": "Write a file to the local disk",
    "desktop_delete_file": "Delete a file from the local disk",
    "desktop_move_file": "Move a file on the local disk",
    "vault_unlock": "Unlock the secrets vault",
    "vault_set_secret": "Store a secret in the vault",
}


def _pick_lang(accept_language: str | None) -> dict[str, str]:
    """Return the right description map based on the Accept-Language header.

    Accept-Language est de la forme « fr-FR,fr;q=0.9,en;q=0.8 ». On fait
    matching simple : si le tag commence par « en » → anglais, sinon FR par
    défaut (notre langue principale historique).
    """
    if accept_language and accept_language.strip().lower().startswith("en"):
        return _TOOL_DESCRIPTIONS_EN
    return _TOOL_DESCRIPTIONS_FR


@router.get("/preferences", response_model=list[HitlPrefOut])
async def list_preferences(
    current_user: User = Depends(get_current_user),
    accept_language: str | None = Header(default=None),
) -> list[HitlPrefOut]:
    """Return one entry per tool in ALWAYS_CRITICAL_TOOLS with its HITL state.

    The default is "HITL on" — overrides come from ``hitl_preferences`` rows.
    Tools listed in ``LOCKED_HITL_TOOLS`` are always returned with
    ``requires_confirmation=true, locked=true`` regardless of the user
    override (defence-in-depth — the resolver also enforces this).

    Descriptions sont localisées via le header ``Accept-Language`` (FR par
    défaut, EN si commence par « en »).
    """
    descriptions = _pick_lang(accept_language)

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
            description=descriptions.get(tool_name),
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


# ──────────────────────────────────────────────────────────────────────────────
# HITL preferred channel
# ──────────────────────────────────────────────────────────────────────────────

# Whitelist of accepted channel values. Keep in sync with the frontend
# Settings UI dropdown and the dispatch logic in hitl_manager.request_validation.
_ALLOWED_CHANNELS = frozenset({
    "ely_android",
    "ntfy",
    "telegram",
    "discord",
    "slack",
    "web_only",
    "all",
})


class HitlChannelOut(BaseModel):
    preferred_channel: str
    available_channels: list[dict]


class HitlChannelPatch(BaseModel):
    preferred_channel: str = Field(..., description="One of: ely_android, ntfy, telegram, discord, slack, web_only, all.")


@router.get("/channel", response_model=HitlChannelOut)
async def get_hitl_channel(current_user: User = Depends(get_current_user)) -> HitlChannelOut:
    """Return the user's preferred HITL channel + which channels are available
    for them (linked / configured).

    Used by the Settings UI to populate the dropdown with grayed-out options
    for unlinked channels.
    """
    import os
    pref = (current_user.hitl_preferred_channel or "all").strip().lower()
    if pref not in _ALLOWED_CHANNELS:
        pref = "all"

    # Resolve availability per channel
    has_telegram = bool(getattr(current_user, "telegram_id", None))
    has_fcm = bool(getattr(current_user, "fcm_token", None))
    has_discord = bool(getattr(current_user, "discord_id", None))
    has_slack = bool(getattr(current_user, "slack_id", None))

    # ntfy is configured server-side (env or DB)
    from app.services.system_config import get_config
    ntfy_url = await get_config("ntfy_url", "") or os.environ.get("NTFY_URL", "")
    has_ntfy = bool(ntfy_url)

    available = [
        {"value": "ely_android", "label": "App ELY Android", "available": has_fcm,    "icon": "📱"},
        {"value": "ntfy",        "label": "ntfy (push)",     "available": has_ntfy,   "icon": "🔔"},
        {"value": "telegram",    "label": "Telegram",        "available": has_telegram, "icon": "✈️"},
        {"value": "discord",     "label": "Discord",         "available": has_discord,  "icon": "💜"},
        {"value": "slack",       "label": "Slack",           "available": has_slack,    "icon": "🟣"},
        {"value": "web_only",    "label": "Web seulement",   "available": True,         "icon": "🌐"},
        {"value": "all",         "label": "Tous (broadcast)","available": True,         "icon": "📢"},
    ]
    return HitlChannelOut(preferred_channel=pref, available_channels=available)


@router.patch("/channel", response_model=HitlChannelOut)
async def patch_hitl_channel(
    body: HitlChannelPatch,
    current_user: User = Depends(get_current_user),
) -> HitlChannelOut:
    """Set the user's preferred HITL notification channel."""
    val = (body.preferred_channel or "all").strip().lower()
    if val not in _ALLOWED_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"Canal '{body.preferred_channel}' invalide. Valeurs : {sorted(_ALLOWED_CHANNELS)}.",
        )

    async with async_session() as db:
        u = await db.get(User, current_user.id)
        if u is None:
            raise HTTPException(status_code=404, detail="User not found")
        # Store None for "all" (legacy default behaviour) so a freshly migrated
        # column reads as None and we don't clutter the DB with default values.
        u.hitl_preferred_channel = None if val == "all" else val
        await db.commit()
        await db.refresh(u)

    # Re-use the GET to return the same shape (with availability flags)
    return await get_hitl_channel(u)
