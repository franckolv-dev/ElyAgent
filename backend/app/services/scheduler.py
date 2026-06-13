# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/scheduler.py
# @brief      Task scheduler — runs agent prompts on cron schedules
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
"""Task scheduler — runs agent prompts on cron schedules.

Each task triggers the same LangGraph agent as a regular chat message,
then delivers the result to the specified channel (web push or Telegram).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import async_session
from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.models.conversation import Conversation, Message

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Europe/Paris")
    return _scheduler


async def _execute_task(task_id: str) -> None:
    """Execute a scheduled task: invoke agent and deliver result."""
    from app.agent.graph import build_simple_agent_graph
    from langchain_core.messages import HumanMessage

    try:
        async with async_session() as db:
            result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if not task or not task.enabled:
                return

            # Get user's google credentials
            u_result = await db.execute(select(User).where(User.id == task.user_id))
            user = u_result.scalar_one_or_none()
            google_credentials = user.google_credentials if user else None

        logger.info("Executing scheduled task '%s' for user %s", task.name, task.user_id)

        # A-6b — budget LLM quotidien du user : une tâche planifiée saute
        # son exécution du jour (la tâche reste programmée, le cron la
        # relancera à la prochaine occurrence).
        from app.services.budget_guard import check_user_budget
        if await check_user_budget(task.user_id):
            logger.warning(
                "Scheduled task '%s' (user %s) skipped — budget LLM "
                "quotidien épuisé", task.name, task.user_id,
            )
            return

        # Create a conversation for this execution
        async with async_session() as db:
            conv = Conversation(
                user_id=task.user_id,
                title=f"[Planifié] {task.name}"
            )
            db.add(conv)
            await db.flush()
            conv_id = str(conv.id)
            db.add(Message(conversation_id=conv_id, role="user", content=task.prompt))
            await db.commit()

        # Invoke agent. Scheduled tasks run on the FLAT (non-supervisor) graph
        # with ``automated_task=True``. Rationale (2026-05-31) : the supervisor
        # routes a whole prompt to ONE sub-agent, so a multi-domain prompt —
        # e.g. a daily briefing that needs calendar + gmail + system tools —
        # lost every tool outside the chosen sub-agent's domain and reported
        # « outil X non disponible pour cet agent » for the rest. The flat
        # graph binds every tool the prompt names (see create_agent_node's
        # automated_task branch). recursion_limit configurable
        # (scheduler_recursion_limit, défaut 60) — 25 était trop bas pour les
        # tâches multi-étapes qui bouclaient avant d'atteindre leurs écritures
        # (bug terrain 13/06, Prospection). Voir config.py.
        from app.config import get_settings as _get_settings
        _recursion = _get_settings().scheduler_recursion_limit
        agent = build_simple_agent_graph()
        invoke_result = await agent.ainvoke(
            {
                "messages": [HumanMessage(content=task.prompt)],
                "user_id": task.user_id,
                "conversation_id": conv_id,
                "google_credentials": google_credentials or "",
                "automated_task": True,
            },
            config={"recursion_limit": _recursion},
        )

        # `content` can be str OR list[dict] (multimodal blocks). Coerce
        # to string for DB persistence — saving a list to a Text column
        # would trigger an autoflush failure when the next SELECT runs
        # in the same session (observed bug : Telegram task 73994b74
        # crashed at 17:30 with "raised as a result of Query-invoked
        # autoflush"). The list shape happens when an agent emits text+
        # image+text triples (e.g. weather card with icon).
        ai_content_raw = invoke_result["messages"][-1].content
        if isinstance(ai_content_raw, list):
            ai_content = " ".join(
                (b.get("text", "") if isinstance(b, dict) else str(b))
                for b in ai_content_raw
            )
        else:
            ai_content = str(ai_content_raw or "")

        # Save result. Split into two sessions to avoid autoflush
        # interference between the new Message insert and the subsequent
        # ScheduledTask UPDATE (they touch unrelated tables but share the
        # same Unit-of-Work; an autoflush mid-query has caused failures).
        async with async_session() as db:
            db.add(Message(conversation_id=conv_id, role="assistant", content=ai_content))
            await db.commit()
        async with async_session() as db:
            t_result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            t = t_result.scalar_one_or_none()
            if t:
                t.last_run_at = datetime.now(timezone.utc)
                t.last_result = ai_content[:2000]
                await db.commit()

        # Deliver result to all configured channels (email, telegram,
        # whatsapp, discord, slack, ntfy + always-on web fallback).
        await _deliver_result(task, ai_content)

        logger.info("Scheduled task '%s' completed", task.name)

    except Exception as exc:
        logger.exception("Failed to execute scheduled task %s: %s", task_id, exc)
        # Save error — wrapped in its own try-except so a DB failure doesn't hide the original error
        try:
            async with async_session() as db:
                t_result = await db.execute(
                    select(ScheduledTask).where(ScheduledTask.id == task_id)
                )
                t = t_result.scalar_one_or_none()
                if t:
                    t.last_run_at = datetime.now(timezone.utc)
                    t.last_result = f"Erreur: {exc}"
                    await db.commit()
        except Exception as db_exc:
            logger.warning("Failed to persist error status for task %s: %s", task_id, db_exc)


async def _deliver_result(task: ScheduledTask, content: str) -> None:
    """Deliver task result to the configured channel.

    Channels supported : telegram, whatsapp, discord, slack, email, ntfy.
    Default ("web" or unknown) → push via WebSocket if connected, AND
    always persist a Message in a dedicated `[Tâches planifiées]`
    conversation so the user sees the result on next login (mirrors the
    [Missions] Notifications pattern).

    Each channel is attempted independently and errors are logged but
    don't block the others.
    """
    chan = (task.channel or "web").lower()
    header = f"📋 *Tâche planifiée : {task.name}*\n\n"
    full = header + content
    delivered = False

    # ── Telegram ──
    if chan == "telegram":
        try:
            from app.channels.telegram_bot import _bot_app, _linked_users
            if _bot_app:
                tg_id = next((tid for tid, uid in _linked_users.items() if uid == task.user_id), None)
                if tg_id:
                    # parse_mode=None : task name + AI content are user/LLM
                    # text → Markdown injection risk + crashes on stray
                    # `_` `*` characters.
                    for i in range(0, len(full), 4096):
                        await _bot_app.bot.send_message(chat_id=tg_id, text=full[i:i + 4096])
                    delivered = True
                else:
                    logger.warning("Task %s telegram: user %s has no linked TG account", task.id, task.user_id)
            else:
                logger.warning("Task %s telegram: bot not running", task.id)
        except Exception as exc:
            logger.warning("Failed Telegram delivery for task %s: %s", task.id, exc)

    # ── WhatsApp (self-chat via neonize bridge) ──
    elif chan == "whatsapp":
        try:
            from app.channels.whatsapp_web import _sessions as _wa_sessions, send_text
            sess = _wa_sessions.get(task.user_id)
            if sess and sess.get("status") == "linked" and sess.get("phone"):
                ok = await send_text(sess["phone"], full, from_user_id=task.user_id)
                delivered = bool(ok)
            else:
                logger.warning("Task %s whatsapp: no linked WhatsApp Web session", task.id)
        except Exception as exc:
            logger.warning("Failed WhatsApp delivery for task %s: %s", task.id, exc)

    # ── Discord (DM the linked user) ──
    elif chan == "discord":
        try:
            from app.channels import discord_bot as _dc
            if getattr(_dc, "_discord_client", None) and _dc._discord_client.is_ready():
                # Reverse-lookup Discord user_id from ELY user_id
                dc_id = next((did for did, uid in _dc._linked_users.items() if uid == task.user_id), None)
                if dc_id:
                    user = await _dc._discord_client.fetch_user(int(dc_id))
                    for i in range(0, len(full), 2000):  # Discord message cap
                        await user.send(full[i:i + 2000])
                    delivered = True
                else:
                    logger.warning("Task %s discord: user %s has no linked Discord account", task.id, task.user_id)
        except Exception as exc:
            logger.warning("Failed Discord delivery for task %s: %s", task.id, exc)

    # ── Slack (DM the linked user) ──
    elif chan == "slack":
        try:
            from app.channels import slack_bot as _sl
            if getattr(_sl, "_slack_app", None):
                slack_uid = next((sid for sid, uid in _sl._linked_users.items() if uid == task.user_id), None)
                if slack_uid:
                    open_resp = await _sl._slack_app.client.conversations_open(users=slack_uid)
                    chan_id = open_resp["channel"]["id"]
                    for i in range(0, len(full), 4000):
                        await _sl._slack_app.client.chat_postMessage(channel=chan_id, text=full[i:i + 4000])
                    delivered = True
                else:
                    logger.warning("Task %s slack: user %s has no linked Slack account", task.id, task.user_id)
        except Exception as exc:
            logger.warning("Failed Slack delivery for task %s: %s", task.id, exc)

    # ── Email (via user's Gmail OAuth credentials) ──
    elif chan == "email":
        try:
            async with async_session() as db:
                u = (await db.execute(select(User).where(User.id == task.user_id))).scalar_one_or_none()

            # Resolve recipient email. Priority :
            # 1. User.email (if it looks like a real address)
            # 2. UserProfile `primary_email` / `user_email` keys (consolidated from chat)
            # Without this fallback, users created with username==email
            # (common at first sign-up) would silently fail email delivery.
            target_email: Optional[str] = None
            if u:
                if u.email and "@" in u.email:
                    target_email = u.email
                else:
                    try:
                        from app.models.user_memory import UserProfile
                        async with async_session() as db:
                            r = await db.execute(
                                select(UserProfile)
                                .where(UserProfile.user_id == task.user_id)
                                .where(UserProfile.key.in_({"primary_email", "user_email", "email"}))
                                .order_by(UserProfile.confidence.desc())
                                .limit(1)
                            )
                            up = r.scalar_one_or_none()
                            if up and "@" in (up.value or ""):
                                target_email = up.value.strip()
                                logger.info("Task %s email: using UserProfile.%s (%s)", task.id, up.key, target_email)
                    except Exception as exc:
                        logger.debug("UserProfile lookup failed: %s", exc)

            if not u:
                logger.warning("Task %s email: user not found", task.id)
            elif not u.google_credentials:
                logger.warning("Task %s email: user %s has no Google OAuth — connect Google in Settings", task.id, u.username)
            elif not target_email:
                logger.warning("Task %s email: user %s has no valid email anywhere (User.email=%r, UserProfile empty)", task.id, u.username, u.email)
            else:
                # Direct call to the Gmail tool's underlying coroutine. We
                # bypass the LangChain @tool decorator wrapper because we
                # already have the user's credentials in hand and don't
                # need HITL (the user EXPLICITLY scheduled this task).
                from app.agent.tools.gmail_tool import gmail_send_email
                result = await gmail_send_email.ainvoke({
                    "to": target_email,
                    "subject": f"[ELY] Tâche planifiée : {task.name}",
                    "body": content,
                    "user_google_credentials_json": u.google_credentials,
                })
                if isinstance(result, str) and ("envoyé" in result.lower() or "sent" in result.lower() or "id:" in result.lower()):
                    delivered = True
                    logger.info("Task %s email: sent to %s (gmail returned: %s)", task.id, target_email, str(result)[:80])
                else:
                    logger.warning("Task %s email: gmail_send_email returned: %s", task.id, str(result)[:200])
        except Exception as exc:
            logger.warning("Failed email delivery for task %s: %s", task.id, exc)

    # ── ntfy (mobile push) ──
    elif chan == "ntfy":
        import os
        ntfy_url = os.environ.get("NTFY_URL")
        if ntfy_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.post(
                        ntfy_url,
                        headers={
                            "Title": f"Tâche planifiée : {task.name}"[:120],
                            "Tags": "calendar",
                            "Priority": "default",
                        },
                        content=content[:1000].encode("utf-8"),
                    )
                delivered = True
            except Exception as exc:
                logger.warning("Failed ntfy delivery for task %s: %s", task.id, exc)
        else:
            logger.warning("Task %s ntfy: NTFY_URL not configured", task.id)

    # ── WebSocket push (best-effort, runs for ALL channels including unknown) ──
    try:
        from app.services import ws_registry
        if ws_registry.get(task.user_id):
            import json
            await ws_registry.send_text_all(task.user_id, json.dumps({
                "type": "scheduled_task",
                "task_name": task.name,
                "content": content,
            }))
            # Don't set `delivered=True` — WebSocket is a "live" push that
            # only works if the user has the app open. The persisted Message
            # below is what guarantees the user sees it next time.
    except Exception as exc:
        logger.warning("WebSocket push for task %s skipped: %s", task.id, exc)

    # ── ALWAYS persist in [Tâches planifiées] convo as a fallback ──
    # Mirrors the [Missions] Notifications pattern : the user always finds
    # the result in their sidebar even if the channel-specific delivery
    # failed (offline, token rotated, etc.).
    try:
        async with async_session() as db:
            r = await db.execute(
                select(Conversation)
                .where(Conversation.user_id == task.user_id)
                .where(Conversation.title.like("[Tâches planifiées]%"))
                .limit(1)
            )
            conv = r.scalar_one_or_none()
            if not conv:
                conv = Conversation(user_id=task.user_id, title="[Tâches planifiées] Résultats")
                db.add(conv)
                await db.flush()
            db.add(Message(conversation_id=conv.id, role="assistant", content=full))
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to persist task result in [Tâches planifiées] convo: %s", exc)

    if delivered:
        logger.info("Task '%s' delivered via %s", task.name, chan)
    else:
        logger.info("Task '%s' result stored (channel=%s did not deliver — see warnings above)", task.name, chan)


def _parse_cron(expression: str) -> CronTrigger | None:
    """Parse a cron expression into an APScheduler CronTrigger.

    Supports standard 5-field cron: minute hour day month day_of_week
    Examples: '0 8 * * 1-5' (weekdays at 8am), '30 9 * * *' (daily at 9:30)
    """
    try:
        parts = expression.strip().split()
        if len(parts) == 5:
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone="Europe/Paris",
            )
        else:
            logger.warning("Invalid cron expression: %s", expression)
            return None
    except Exception as exc:
        logger.warning("Failed to parse cron '%s': %s", expression, exc)
        return None


async def load_and_schedule_tasks() -> None:
    """Load all enabled tasks from DB and register them with APScheduler."""
    scheduler = get_scheduler()

    async with async_session() as db:
        result = await db.execute(
            select(ScheduledTask).where(ScheduledTask.enabled == True)
        )
        tasks = result.scalars().all()

    for task in tasks:
        trigger = _parse_cron(task.cron_expression)
        if trigger:
            scheduler.add_job(
                _execute_task,
                trigger=trigger,
                args=[task.id],
                id=f"task_{task.id}",
                replace_existing=True,
                name=task.name,
            )
            logger.info("Scheduled task '%s' (%s)", task.name, task.cron_expression)

    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started with %d tasks", len(tasks))


def schedule_task(task: ScheduledTask) -> bool:
    """Add or update a single task in the running scheduler."""
    scheduler = get_scheduler()
    trigger = _parse_cron(task.cron_expression)
    if not trigger:
        return False

    scheduler.add_job(
        _execute_task,
        trigger=trigger,
        args=[task.id],
        id=f"task_{task.id}",
        replace_existing=True,
        name=task.name,
    )
    return True


def unschedule_task(task_id: str) -> None:
    """Remove a task from the running scheduler."""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(f"task_{task_id}")
    except Exception:
        pass  # Job may not exist


async def stop_scheduler() -> None:
    """Shutdown the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
