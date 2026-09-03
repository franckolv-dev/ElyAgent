# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/hitl_manager.py
# @brief      Human-in-the-Loop (HITL) manager
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Human-in-the-Loop (HITL) manager.

When the agent wants to execute a critical action:
1. A push notification is fanned out to every linked channel (Android FCM,
   Telegram, web WebSocket).
2. Execution is paused (asyncio.Event) for up to TIMEOUT_SECONDS.
3. The user taps one of: Allow / Deny (once) / Ban (always).
4. The matching webhook endpoint resolves the event.
5. If "Ban": the action description is stored as a permanent security rule
   in Qdrant so the agent never proposes it again.

The frontend is also notified via WebSocket so it can show a visual indicator.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.services.background_tasks import spawn
from app.services.hitl_channels import DEFAULT_CHANNEL, normalize_channel

logger = logging.getLogger(__name__)

def _timeout_seconds() -> int:
    """Délai d'attente d'une validation HITL, configurable (HITL_TIMEOUT_SECONDS).

    30 min par défaut (était 5 min — trop court pour valider une notif ntfy
    depuis le téléphone, demande Franck 2026-06-19). Lu à chaque requête pour
    refléter un changement de config sans redémarrage. Un timeout n'est PAS un
    refus délibéré (record_hitl_refusal ignore reason='timeout')."""
    try:
        return int(get_settings().hitl_timeout_seconds)
    except Exception:
        return 1800


# Rétrocompat : encore importée par d'anciens tests/modules. Reflète le défaut ;
# le délai EFFECTIF est résolu dynamiquement par _timeout_seconds().
TIMEOUT_SECONDS = 1800

_firebase_init_lock = asyncio.Lock()


# ====================================================================== #
# V0-2 — persistance (audit Opus 5 §4.6)                                 #
#                                                                        #
# Tout l'état HITL vivait dans un dict en mémoire. Un redémarrage         #
# pendant une mission de nuit perdait les demandes en attente, et la     #
# décision prise ensuite depuis le téléphone tombait dans le vide.       #
#                                                                        #
# Périmètre honnête : la coroutine qui attendait est morte avec le       #
# processus, et rien ici ne la ressuscite (ce serait de la reprise       #
# d'exécution). Ce que la table garantit : la demande reste visible, et  #
# la décision humaine est ENREGISTRÉE au lieu d'être perdue.             #
#                                                                        #
# Best-effort : une base indisponible ne doit jamais empêcher une        #
# validation de se dérouler en mémoire — on trace et on continue.        #
# ====================================================================== #

async def persist_request(action_id: str, user_id: str, description: str) -> None:
    """Écrit la demande « en attente » en base, à sa création."""
    try:
        from app.database import async_session
        from app.models.hitl_request import HitlRequest
        async with async_session() as db:
            db.add(HitlRequest(
                action_id=action_id, user_id=user_id,
                description=description, status="pending",
            ))
            await db.commit()
    except Exception as exc:
        logger.warning("HITL %s: persistance de la demande échouée: %s", action_id, exc)


