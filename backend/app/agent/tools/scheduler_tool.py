# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/scheduler_tool.py
# @brief      Scheduler tools for ELY agent — create and manage scheduled tasks via conversation.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
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
    as_mission: bool = False,
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

            ── ONE-SHOT tasks (runs ONCE then auto-deletes) ──
            Use « @once <ISO8601> » — NOT a day+month cron (a day+month cron
            would silently RE-FIRE every year).
              '@once 2026-05-14T08:00'   once, 8 am on May 14th 2026
              '@once 2026-12-27T09:30'   once, 9:30 am on December 27th 2026

            ⚠️ « Dans X jours ouvrés », « la semaine prochaine », « demain
            matin » must be converted to an ABSOLUTE date BEFORE building the
            « @once » expression. Use the current date (provided at the top of
            your prompt) and SKIP Saturdays / Sundays when counting « jours
            ouvrés ». Example for « dans 3 jours ouvrés à 8h » starting from a
            Monday: Tue=1, Wed=2, Thu=3 → '@once <Thu-date>T08:00'.

        channel: 'web' (default — browser notification + accumulated in the
            « Missions » tab) or 'telegram' (Telegram message via the
            linked bot).
        as_mission: True when the work is LONG (dozens of tool calls, e.g.
            sorting a whole mailbox, a prospection run) : at the scheduled
            time the task creates and starts a MISSION with `prompt` as its
            goal, instead of running it in a single chat turn. The mission
            has its own logbook, budgets and wake-ups. Keep False for short
            recurring jobs (briefing, reminder, quick check).
    """
    _expr = cron_expression.strip()
    if _expr.lower().startswith("@once"):
        # One-shot (J2) : « @once 2026-05-14T08:00 » → DateTrigger, runs once
        # then auto-deletes. Validate the ISO date here (croniter rejects it).
        _iso = _expr[len("@once"):].strip()
        try:
            from datetime import datetime as _dt
            _dt.fromisoformat(_iso)
        except Exception:
            return (
                f"Date one-shot invalide : '{cron_expression}'. "
                "Format attendu : @once 2026-05-14T08:00 (ISO 8601)."
            )
    else:
        from croniter import croniter
        if not croniter.is_valid(cron_expression):
            return (
                f"Expression invalide : '{cron_expression}'. Cron récurrent "
                "(minute heure jour mois jour_semaine) ou one-shot "
                "« @once 2026-05-14T08:00 »."
            )

    task = ScheduledTask(
        user_id=user_id,
        name=name,
        prompt=prompt,
        cron_expression=cron_expression,
        channel=channel,
        as_mission=bool(as_mission),
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
        + ("Mode : mission (carnet, budgets, passages)\n" if as_mission else "")
        + f"Prompt : {prompt}\n"
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


def _validate_schedule_expr(expr: str) -> str | None:
    """Return an error message if ``expr`` is neither a valid 5-field cron
    nor a valid « @once <ISO8601> » one-shot; None if valid."""
    e = expr.strip()
    if e.lower().startswith("@once"):
        iso = e[len("@once"):].strip()
        try:
            from datetime import datetime as _dt
            _dt.fromisoformat(iso)
            return None
        except Exception:
            return (
                f"Date one-shot invalide : '{expr}'. "
                "Format attendu : @once 2026-05-14T08:00 (ISO 8601)."
            )
    from croniter import croniter
    if not croniter.is_valid(e):
        return (
            f"Expression invalide : '{expr}'. Cron récurrent "
            "(minute heure jour mois jour_semaine) ou one-shot "
            "« @once 2026-05-14T08:00 »."
        )
    return None


@tool
async def scheduler_update_task(
    task_id: str,
    name: str | None = None,
    prompt: str | None = None,
    cron_expression: str | None = None,
    channel: str | None = None,
    enabled: bool | None = None,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Modify an existing scheduled task without deleting + recreating it.

    Only the fields you pass are changed (the rest keep their current value).
    Use this to fix a wrong time, reword the prompt, pause/resume a task, or
    switch its delivery channel.

    Args:
        task_id: The task ID to update (from scheduler_list_tasks).
        name: New name (optional).
        prompt: New natural-language instruction (optional).
        cron_expression: New schedule — 5-field cron OR « @once <ISO8601> »
            (optional).
        channel: New delivery channel, 'web' or 'telegram' (optional).
        enabled: Set False to pause the task, True to resume it (optional).
    """
    if cron_expression is not None:
        err = _validate_schedule_expr(cron_expression)
        if err:
            return err

    async with async_session() as db:
        task = (await db.execute(
            select(ScheduledTask).where(
                ScheduledTask.id == task_id,
                ScheduledTask.user_id == user_id,
            )
        )).scalar_one_or_none()
        if not task:
            return "Tâche non trouvée."

        if name is not None:
            task.name = name
        if prompt is not None:
            task.prompt = prompt
        if cron_expression is not None:
            task.cron_expression = cron_expression
        if channel is not None:
            task.channel = channel
        if enabled is not None:
            task.enabled = enabled
        await db.commit()
        await db.refresh(task)
        is_enabled = task.enabled
        cron = task.cron_expression
        nm = task.name

    # Re-register with the running scheduler to reflect the change.
    if is_enabled:
        if not schedule_task(task):
            return f"Tâche mise à jour mais planification invalide : '{cron}'."
    else:
        unschedule_task(task_id)

    state = "actif" if is_enabled else "en pause"
    return f"Tâche '{nm}' mise à jour ({state}) — planification : {cron}."


@tool
async def scheduler_run_task(
    task_id: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Run a scheduled task NOW, once, in the background (without waiting for
    its next scheduled time). The task's normal schedule is unchanged.

    Args:
        task_id: The task ID to run now (from scheduler_list_tasks).
    """
    async with async_session() as db:
        task = (await db.execute(
            select(ScheduledTask).where(
                ScheduledTask.id == task_id,
                ScheduledTask.user_id == user_id,
            )
        )).scalar_one_or_none()
        if not task:
            return "Tâche non trouvée."
        nm = task.name

    from app.services.background_tasks import spawn
    from app.services.scheduler import _execute_task
    spawn(_execute_task(task_id), label=f"run-now-{task_id}")
    return f"Tâche '{nm}' lancée maintenant (en arrière-plan)."
