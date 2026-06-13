# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/scheduler.py
# @brief      Scheduler API — CRUD for scheduled tasks.
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
"""Scheduler API — CRUD for scheduled tasks."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.scheduled_task import ScheduledTask
from app.services.scheduler import schedule_task, unschedule_task

router = APIRouter()


class TaskCreate(BaseModel):
    name: str
    prompt: str
    cron_expression: str  # "0 8 * * 1-5"
    channel: str = "web"  # "web" | "telegram"


class TaskUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    cron_expression: str | None = None
    channel: str | None = None
    enabled: bool | None = None


class TaskResponse(BaseModel):
    id: str
    name: str
    prompt: str
    cron_expression: str
    channel: str
    enabled: bool
    last_run_at: str | None
    last_result: str | None
    last_status: str | None       # "running" | "success" | "error" | None
    last_run_started_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[TaskResponse])
async def list_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScheduledTask)
        .where(ScheduledTask.user_id == user.id)
        .order_by(ScheduledTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [_to_response(t) for t in tasks]


@router.post("/", response_model=TaskResponse)
async def create_task(
    body: TaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = ScheduledTask(
        user_id=user.id,
        name=body.name,
        prompt=body.prompt,
        cron_expression=body.cron_expression,
        channel=body.channel,
    )
    db.add(task)
    await db.flush()

    if not schedule_task(task):
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Expression cron invalide : '{body.cron_expression}'. "
                   "Format attendu : minute heure jour mois jour_semaine (ex: '0 8 * * 1-5')"
        )

    await db.commit()
    await db.refresh(task)
    return _to_response(task)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    body: TaskUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScheduledTask).where(
            ScheduledTask.id == task_id,
            ScheduledTask.user_id == user.id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")

    if body.name is not None:
        task.name = body.name
    if body.prompt is not None:
        task.prompt = body.prompt
    if body.cron_expression is not None:
        task.cron_expression = body.cron_expression
    if body.channel is not None:
        task.channel = body.channel
    if body.enabled is not None:
        task.enabled = body.enabled

    await db.commit()
    await db.refresh(task)

    if task.enabled:
        schedule_task(task)
    else:
        unschedule_task(task.id)

    return _to_response(task)


@router.post("/{task_id}/run")
async def run_task_now(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scheduled task immediately, out-of-band.

    Useful to (a) verify a task works without waiting for its cron tick,
    (b) get a fresh result on demand. Runs IN-PROCESS so it shares the
    backend's LLM instance cache, skill registry, and Telegram/Slack
    bot connections — unlike a `docker exec` Python script which would
    spawn a fresh process with empty caches.
    """
    result = await db.execute(
        select(ScheduledTask).where(
            ScheduledTask.id == task_id,
            ScheduledTask.user_id == user.id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")

    # Fire-and-forget : the task can take 30+ s to complete (LLM call +
    # tool dispatch + delivery), don't block the HTTP response. Track the
    # task in a module-level set so Python's GC doesn't kill it mid-flight.
    import asyncio as _asyncio
    from app.services.scheduler import _execute_task
    _t = _asyncio.create_task(_execute_task(task.id))
    _RUN_NOW_TASKS.add(_t)
    _t.add_done_callback(_RUN_NOW_TASKS.discard)

    return {"message": f"Tâche '{task.name}' déclenchée — résultat livré via {task.channel} dès qu'elle se termine."}


# Strong refs to in-flight manual-trigger tasks. See run_task_now().
_RUN_NOW_TASKS: set = set()


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScheduledTask).where(
            ScheduledTask.id == task_id,
            ScheduledTask.user_id == user.id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")

    unschedule_task(task.id)
    await db.delete(task)
    await db.commit()
    return {"message": f"Tâche '{task.name}' supprimée"}


def _to_response(task: ScheduledTask) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        name=task.name,
        prompt=task.prompt,
        cron_expression=task.cron_expression,
        channel=task.channel,
        enabled=task.enabled,
        last_run_at=task.last_run_at.isoformat() if task.last_run_at else None,
        last_result=task.last_result,
        last_status=task.last_status,
        last_run_started_at=(
            task.last_run_started_at.isoformat() if task.last_run_started_at else None
        ),
        created_at=task.created_at.isoformat(),
    )
