# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/hitl_manager.py
# @brief      Human-in-the-Loop (HITL) manager
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Human-in-the-Loop (HITL) manager.

When the agent wants to execute a critical action:
1. A push notification is fanned out to every linked channel (Android FCM,
   Telegram, Discord, Slack, web WebSocket).
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

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300  # 5 minutes — laisse le temps à la notif FCM d'arriver
#                       sur Android, que l'utilisateur la voie, déverrouille
#                       son tél, et valide. Le runner de tests automatisé
#                       utilise son propre HITL_TIMEOUT=180s pour ne pas
#                       bloquer. En usage réel c'est la patience humaine qui
#                       compte — 2 minutes était trop court (essais sur
#                       2026-04-23 : 404 systématiques car auto-deny déclenché
#                       avant que l'utilisateur ait cliqué).

_firebase_init_lock = asyncio.Lock()


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
        return datetime.now(timezone.utc) > self.created_at + timedelta(seconds=TIMEOUT_SECONDS)


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

        # ── Resolve the user's preferred channel (April 2026 fix #18) ──
        # Before this fix, ALL channels were notified in parallel — users
        # with multiple channels linked (Telegram + ntfy + Android app) got
        # 3 buzzes per HITL request. Now we honour User.hitl_preferred_channel:
        #   - None / "all" → legacy broadcast (every linked channel)
        #   - "web_only"   → only the WebSocket frontend (silent on phone)
        #   - specific     → just that channel + frontend (always for UI sync)
        preferred = "all"
        try:
            from app.database import async_session as _async_session
            from app.models.user import User as _U
            async with _async_session() as _db:
                _u = await _db.get(_U, user_id) if user_id else None
                if _u and _u.hitl_preferred_channel:
                    preferred = _u.hitl_preferred_channel
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
        send_discord  = preferred in ("all", "discord")  # currently no-op until _send_discord
        send_slack    = preferred in ("all", "slack")    # currently no-op until _send_slack

        if send_telegram:
            tasks.append(self._send_telegram(user_id, action_id, description))
        if send_ntfy:
            tasks.append(self._send_ntfy(action_id, description))

        await asyncio.gather(*tasks, return_exceptions=True)

        if send_fcm:
            asyncio.create_task(self._send_fcm(user_id, action_id, "hitl", description, {}))

        logger.info(
            "HITL %s dispatched (channel=%s, fan-out=%d)",
            action_id, preferred, sum([send_telegram, send_ntfy, send_fcm, send_discord, send_slack]),
        )

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.info("HITL action %s timed out — auto-denied", action_id)
            pending.decision = "deny"
            pending.reason = "timeout"
        finally:
            # Always clean up, even if the event loop is cancelled
            self._pending.pop(action_id, None)

        await self._notify_frontend(
            user_id, action_id, description, "hitl_resolved",
            decision=pending.decision, reason=pending.reason,
        )

        return pending.decision, pending.reason

    async def resolve(self, action_id: str, decision: str, reason: str | None = None) -> bool:
        """Called by the webhook router when Android sends a response."""
        pending = self._pending.get(action_id)
        if not pending:
            return False
        pending.decision = decision
        pending.reason = reason
        pending.event.set()
        return True

    def list_pending(self, user_id: str) -> list[dict]:
        """Return all pending HITL actions for a given user.

        Used by the web UI bell component to display unresolved approval
        requests when the WebSocket was not connected at the moment the
        action was created (e.g. user is on a page other than /chat).

        Expired or resolved actions are filtered out — only actually
        actionable items are returned.
        """
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
            "title": "Action requise — Éli",
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
        from app.services.ws_registry import get as ws_get
        ws = ws_get(user_id)
        if not ws:
            return
        payload = {"type": msg_type, "action_id": action_id, "description": description, **extra}
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            pass


def get_hitl_manager() -> HITLManager:
    return _hitl_manager


_hitl_manager = HITLManager()
