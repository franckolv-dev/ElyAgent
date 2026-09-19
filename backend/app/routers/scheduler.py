# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/scheduler.py
# @brief      Scheduler API — CRUD for scheduled tasks.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
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
    # Défaut FAUX : une tâche qui n'a rien demandé livre toujours son
    # résultat. Seule une tâche de VEILLE peut se taire (révision 0033).
    allow_silent: bool = False
    # Lancer une MISSION à l'heure dite plutôt qu'un tour de chat (0036).
    as_mission: bool = False


class TaskUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    cron_expression: str | None = None
    channel: str | None = None
    enabled: bool | None = None
    allow_silent: bool | None = None
    as_mission: bool | None = None


class PromptPatchOut(BaseModel):
    """Une réécriture de consigne, proposée ou appliquée, avec son avant/après."""

    id: int
    status: str            # proposed | applied | rejected | reverted
    old_value: str | None
    new_value: str
    rationale: str | None
    applied_at: str | None


def _patch_out(p) -> PromptPatchOut:
    return PromptPatchOut(
        id=p.id, status=p.status, old_value=p.old_value, new_value=p.new_value,
        rationale=p.rationale,
        applied_at=p.applied_at.isoformat() if p.applied_at else None,
    )


class TaskResponse(BaseModel):
    id: str
    name: str
    prompt: str
    cron_expression: str
    channel: str
    enabled: bool
    last_run_at: str | None
    last_result: str | None
    # "running" | "success" | "error" | "silent" | "missed" | None.
    # "missed" = occurrence due, trop ancienne pour la fenêtre de
    # rattrapage : elle ne sera PAS rejouée.
    last_status: str | None
    allow_silent: bool = False
    as_mission: bool = False
    last_run_started_at: str | None
    created_at: str
    # Verdict de la dernière exécution jugée : "succeeded" | "dubious" | "failed".
    # Une tâche peut se déclarer « success » et n'avoir rien écrit.
    last_outcome: str | None = None
    # La fiche propose « Améliorer la consigne » quand la dernière exécution
    # est en erreur, ou jugée douteuse / échouée.
    needs_attention: bool = False
    prompt_patch: PromptPatchOut | None = None

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

    from app.models.execution_outcome import ExecutionOutcome
    from app.services.learning.patch_service import patches_for_tasks

    ids = [t.id for t in tasks]
    verdicts: dict[str, str] = {}
    if ids:
        lignes = (await db.execute(
            select(ExecutionOutcome.source_id, ExecutionOutcome.outcome)
            .where(
                ExecutionOutcome.user_id == user.id,
                ExecutionOutcome.source == "scheduled",
                ExecutionOutcome.source_id.in_(ids),
            )
            .order_by(ExecutionOutcome.created_at.desc(), ExecutionOutcome.id.desc())
        )).all()
        for source_id, outcome in lignes:  # premier vu = le plus récent
            verdicts.setdefault(source_id, outcome)
    correctifs = await patches_for_tasks(db, user.id, ids)
    # Un correctif appliqué puis retouché à la main n'est plus annulable : il
    # quitte la fiche au lieu d'y rester sans action possible.
    return [
        _to_response(
            t, last_outcome=verdicts.get(t.id),
            patch=(p if (p := correctifs.get(t.id)) is not None and (
                p.status == "proposed" or t.prompt == p.new_value) else None),
        )
        for t in tasks
    ]


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
        allow_silent=body.allow_silent,
        as_mission=body.as_mission,
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
    if body.allow_silent is not None:
        task.allow_silent = body.allow_silent
    if body.as_mission is not None:
        task.as_mission = body.as_mission

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
    backend's LLM instance cache, skill registry, and Telegram bot
    connection — unlike a `docker exec` Python script which would
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


# ──────────────────────────────────────────────────────────────────────
# « Améliorer la consigne » — à la demande, depuis la fiche de la tâche
# ──────────────────────────────────────────────────────────────────────
#
# C'est ce qui reste de la page « Incidents & propositions » (19/09/2026) :
# plus de diagnostic systématique ni de liste à trancher, une réécriture que
# l'on demande quand une tâche ne fait pas ce qu'on attend, avec son avant /
# après, applicable et annulable.


async def _appeler(operation, *args):
    from app.services.learning.patch_service import PatchError

    try:
        return _patch_out(await operation(*args))
    except PatchError as exc:
        introuvable = "introuvable" in str(exc)
        raise HTTPException(404 if introuvable else 409, str(exc))


@router.post("/{task_id}/improve-prompt", response_model=PromptPatchOut)
async def improve_prompt(task_id: str, user: User = Depends(get_current_user)):
    """Propose une réécriture de la consigne. N'applique rien."""
    from app.services.learning.patch_service import propose_for_task

    return await _appeler(propose_for_task, task_id, user.id)


@router.post("/prompt-patches/{patch_id}/apply", response_model=PromptPatchOut)
async def apply_prompt_patch(patch_id: int, user: User = Depends(get_current_user)):
    from app.services.learning.patch_service import apply_patch

    return await _appeler(apply_patch, patch_id, user.id)


@router.post("/prompt-patches/{patch_id}/revert", response_model=PromptPatchOut)
async def revert_prompt_patch(patch_id: int, user: User = Depends(get_current_user)):
    from app.services.learning.patch_service import revert_patch

    return await _appeler(revert_patch, patch_id, user.id)


@router.post("/prompt-patches/{patch_id}/reject", response_model=PromptPatchOut)
async def reject_prompt_patch(patch_id: int, user: User = Depends(get_current_user)):
    from app.services.learning.patch_service import reject_patch

    return await _appeler(reject_patch, patch_id, user.id)


def _to_response(task: ScheduledTask, *, last_outcome: str | None = None,
                 patch=None) -> TaskResponse:
    return TaskResponse(
        last_outcome=last_outcome,
        needs_attention=(task.last_status == "error"
                         or last_outcome in ("dubious", "failed")),
        prompt_patch=_patch_out(patch) if patch is not None else None,
        id=task.id,
        name=task.name,
        prompt=task.prompt,
        cron_expression=task.cron_expression,
        channel=task.channel,
        enabled=task.enabled,
        last_run_at=task.last_run_at.isoformat() if task.last_run_at else None,
        last_result=task.last_result,
        last_status=task.last_status,
        allow_silent=bool(task.allow_silent),
        as_mission=bool(getattr(task, "as_mission", False)),
        last_run_started_at=(
            task.last_run_started_at.isoformat() if task.last_run_started_at else None
        ),
        created_at=task.created_at.isoformat(),
    )
