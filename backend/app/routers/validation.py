# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/validation.py
# @brief      Android webhook endpoints for HITL validation
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""HITL validation webhooks.

Called by the Android app (via FCM action intents), Telegram callback
buttons, and the web UI when the user approves or denies a pending action:
  POST /validation/{action_id}/allow  → execute once
  POST /validation/{action_id}/deny   → cancel this time
  POST /validation/{action_id}/ban    → cancel + store permanent rule

The Android and web UI clients pass a JWT (Authorization header) and are
therefore authenticated via `get_current_user`.

The ntfy mobile push channel cannot attach a JWT to its action buttons,
so each action_id is also bound to a short-lived HMAC token (see
`sign_action_token` in hitl_manager). These buttons target the same paths
with an extra `?t=<token>` query string and bypass the JWT check — the
token itself proves the caller received the legitimate push notification.
"""
import hmac
import hashlib
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

from app.auth.dependencies import get_current_user, get_optional_user
from app.config import get_settings
from app.models.user import User
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager

router = APIRouter(prefix="/validation", tags=["validation"])


def sign_action_token(action_id: str) -> str:
    """HMAC-sign an action_id with the JWT secret, returning a short token
    suitable for URL query strings. The token is unique per action — it
    cannot be replayed on another action, and becomes useless once the
    pending action is cleared from memory."""
    secret = get_settings().jwt_secret_key.encode("utf-8")
    mac = hmac.new(secret, action_id.encode("utf-8"), hashlib.sha256)
    # 16 hex chars = 64-bit, enough to resist brute-forcing within the
    # HITL timeout window (a few minutes).
    return mac.hexdigest()[:16]


def _verify_action_token(action_id: str, token: str) -> bool:
    expected = sign_action_token(action_id)
    return hmac.compare_digest(expected, token)


async def _resolve(
    action_id: str,
    decision: str,
    reason: str | None,
    current_user: User | None,
    channel: str = "web",
) -> dict:
    hitl = get_hitl_manager()
    # V0-2 : le propriétaire vient de la mémoire OU de la base — sinon un
    # redémarrage transformait toute validation en attente en 404, alors que
    # la demande était encore parfaitement légitime.
    owner_id = await hitl.get_pending_owner(action_id)
    if not owner_id:
        raise HTTPException(status_code=404, detail="Action not found or already resolved")
    # Verify the action belongs to the requesting user (when authenticated).
    # When called via the signed-token path (current_user is None), the
    # token itself already binds the caller to the action_id.
    if current_user is not None and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to resolve this action")
    # Détail en mémoire, best-effort : absent après un redémarrage, et les
    # champs `tool_name`/`summary` lus plus bas n'ont jamais existé sur
    # _PendingAction (getattr → None). Conservé tel quel : le journal d'audit
    # garde exactement la forme qu'il avait.
    pending = hitl._pending.get(action_id)
    resolved = await hitl.resolve(action_id, decision, reason)
    if not resolved:
        raise HTTPException(status_code=404, detail="Action not found or already resolved")

    # Log HITL decision for dashboard analytics (non-critical, fire-and-forget)
    # ``spawn`` et non ``asyncio.create_task`` : la boucle ne garde qu'une
    # référence FAIBLE sur une tâche détachée, donc le GC pouvait l'emporter
    # en vol — la décision HITL disparaissait du tableau de bord sans trace.
    # ``spawn`` retient la tâche et journalise son exception.
    try:
        from app.services.analytics_service import log_usage
        from app.services.background_tasks import spawn
        spawn(log_usage(
            user_id=current_user.id if current_user else owner_id,
            model="",
            provider="hitl",
            input_tokens=0,
            output_tokens=0,
            hitl_decision=decision,
            hitl_action=action_id,
            channel=channel,
        ))
    except Exception:
        pass

    # Audit log permanent (mai 2026 — avant ce fix, AuditLog n'était écrit
    # QUE depuis routers/admin.py, donc Admin → Logs UI restait vide à
    # chaque chat/mission/HITL. Maintenant chaque décision HITL est
    # tracée pour traçabilité conformité GDPR/SOC2-like).
    try:
        from app.database import async_session as _async_session
        from app.models.audit import AuditLog as _AuditLog
        async with _async_session() as _db:
            _db.add(_AuditLog(
                user_id=current_user.id if current_user else owner_id,
                action=f"hitl_{decision}",  # hitl_allow / hitl_deny / hitl_ban
                tool_used=getattr(pending, "tool_name", None),
                command=(getattr(pending, "summary", None) or "")[:500],
                channel=channel,
                details=(reason or "")[:500] if reason else None,
                result_code=0 if decision == "allow" else 1,
            ))
            await _db.commit()
    except Exception as _exc:
        logger.debug("HITL audit log write failed: %s", _exc)

    return {"status": "ok", "decision": decision}


async def _resolve_with_auth_or_token(
    action_id: str,
    decision: str,
    reason: str | None,
    current_user: User | None,
    token: str | None,
    channel: str,
) -> dict:
    """Resolve the action with either JWT auth (current_user set) or a
    valid signed action token (current_user None, token validates)."""
    if token:
        if not _verify_action_token(action_id, token):
            raise HTTPException(status_code=401, detail="Invalid action token")
        return await _resolve(action_id, decision, reason, None, channel=channel)
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await _resolve(action_id, decision, reason, current_user, channel=channel)


@router.post("/{action_id}/allow")
async def allow_action(
    action_id: str,
    t: str | None = Query(default=None, description="Signed action token (ntfy channel)"),
    current_user: User | None = Depends(get_optional_user),
):
    """Authorize the action for this occurrence only. Accepts either a JWT
    (from Android/web UI) OR the signed `t` token from the ntfy push."""
    channel = "ntfy" if t else "web"
    return await _resolve_with_auth_or_token(action_id, "allow", None, current_user, t, channel)


@router.post("/{action_id}/allow_always")
async def allow_always_action(
    action_id: str,
    t: str | None = Query(default=None, description="Signed action token (ntfy channel)"),
    current_user: User | None = Depends(get_optional_user),
):
    """Authorize the action this occurrence AND mark the underlying tool as
    always-allowed for the calling user. Mirrors ``/ban`` on the deny side.

    The tool→user binding happens in ``nodes.py`` when it handles the
    ``allow_always`` decision : it upserts a HitlPreference row with
    ``requires_confirmation=False`` so subsequent invocations skip the
    HITL prompt entirely. Depuis 2026-06-19, cela vaut AUSSI pour les outils
    dangereux (``LOCKED_HITL_TOOLS``) : la préférence est désormais honorée à
    la lecture (avant, elle était écrite mais ignorée → re-demande chaque jour).
    """
    channel = "ntfy" if t else "web"
    return await _resolve_with_auth_or_token(
        action_id, "allow_always", None, current_user, t, channel,
    )


@router.post("/{action_id}/allow_for_task")
async def allow_for_task_action(
    action_id: str,
    t: str | None = Query(default=None, description="Signed action token (ntfy channel)"),
    current_user: User | None = Depends(get_optional_user),
):
    """Authorize this occurrence AND skip HITL for the same tool for the
    rest of the CURRENT conversation/task — args-agnostic, ephemeral, and
    NOT persisted (unlike ``allow_always``). Works even for locked tools.

    The conversation-scoped registration happens in ``tool_node`` when it
    handles the ``allow_for_task`` decision (it has the conversation_id).
    """
    channel = "ntfy" if t else "web"
    return await _resolve_with_auth_or_token(
        action_id, "allow_for_task", None, current_user, t, channel,
    )


@router.post("/{action_id}/deny")
async def deny_action(
    action_id: str,
    t: str | None = Query(default=None),
    current_user: User | None = Depends(get_optional_user),
    reason: str = Body(default=None, embed=True),
):
    """Refuse the action for this occurrence only."""
    channel = "ntfy" if t else "web"
    return await _resolve_with_auth_or_token(action_id, "deny", reason, current_user, t, channel)


@router.post("/{action_id}/ban")
async def ban_action(
    action_id: str,
    t: str | None = Query(default=None),
    current_user: User | None = Depends(get_optional_user),
    reason: str = Body(default=None, embed=True),
):
    """Refuse and permanently memorise a security rule derived from this action.

    The constraint is always derived from the pending action itself (its
    description and owner), so a push-action button with an empty body
    (ntfy or FCM) works without any body params.
    """
    # If using signed token, verify before touching anything else
    if t and not _verify_action_token(action_id, t):
        raise HTTPException(status_code=401, detail="Invalid action token")
    if not t and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    hitl = get_hitl_manager()
    pending = hitl._pending.get(action_id)
    # V0-2 : propriétaire résolu en mémoire OU en base, pour que le contrôle
    # d'appartenance et l'attribution de la contrainte survivent au
    # redémarrage (sinon, sur le chemin ntfy, la contrainte permanente
    # s'écrivait au nom de l'utilisateur vide).
    owner_id = await hitl.get_pending_owner(action_id)
    # Verify ownership when authenticated via JWT (token path already bound
    # caller to action_id via HMAC, no extra check needed).
    if not t and owner_id and current_user and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to resolve this action")

    # H1 (audit sécurité 13/06) — IDOR fermé : la description ET le
    # propriétaire de la contrainte sont TOUJOURS dérivés de l'action en
    # attente (figés côté serveur), jamais de paramètres du body. Avant,
    # `user_id`/`description` étaient acceptés du corps → un utilisateur
    # authentifié pouvait écrire une contrainte permanente au nom d'un autre.
    actual_desc = pending.description if pending else action_id
    actual_user = owner_id or (current_user.id if current_user else "")

    rule = f"INTERDICTION PERMANENTE: {actual_desc}"
    if reason:
        rule += f" — Raison: {reason}"
    await get_memory_manager().store_constraint(rule, actual_user)
    channel = "ntfy" if t else "web"
    return await _resolve_with_auth_or_token(action_id, "ban", reason, current_user, t, channel)
