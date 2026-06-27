# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/reversible_actions.py
# @brief      API /api/me/reversible-actions — lister et annuler ses actions.
# @license    Elastic License 2.0
# =============================================================================
"""Surface HTTP du Reversible Action Journal (substrat / J2).

Endpoints scopés à l'utilisateur courant (``get_current_user``) ; toute la
logique (fail-closed, propriété, expiration, idempotence) vit dans
``journal_service``. Ce routeur ne fait que mapper les raisons d'échec sur des
codes HTTP — et masque l'existence d'une action d'un autre utilisateur (404).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, require_admin
from app.models.user import User
from app.services import journal_service

router = APIRouter(prefix="/api/me/reversible-actions", tags=["trust"])


class ReversibleActionOut(BaseModel):
    id: str
    capability_id: str
    compensation: str
    created_at: str | None = None
    expires_at: str


class UndoResult(BaseModel):
    ok: bool
    capability_id: str | None = None
    # (J4) None si pas de vérification possible ; True/False = annulation confirmée ou non.
    verified: bool | None = None


@router.get("", response_model=list[ReversibleActionOut])
async def list_my_reversible_actions(
    user: User = Depends(get_current_user),
) -> list[ReversibleActionOut]:
    """Actions encore annulables de l'utilisateur courant (plus récentes d'abord)."""
    items = await journal_service.list_reversible(str(user.id))
    return [ReversibleActionOut(**it) for it in items]


@router.post("/{record_id}/undo", response_model=UndoResult)
async def undo_my_action(
    record_id: str,
    user: User = Depends(get_current_user),
) -> UndoResult:
    """Annule une action de l'utilisateur courant. Fail-closed côté service."""
    res = await journal_service.undo(record_id, str(user.id))
    if res.get("ok"):
        return UndoResult(ok=True, capability_id=res.get("capability_id"),
                          verified=res.get("verified"))
    base = (res.get("reason") or "").split(":")[0]
    # 404 (pas 403) pour ne pas révéler l'existence d'une action d'autrui.
    if base in ("not_found", "forbidden"):
        raise HTTPException(status_code=404, detail="Action introuvable.")
    # Non annulable : expirée, déjà annulée, compensation inconnue, échec.
    raise HTTPException(status_code=409, detail=res.get("reason") or "annulation impossible")


# ── Métriques (admin) ────────────────────────────────────────────────────
# (J4) Compteurs par statut + taux de succès d'annulation. Réservé admin :
# c'est une vue d'instance, pas une donnée par-utilisateur.
admin_router = APIRouter(prefix="/admin/reversible-actions", tags=["trust"])


@admin_router.get("/stats")
async def reversible_action_stats(_: User = Depends(require_admin)) -> dict:
    """Métriques du Reversible Journal (vue instance)."""
    return await journal_service.stats()
