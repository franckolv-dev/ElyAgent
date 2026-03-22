"""Human-in-the-Loop (HITL) manager.

When the agent wants to execute a critical action:
1. A ntfy push notification is sent to Android with three action buttons.
2. Execution is paused (asyncio.Event) for up to TIMEOUT_SECONDS.
3. The Android user taps one of: Allow / Deny (once) / Ban (always).
4. The matching webhook endpoint resolves the event.
5. If "Ban": the action description is stored as a permanent security rule
   in Qdrant so the agent never proposes it again.

The frontend is also notified via WebSocket so it can show a visual indicator.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300  # 5 minutes


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
        - ntfy push notification (if configured)

        Returns a (decision, reason) tuple where decision is one of:
        ``"allow"``, ``"deny"``, ``"ban"``.
        """
        action_id = uuid.uuid4().hex[:8]
        pending = _PendingAction(action_id=action_id, description=description, user_id=user_id)
        self._pending[action_id] = pending

        # Notify ALL available channels in parallel
        await asyncio.gather(
            self._notify_frontend(user_id, action_id, description, "hitl_pending"),
            self._send_ntfy(action_id, description),
            self._send_telegram(user_id, action_id, description),
            return_exceptions=True,
        )

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.info("HITL action %s timed out — auto-denied", action_id)
            pending.decision = "deny"
            pending.reason = "timeout"

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

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _send_ntfy(self, action_id: str, description: str) -> None:
        settings = get_settings()
        if not settings.ntfy_url:
            logger.debug("ntfy not configured — skipping push notification")
            return

        topic = settings.ntfy_topic or "cyberentity"
        base = settings.backend_url.rstrip("/")
        headers = {
            "Title": "⚠️ Action requise — Cyber-Entity",
            "Priority": "high",
            "Tags": "warning,robot",
            "Actions": (
                f"http, ✅ Autoriser, {base}/validation/{action_id}/allow, method=POST; "
                f"http, ❌ Refuser, {base}/validation/{action_id}/deny, method=POST; "
                f"http, 🛡️ Interdire toujours, {base}/validation/{action_id}/ban, method=POST"
            ),
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(f"{settings.ntfy_url}/{topic}", content=description, headers=headers)
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