async def persist_decision(action_id: str, decision: str, reason: str | None) -> bool:
    """Reporte l'issue sur la ligne persistée.

    Rend ``True`` si une demande **encore en attente** a bien été tranchée.
    Rend ``False`` si l'action est inconnue ou déjà tranchée : c'est ce qui
    interdit la double validation, et ce qui distingue « décision arrivée
    après un redémarrage » (légitime) de « action fantôme » (à refuser).
    """
    try:
        from sqlalchemy import update
        from app.database import async_session
        from app.models.hitl_request import HitlRequest
        async with async_session() as db:
            result = await db.execute(
                update(HitlRequest)
                .where(
                    HitlRequest.action_id == action_id,
                    HitlRequest.status == "pending",
                )
                .values(
                    status=decision,
                    reason=reason,
                    resolved_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            return bool(result.rowcount)
    except Exception as exc:
        logger.warning("HITL %s: persistance de la décision échouée: %s", action_id, exc)
        return False


async def get_recorded_decision(action_id: str) -> tuple[str, str | None] | None:
    """Décision enregistrée pour cette action, ou ``None`` si encore en
    attente / inconnue. Permet à une exécution reprise de consulter un choix
    fait pendant que le processus était arrêté."""
    try:
        from sqlalchemy import select as _select
        from app.database import async_session
        from app.models.hitl_request import HitlRequest
        async with async_session() as db:
            row = (await db.execute(
                _select(HitlRequest).where(HitlRequest.action_id == action_id)
            )).scalar_one_or_none()
        if row is None or row.status == "pending":
            return None
        return row.status, row.reason
    except Exception as exc:
        logger.warning("HITL %s: lecture de la décision échouée: %s", action_id, exc)
        return None


@dataclass
class _PendingAction:
    action_id: str
    description: str
    user_id: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str = "deny"       # "allow" | "deny" | "ban"
    reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def expired(self) -> bool:
        return datetime.now(timezone.utc) > self.created_at + timedelta(seconds=_timeout_seconds())


class HITLManager:
    def __init__(self) -> None:
        self._pending: dict[str, _PendingAction] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def request_validation(
        self,
        description: str,
        user_id: str,
        channel: str = "web",
    ) -> tuple[str, str | None]:
        """Pause execution and wait for the user's decision.

        Sends validation request to ALL available channels:
        - Web UI via WebSocket
        - Telegram via inline keyboard (if user has linked account)
        - Android app via FCM push notification

        Returns a (decision, reason) tuple where decision is one of:
        ``"allow"``, ``"deny"``, ``"ban"``.
        """
        action_id = uuid.uuid4().hex[:8]
        pending = _PendingAction(action_id=action_id, description=description, user_id=user_id)
        self._pending[action_id] = pending
        # V0-2 : trace durable AVANT la notification — si le backend tombe
        # entre l'envoi et la réponse, la demande existe encore au retour.
        await persist_request(action_id, user_id, description)

        # ── Resolve the user's preferred channel (April 2026 fix #18) ──
        # Before this fix, ALL channels were notified in parallel — users
        # with multiple channels linked (Telegram + ntfy + Android app) got
        # 3 buzzes per HITL request. Now we honour User.hitl_preferred_channel:
        #   - None / "all" → legacy broadcast (every linked channel)
        #   - "web_only"   → only the WebSocket frontend (silent on phone)
        #   - specific     → just that channel + frontend (always for UI sync)
        #
        # ⚠️ 02/09/2026 — la valeur est NORMALISÉE ici, pas seulement à
        # l'affichage. La colonne peut porter le nom d'un canal depuis retiré
        # (« discord », « slack ») : lue telle quelle, aucun des trois envois
        # ci-dessous ne s'arme et l'éventail tombe à zéro. Sur un chemin sans
        # navigateur (mission, tâche planifiée) plus rien ne prévient
        # l'utilisateur, et la demande expire toute seule en auto-refus.
        preferred = DEFAULT_CHANNEL
        try:
            from app.database import async_session as _async_session
            from app.models.user import User as _U
            async with _async_session() as _db:
                _u = await _db.get(_U, user_id) if user_id else None
                if _u:
                    preferred = normalize_channel(_u.hitl_preferred_channel)
        except Exception as _exc:
            logger.debug("HITL channel preference lookup failed: %s — defaulting to 'all'", _exc)

        # The web frontend is ALWAYS notified — it must sync the chat UI in
        # real time. The preference only filters out the phone push channels.
        tasks: list = [
            self._notify_frontend(user_id, action_id, description, "hitl_pending"),
        ]
        send_telegram = preferred in ("all", "telegram")
        send_ntfy     = preferred in ("all", "ntfy")
        send_fcm      = preferred in ("all", "ely_android")

        if send_telegram:
            tasks.append(self._send_telegram(user_id, action_id, description))
        if send_ntfy:
            tasks.append(self._send_ntfy(action_id, description))

        await asyncio.gather(*tasks, return_exceptions=True)

        if send_fcm:
            # ⚠️ CE QUE ÇA CORRIGE (audit 02/09) : c'était un
            # `asyncio.create_task` nu. La boucle événementielle ne garde
            # qu'une référence FAIBLE sur la tâche : sous pression du GC, la
            # notification pouvait être ramassée EN VOL — l'utilisateur
            # n'était jamais prévenu qu'on attendait son approbation, et la
            # demande expirait toute seule en « timeout ». `spawn` garde une
            # référence forte et journalise l'échec au lieu de le perdre.
            spawn(
                self._send_fcm(user_id, action_id, "hitl", description, {}),
                label="hitl.push_fcm",
            )

        logger.info(
            "HITL %s dispatched (channel=%s, fan-out=%d)",
            action_id, preferred, sum([send_telegram, send_ntfy, send_fcm]),
        )

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=_timeout_seconds())
        except asyncio.TimeoutError:
            logger.info("HITL action %s timed out — auto-denied (not a deliberate refusal)", action_id)
            pending.decision = "deny"
            pending.reason = "timeout"
        finally:
            # Always clean up, even if the event loop is cancelled
            self._pending.pop(action_id, None)
            # No-op quand resolve() a déjà tranché (l'UPDATE ne vise que les
            # lignes « pending ») ; c'est le chemin du TIMEOUT qui écrit ici.
            await persist_decision(action_id, pending.decision, pending.reason)

        await self._notify_frontend(
            user_id, action_id, description, "hitl_resolved",
            decision=pending.decision, reason=pending.reason,
        )

        return pending.decision, pending.reason

    async def resolve(self, action_id: str, decision: str, reason: str | None = None) -> bool:
        """Enregistre la décision humaine. Appelée par le routeur de validation
        et par les boutons Telegram.

        V0-2 — deux chemins, un seul verdict :

        - **processus vivant** : on réveille la coroutine en attente, ET on
          reporte l'issue en base ;
        - **après un redémarrage** : plus rien en mémoire. La décision est
          quand même enregistrée — c'est tout l'objet du lot. Avant, elle
          était silencieusement perdue (``False`` → 404 côté routeur).

        Rend ``False`` seulement si l'action est inconnue **ou déjà tranchée**
        (pas de double validation, pas d'acceptation fantôme).
        """
        pending = self._pending.get(action_id)
        if pending is not None:
            persisted = await persist_decision(action_id, decision, reason)
            if not persisted and await get_recorded_decision(action_id) is not None:
                return False  # déjà tranchée par un autre canal
            pending.decision = decision
            pending.reason = reason
            pending.event.set()
            return True

        # Mémoire vide : soit le backend a redémarré, soit l'action n'a
        # jamais existé. Seule la base peut faire la différence.
        return await persist_decision(action_id, decision, reason)

    async def get_pending_owner(self, action_id: str) -> str | None:
        """Propriétaire d'une demande ENCORE en attente, ou ``None``.

        Le routeur de validation en a besoin pour son contrôle
        d'appartenance : avant V0-2 il lisait ``_pending`` en direct et
        rendait donc 404 après un redémarrage, sans même appeler
        ``resolve()``. La vérification de propriété reste entière — elle
        s'appuie simplement sur une source qui survit au processus.
        """
        pending = self._pending.get(action_id)
        if pending is not None:
            return pending.user_id
        try:
            from sqlalchemy import select as _select
            from app.database import async_session
            from app.models.hitl_request import HitlRequest
            async with async_session() as db:
                row = (await db.execute(
                    _select(HitlRequest).where(
                        HitlRequest.action_id == action_id,
                        HitlRequest.status == "pending",
                    )
                )).scalar_one_or_none()
            return row.user_id if row is not None else None
        except Exception as exc:
            logger.warning("HITL %s: lecture du propriétaire échouée: %s", action_id, exc)
            return None

    async def list_pending(self, user_id: str) -> list[dict]:
        """Return all pending HITL actions for a given user.

        Used by the web UI bell component to display unresolved approval
        requests when the WebSocket was not connected at the moment the
        action was created (e.g. user is on a page other than /chat).

        Expired or resolved actions are filtered out — only actually
        actionable items are returned.

        V0-2 : lue depuis la base, donc la cloche survit à un redémarrage.
        Repli sur la mémoire si la base est indisponible.
        """
        try:
            from sqlalchemy import select as _select
            from app.database import async_session
            from app.models.hitl_request import HitlRequest
            floor = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                seconds=_timeout_seconds()
            )
            async with async_session() as db:
                rows = (await db.execute(
                    _select(HitlRequest)
                    .where(
                        HitlRequest.user_id == user_id,
                        HitlRequest.status == "pending",
                        HitlRequest.created_at >= floor,
                    )
                    .order_by(HitlRequest.created_at.desc())
                )).scalars().all()
            return [
                {
                    "action_id": r.action_id,
                    "description": r.description,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("HITL: lecture des demandes en attente échouée: %s", exc)

        out: list[dict] = []
        for p in self._pending.values():
            if p.user_id != user_id:
                continue
            if p.expired() or p.event.is_set():
                continue
            out.append({
                "action_id": p.action_id,
                "description": p.description,
                "created_at": p.created_at.isoformat(),
            })
        # Newest first
        out.sort(key=lambda d: d["created_at"], reverse=True)
        return out

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _send_ntfy(self, action_id: str, description: str) -> None:
        """Fire a push notification to the ntfy topic configured in settings.

        `ntfy_url` should be the FULL topic URL (e.g.
        https://ntfy.sh/ely-franck-xxxxx). If unset, this is a no-op.

        Notifications include 3 action buttons that call back the backend's
        /validation/{action_id}/{decision} endpoints directly — so the user
        can approve/deny straight from the phone notification shade without
        opening the app.
        """
        settings = get_settings()
        if not settings.ntfy_url:
            logger.debug("ntfy not configured — skipping push")
            return

        base = settings.backend_url.rstrip("/")
        # Sign the action_id so the notification buttons can resolve the
        # HITL without passing a JWT (ntfy actions have no way to carry
        # one). The token is validated by _verify_action_token in
        # backend/app/routers/validation.py.
        from app.routers.validation import sign_action_token
        tok = sign_action_token(action_id)

        # IMPORTANT: nginx in front of the backend only proxies /api/* to
        # the FastAPI app, so the action buttons MUST call /api/validation/*
        # (legacy /validation/* is also mounted but only reachable directly
        # on the backend port, not via the public Cloudflare Tunnel URL).
        # JSON body is required to keep Unicode safe (ntfy headers are ASCII-only).
        # See https://docs.ntfy.sh/publish/#publish-as-json
        payload = {
            "topic": settings.ntfy_topic or "ely",
            "title": "Action requise — Ely",
            "message": description[:4000],
            "priority": 5,
            "tags": ["warning", "robot"],
            "actions": [
                {"action": "http", "label": "Autoriser",
                 "url": f"{base}/api/validation/{action_id}/allow?t={tok}",
                 "method": "POST", "clear": True},
                {"action": "http", "label": "Refuser",
                 "url": f"{base}/api/validation/{action_id}/deny?t={tok}",
                 "method": "POST", "clear": True},
                {"action": "http", "label": "Interdire",
                 "url": f"{base}/api/validation/{action_id}/ban?t={tok}",
                 "method": "POST", "clear": True},
            ],
        }
        # If ntfy_url already points at a topic (e.g. https://ntfy.sh/xxx),
        # we POST to the host root and let the "topic" field route. If it's
        # just the host (https://ntfy.sh), we also POST to root — equivalent.
        from urllib.parse import urlparse
        u = urlparse(settings.ntfy_url)
        host_root = f"{u.scheme}://{u.netloc}"
        # Override topic from URL path if present (takes precedence over ntfy_topic)
        url_topic = u.path.strip("/")
        if url_topic:
            payload["topic"] = url_topic

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(host_root, json=payload)
                if resp.status_code >= 300:
                    logger.warning(
                        "ntfy returned HTTP %s: %s",
                        resp.status_code, resp.text[:200],
                    )
                else:
                    logger.info("ntfy push sent for action %s", action_id)
        except Exception as exc:
            logger.warning("Failed to send ntfy notification: %s", exc)

    async def _send_telegram(self, user_id: str, action_id: str, description: str) -> None:
        """Send HITL validation as Telegram inline keyboard if user has linked account."""
        try:
            from app.channels.telegram_bot import _bot_app, _linked_users
            if not _bot_app:
                return

            # Find Telegram ID for this user
            tg_id = None
            for tid, uid in _linked_users.items():
                if uid == user_id:
                    tg_id = tid
                    break

            if not tg_id:
                return

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [
                    InlineKeyboardButton("✅ Autoriser", callback_data=f"hitl:allow:{action_id}"),
                    InlineKeyboardButton("❌ Refuser", callback_data=f"hitl:deny:{action_id}"),
                ],
                [
                    InlineKeyboardButton("🚫 Interdire définitivement", callback_data=f"hitl:ban:{action_id}"),
                ],
            ]
            await _bot_app.bot.send_message(
                chat_id=tg_id,
                text=f"⚠️ Validation requise :\n\n{description[:3000]}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            logger.warning("Failed to send Telegram HITL: %s", exc)

    async def _send_fcm(self, user_id: str, action_id: str, tool: str, description: str, args: dict) -> None:
        """Send HITL notification via Firebase Cloud Messaging to Android app."""
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging

            # Initialize Firebase app once (lazy, race-safe)
            async with _firebase_init_lock:
                if not firebase_admin._apps:
                    cred_path = get_settings().firebase_credentials_path
                    if not cred_path or not os.path.exists(cred_path):
                        return  # FCM not configured
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)

            # Get user's FCM token from DB
            from app.database import async_session
            from app.models.user import User
            from sqlalchemy import select
            async with async_session() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if not user or not user.fcm_token:
                    return

            message = messaging.Message(
                data={
                    "type": "hitl_pending",
                    "action_id": action_id,
                    "tool": tool,
                    "description": description,
                    "args": json.dumps(args),
                },
                android=messaging.AndroidConfig(priority="high"),
                token=user.fcm_token,
            )
            await asyncio.to_thread(messaging.send, message)
            logger.info(f"FCM HITL notification sent to user {user_id}")
        except Exception as e:
            logger.warning(f"FCM send failed: {e}")

    async def _notify_frontend(
        self,
        user_id: str,
        action_id: str,
        description: str,
        msg_type: str,
        **extra,
    ) -> None:
        # Fan-out to EVERY open socket (B-6, revue 2026-06-10) — a HITL card
        # must reach all tabs/devices, not just the most recent connection.
        from app.services.ws_registry import send_text_all
        payload = {"type": msg_type, "action_id": action_id, "description": description, **extra}
        try:
            await send_text_all(user_id, json.dumps(payload))
        except Exception:
            pass


def get_hitl_manager() -> HITLManager:
    return _hitl_manager


_hitl_manager = HITLManager()
