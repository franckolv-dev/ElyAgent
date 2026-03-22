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
    await db.commit()
    await db.refresh(task)

    if not schedule_task(task):
        raise HTTPException(
            status_code=400,
            detail=f"Expression cron invalide : '{body.cron_expression}'. "
                   "Format attendu : minute heure jour mois jour_semaine (ex: '0 8 * * 1-5')"
        )

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
        created_at=task.created_at.isoformat(),
    )
