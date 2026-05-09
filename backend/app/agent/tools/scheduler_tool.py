# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/scheduler_tool.py
# @brief      Scheduler tools for ELY agent — create and manage scheduled tasks via conversation.
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

    The task executes the given `prompt` at the specified schedule, just as
    if the user had typed it in the chat at that moment. The result is
    delivered via the chosen `channel`. Use this tool whenever the user asks
    to « programmer », « planifier », « rappeler », « envoyer plus tard »,
    « me notifier dans X heures/jours », « dans 3 jours ouvrés », etc.

    The `prompt` field can request ANY action ELY can normally perform —
    not just summaries. This includes sending an email, taking a screenshot,
    running a web search, listing emails, creating a calendar event, etc.

    Args:
        name: Short name for the task (e.g. "Rappel livraison Gert").
        prompt: The natural-language instruction to execute at run time.
            Examples:
              - One-shot reminder that triggers an email :
                « Envoie un email à gert@example.com en lui rappelant
                la livraison du colis prévue cette semaine »
              - Recurring summary :
                « Liste mes 5 derniers emails non lus et fais un résumé »
              - Recurring web check :
                « Vérifie les news IA d'hier et fais-moi un résumé en 5 lignes »
        cron_expression: Standard cron with 5 fields: minute hour day month day_of_week.

            ── RECURRING tasks (most common case) ──
              '0 8 * * 1-5'    weekdays 8am
              '30 9 * * *'     daily 9:30am
              '0 20 * * 0'     Sunday 8pm
              '0 */2 * * *'    every 2 hours

            ── ONE-SHOT tasks (specific date + time) ──
            Set the day and month explicitly; leave the others as «*».
              '0 8 14 5 *'     8 am on May 14th
              '30 9 27 12 *'   9:30 am on December 27th

            ⚠️ « Dans X jours ouvrés », « la semaine prochaine », « demain
            matin » must be converted to an ABSOLUTE date BEFORE building
            the cron. Use the current date (provided at the top of your
            prompt) and SKIP Saturdays / Sundays when counting « jours
            ouvrés ». Example reasoning for « dans 3 jours ouvrés à 8h »
            starting from a Monday: Tue=1, Wed=2, Thu=3 → cron `0 8 <Thu> <month> *`.
            Starting from a Saturday: Mon=1, Tue=2, Wed=3 → cron uses Wednesday.

        channel: 'web' (default — browser notification + accumulated in the
            « Missions » tab) or 'telegram' (Telegram message via the
            linked bot).
    """
    from croniter import croniter
    if not croniter.is_valid(cron_expression):
        return f"Expression cron invalide : '{cron_expression}'. Format : minute heure jour mois jour_semaine"

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
