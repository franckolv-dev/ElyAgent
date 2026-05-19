# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/scheduler.py
# @brief      Task scheduler — runs agent prompts on cron schedules
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
"""Task scheduler — runs agent prompts on cron schedules.

Each task triggers the same LangGraph agent as a regular chat message,
then delivers the result to the specified channel (web push or Telegram).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from functools import lru_cache

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
    from app.agent.graph import build_agent_graph
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

        # Invoke agent
        agent = build_agent_graph()
        invoke_result = await agent.ainvoke({
            "messages": [HumanMessage(content=task.prompt)],
            "user_id": task.user_id,
            "conversation_id": conv_id,
            "google_credentials": google_credentials or "",
        })

        ai_content = invoke_result["messages"][-1].content

        # Save result
        async with async_session() as db:
            db.add(Message(conversation_id=conv_id, role="assistant", content=ai_content))
            # Update task metadata
            t_result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            t = t_result.scalar_one_or_none()
            if t:
                t.last_run_at = datetime.now(timezone.utc)
                t.last_result = ai_content[:2000]
            await db.commit()

        # Deliver result to channel
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
    """Deliver task result to the appropriate channel."""

    # Telegram delivery
    if task.channel == "telegram":
        try:
            from app.channels.telegram_bot import _bot_app, _linked_users

            if _bot_app:
                # Find Telegram ID for this user
                tg_id = None
                for tid, uid in _linked_users.items():
                    if uid == task.user_id:
                        tg_id = tid
                        break

                if tg_id:
                    header = f"📋 Tâche planifiée : {task.name}\n\n"
                    full_msg = header + content
                    for i in range(0, len(full_msg), 4096):
                        await _bot_app.bot.send_message(chat_id=tg_id, text=full_msg[i:i + 4096])
                    return
        except Exception as exc:
            logger.warning("Failed Telegram delivery for task %s: %s", task.id, exc)

    # Web delivery: push via WebSocket if connected
    try:
        from app.services import ws_registry
        ws = ws_registry.get(task.user_id)
        if ws:
            import json
            await ws.send_text(json.dumps({
                "type": "scheduled_task",
                "task_name": task.name,
                "content": content,
            }))
            return
    except Exception as exc:
        logger.warning("Failed WebSocket delivery for task %s: %s", task.id, exc)

    logger.info("Task '%s' result stored but no active channel for delivery", task.name)


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
