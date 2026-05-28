# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/vault.py
# @brief      Vault API — manage encrypted secrets
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Vault API — manage encrypted secrets.

All routes require authentication.  Secret values are NEVER returned by the
API after storage (write-only from the API perspective).

Endpoints:
  GET    /api/vault/status              — vault locked/unlocked status
  POST   /api/vault/unlock              — unlock with master password
  POST   /api/vault/lock                — lock the vault
  GET    /api/vault/secrets             — list labels + hints (no values)
  POST   /api/vault/secrets             — store a secret
  DELETE /api/vault/secrets/{label}     — delete a secret
  POST   /api/vault/change-password     — re-encrypt all secrets
  GET    /api/vault/export              — export encrypted JSON backup
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.vault_service import get_vault_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vault", tags=["vault"])


# ── Request / response schemas ─────────────────────────────────────────────────

class UnlockRequest(BaseModel):
    master_password: str = Field(..., min_length=8)


class StoreSecretRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=120,
                       pattern=r"^[a-zA-Z0-9_\-\.]+$",
                       description="Alphanumeric identifier, e.g. 'vps_root_password'")
    value: str = Field(..., min_length=1)
    hint : str = Field("", max_length=255, description="Unencrypted memo (optional)")


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/status")
async def vault_status(current_user: User = Depends(get_current_user)):
    """Return whether the vault is currently unlocked."""
    vault = get_vault_service()
    return {
        "locked": vault.is_locked(current_user.id),
        "user_id": current_user.id,
    }


@router.post("/unlock")
async def unlock_vault(
    req: UnlockRequest,
    current_user: User = Depends(get_current_user),
):
    """Unlock the vault (or initialise it on first use).

    The master password is never stored — only the derived AES key lives
    in RAM during the session.
    """
    vault = get_vault_service()
    success = await vault.unlock_vault(current_user.id, req.master_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong master password",
        )
    return {"ok": True, "message": "Vault unlocked"}


@router.post("/lock")
async def lock_vault(current_user: User = Depends(get_current_user)):
    """Lock the vault (erases the in-memory key)."""
    await get_vault_service().lock_vault(current_user.id)
    return {"ok": True, "message": "Vault locked"}


@router.get("/secrets")
async def list_secrets(current_user: User = Depends(get_current_user)):
    """List all secret labels and hints (values are never returned)."""
    return await get_vault_service().list_secrets(current_user.id)


@router.post("/secrets", status_code=status.HTTP_201_CREATED)
async def store_secret(
    req: StoreSecretRequest,
    current_user: User = Depends(get_current_user),
):
    """Encrypt and store a secret. Creates or replaces the entry for *label*."""
    vault = get_vault_service()
    if vault.is_locked(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vault is locked — unlock it first",
        )
    await vault.store_secret(current_user.id, req.label, req.value, req.hint or None)
    return {"ok": True, "label": req.label}


@router.delete("/secrets/{label}")
async def delete_secret(
    label: str,
    current_user: User = Depends(get_current_user),
):
    """Delete a secret by label."""
    vault = get_vault_service()
    if vault.is_locked(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vault is locked — unlock it first",
        )
    deleted = await vault.delete_secret(current_user.id, label)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No secret with label '{label}'")
    return {"ok": True, "label": label}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
):
    """Change the master password (re-encrypts all secrets)."""
    vault = get_vault_service()
    success = await vault.change_master_password(
        current_user.id, req.old_password, req.new_password
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong current master password",
        )
    return {"ok": True, "message": "Master password changed — all secrets re-encrypted"}


@router.get("/export")
async def export_vault(current_user: User = Depends(get_current_user)):
    """Export the encrypted vault as JSON.

    The export is still protected by the master password — it cannot be
    decrypted without it.  Safe to store as a backup.
    """
    vault = get_vault_service()
    if vault.is_locked(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vault is locked — unlock it first",
        )
    return await vault.export_vault(current_user.id)
