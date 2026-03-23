"""Watchdog CRUD API — manage URL/query monitoring tasks."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.watch_task import WatchTask
from app.services.watchdog_service import schedule_watch_task, unschedule_watch_task

router = APIRouter()


class WatchTaskCreate(BaseModel):
    name: str
    watch_type: str = "url"  # "url" or "search"
    target: str
    check_interval_minutes: int = 60
    notify_channel: str = "web"


class WatchTaskUpdate(BaseModel):
    enabled: bool | None = None
    check_interval_minutes: int | None = None
    notify_channel: str | None = None


@router.get("/")
async def list_watch_tasks(current_user=Depends(get_current_user)):
    async with async_session() as db:
        result = await db.execute(
            select(WatchTask).where(WatchTask.user_id == current_user.id)
        )
        tasks = result.scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "watch_type": t.watch_type,
            "target": t.target,
            "check_interval_minutes": t.check_interval_minutes,
            "notify_channel": t.notify_channel,
            "enabled": t.enabled,
            "last_checked_at": t.last_checked_at,
            "last_content_preview": t.last_content_preview,
            "change_count": t.change_count,
            "created_at": t.created_at,
        }
        for t in tasks
    ]


@router.post("/")
async def create_watch_task(
    data: WatchTaskCreate,
    current_user=Depends(get_current_user),
):
    task = WatchTask(
        user_id=current_user.id,
        name=data.name,
        watch_type=data.watch_type,
        target=data.target,
        check_interval_minutes=data.check_interval_minutes,
        notify_channel=data.notify_channel,
    )
    async with async_session() as db:
        db.add(task)
        await db.commit()
        await db.refresh(task)
    schedule_watch_task(task)
    return {"id": task.id, "name": task.name}


@router.put("/{task_id}")
async def update_watch_task(
    task_id: str,
    data: WatchTaskUpdate,
    current_user=Depends(get_current_user),
):
    async with async_session() as db:
        result = await db.execute(
            select(WatchTask).where(
                WatchTask.id == task_id, WatchTask.user_id == current_user.id
            )
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "Task not found")
        if data.enabled is not None:
            task.enabled = data.enabled
        if data.check_interval_minutes is not None:
            task.check_interval_minutes = data.check_interval_minutes
        if data.notify_channel is not None:
            task.notify_channel = data.notify_channel
        await db.commit()
        await db.refresh(task)
    if task.enabled:
        schedule_watch_task(task)
    else:
        unschedule_watch_task(task_id)
    return {"id": task.id, "enabled": task.enabled}


@router.delete("/{task_id}")
async def delete_watch_task(
    task_id: str,
    current_user=Depends(get_current_user),
):
    async with async_session() as db:
        result = await db.execute(
            select(WatchTask).where(
                WatchTask.id == task_id, WatchTask.user_id == current_user.id
            )
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "Task not found")
        await db.delete(task)
        await db.commit()
    unschedule_watch_task(task_id)
    return {"deleted": True}
