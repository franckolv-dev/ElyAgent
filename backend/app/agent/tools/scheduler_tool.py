"""Scheduler tools for ELY agent — create and manage scheduled tasks via conversation."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg
from sqlalchemy import select

from app.database import async_session
from app.models.scheduled_task import ScheduledTask
from app.services.scheduler import schedule_task, unschedule_task


@tool
async def scheduler_list_tasks(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List all scheduled tasks for the current user.

    Returns the list of active and inactive scheduled tasks with their cron schedule.
    """
    async with async_session() as db:
        result = await db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTask.created_at.desc())
        )
        tasks = result.scalars().all()

    if not tasks:
        return "Aucune tâche planifiée."

    lines = []
    for t in tasks:
        status = "actif" if t.enabled else "désactivé"
        last = f" (dernier résultat: {t.last_result[:80]}...)" if t.last_result else ""
        lines.append(
            f"'{t.name}' ({status}) — cron: {t.cron_expression} — canal: {t.channel}{last}\n"
            f"  Prompt: {t.prompt[:100]}...\n"
            f"  ID: {t.id}"
        )

    return f"{len(tasks)} tâche(s) planifiée(s):\n\n" + "\n\n".join(lines)


@tool
async def scheduler_create_task(
    name: str,
    prompt: str,
    cron_expression: str,
    channel: str = "web",
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a new scheduled task that will run automatically.

    The task executes the given prompt at the specified schedule and delivers
    the result via the chosen channel.

    Args:
        name: Short name for the task (e.g. "Résumé emails du matin")
        prompt: The prompt to execute (e.g. "Liste mes 5 derniers emails non lus et fais un résumé")
        cron_expression: Standard cron expression with 5 fields: minute hour day month day_of_week.
            Examples: '0 8 * * 1-5' (weekdays 8am), '30 9 * * *' (daily 9:30am),
            '0 20 * * 0' (Sunday 8pm), '0 */2 * * *' (every 2 hours)
        channel: Delivery channel — 'web' for browser notification, 'telegram' for Telegram message
    """
    task = ScheduledTask(
        user_id=user_id,
        name=name,
        prompt=prompt,
        cron_expression=cron_expression,
        channel=channel,
    )

    async with async_session() as db:
        db.add(task)
        await db.commit()
        await db.refresh(task)

    if not schedule_task(task):
        return f"Erreur : expression cron invalide '{cron_expression}'. Format : minute heure jour mois jour_semaine"

    return (
        f"Tâche planifiée créée : '{name}'\n"
        f"Planification : {cron_expression}\n"
        f"Canal : {channel}\n"
        f"Prompt : {prompt}\n"
        f"ID : {task.id}"
    )


@tool
async def scheduler_delete_task(
    task_id: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Delete a scheduled task.

    Args:
        task_id: The task ID to delete (from scheduler_list_tasks)
    """
    async with async_session() as db:
        result = await db.execute(
            select(ScheduledTask).where(
                ScheduledTask.id == task_id,
                ScheduledTask.user_id == user_id,
            )
        )
        task = result.scalar_one_or_none()
        if not task:
            return "Tâche non trouvée."

        name = task.name
        unschedule_task(task.id)
        await db.delete(task)
        await db.commit()

    return f"Tâche '{name}' supprimée."
