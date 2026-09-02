# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/missions.py
# @brief      REST API for the goal-driven Persistence Loop
# =============================================================================
"""REST API for the goal-driven Persistence Loop.

Endpoints :
  POST   /api/missions                         → create a mission (status=draft)
  GET    /api/missions                         → list user's missions
  GET    /api/missions/{id}                    → mission detail
  GET    /api/missions/{id}/steps              → audit trail
  GET    /api/missions/{id}/plan               → latest plan version
  POST   /api/missions/{id}/start              → draft|paused → planning + first tick
  POST   /api/missions/{id}/pause              → running → paused
  POST   /api/missions/{id}/abort              → kill switch (any → aborted)
  POST   /api/missions/{id}/tick               → manual tick (debug / testing)

PHASE 1 SCOPE — endpoints exist and return real DB data. The /start and
/tick paths run the SKELETON graph (returns a synthetic success). PHASE 2
will replace the graph nodes with real reasoning while keeping these
endpoints unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import mission_service

router = APIRouter(prefix="/api/missions", tags=["missions"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

class MissionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    goal: str = Field(..., min_length=5)
    priority: int = Field(5, ge=1, le=10)
    budget_tokens: int = Field(50_000, ge=1000, le=500_000)
    budget_iterations: int = Field(30, ge=1, le=200)
    tick_interval_seconds: Optional[int] = Field(None, ge=30, le=86_400)
    deadline: Optional[datetime] = None
    autonomous: bool = False
    # Sprint 4c J1 — spec structurée V2 (YAML : steps + foreach + handlers
    # on_*). None = mission legacy prompt-monolithe. Validée à la création :
    # 422 avec la liste COMPLÈTE des erreurs du parser.
    spec_yaml: Optional[str] = Field(None, max_length=64_000)


class MissionUpdate(BaseModel):
    """Editable mission fields — all optional, only provided ones change.

    Allowed only when the mission is NOT actively executing (see
    ``_EDIT_BLOCKED_STATES``). Lets the user fix the goal, bump the
    iteration budget, change the tick schedule, etc. and re-run, instead
    of delete + recreate.
    """

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    goal: Optional[str] = Field(None, min_length=5)
    priority: Optional[int] = Field(None, ge=1, le=10)
    budget_tokens: Optional[int] = Field(None, ge=1000, le=500_000)
    budget_iterations: Optional[int] = Field(None, ge=1, le=200)
    tick_interval_seconds: Optional[int] = Field(None, ge=30, le=86_400)
    deadline: Optional[datetime] = None
    autonomous: Optional[bool] = None


class MissionOut(BaseModel):
    id: str
    title: str
    goal: str
    status: str
    priority: int
    source: str
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    deadline: Optional[datetime]
    budget_tokens: int
    budget_iterations: int
    tokens_used: int
    iterations_used: int
    tick_interval_seconds: Optional[int]
    next_tick_at: Optional[datetime]
    autonomous: bool
    final_summary: Optional[str]
    failure_reason: Optional[str]
    # Sprint 4c — None pour les missions legacy ; le viewer J4 s'en sert.
    spec_yaml: Optional[str] = None
    # J6 — mandat d'autonomie : état (pending_validation/active/paused_*) et
    # mandat sérialisé (JSON, parsé côté frontend pour le résumé/badge).
    autonomy_state: Optional[str] = None
    mandate_json: Optional[str] = None

    model_config = {"from_attributes": True}


class MissionWorkspaceOut(BaseModel):
    """Vue lecture seule du workspace d'une mission autonome (J6) : carnet de
    bord, queue du journal d'actions, compteurs journaliers (disjoncteurs)."""

    carnet: Optional[str] = None
    journal: list[dict] = Field(default_factory=list)
    counters: Optional[dict] = None


class MissionStepOut(BaseModel):
    id: str
    iteration: int
    phase: str
    thought: Optional[str]
    tool_name: Optional[str]
    tool_input: Optional[dict]
    tool_output: Optional[str]
    evaluation: Optional[str]
    success: Optional[bool]
    tokens_used: int
    duration_ms: int
    model_used: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class MissionPlanOut(BaseModel):
    id: str
    version: int
    plan_text: str
    plan_json: Optional[dict]
    reason_for_replan: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AbortBody(BaseModel):
    reason: str = "User-requested abort"


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.post("", response_model=MissionOut, status_code=status.HTTP_201_CREATED)
async def create_mission(
    body: MissionCreate,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    if body.spec_yaml and body.spec_yaml.strip():
        from app.config import get_settings
        from app.services.mission_spec import validate_mission_spec
        spec_errors = validate_mission_spec(
            body.spec_yaml,
            allow_mandate=get_settings().autonomous_missions_enabled,
        )
        if spec_errors:
            raise HTTPException(
                status_code=422,
                detail={"message": "Spec de mission invalide", "errors": spec_errors},
            )
    m = await mission_service.create_mission(
        user_id=current_user.id,
        title=body.title,
        goal=body.goal,
        spec_yaml=body.spec_yaml,
        priority=body.priority,
        source="ui",
        budget_tokens=body.budget_tokens,
        budget_iterations=body.budget_iterations,
        tick_interval_seconds=body.tick_interval_seconds,
        deadline=body.deadline,
        autonomous=body.autonomous,
    )
    return MissionOut.model_validate(m)


# Mission states where editing parameters is unsafe (it's actively running).
_EDIT_BLOCKED_STATES = {"planning", "running"}


@router.patch("/{mission_id}", response_model=MissionOut)
async def update_mission(
    mission_id: str,
    body: MissionUpdate,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    """Edit a mission's parameters (goal, budgets, tick schedule, …) without
    deleting + recreating it.

    Blocked while the mission is actively executing (planning/running) —
    pause it or wait for it to finish first (409). Only the fields present
    in the request body change. After editing, /restart (resets counters)
    then /start to re-run with the new params.
    """
    m = await _own_or_404(mission_id, current_user)
    if m.status in _EDIT_BLOCKED_STATES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Mission en cours ({m.status}) — mets-la en pause ou attends "
                "la fin avant de l'éditer."
            ),
        )

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return MissionOut.model_validate(m)

    from datetime import datetime as _dt, timezone as _tz

    from app.database import async_session
    from app.models.mission import Mission

    async with async_session() as db:
        fresh = await db.get(Mission, mission_id)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")
        for key, value in fields.items():
            setattr(fresh, key, value)
        fresh.updated_at = _dt.now(_tz.utc)
        await db.commit()
        await db.refresh(fresh)
        result = MissionOut.model_validate(fresh)

    from app.services.audit_log import audit
    await audit(
        current_user.id, "mission_edit",
        details=",".join(fields.keys())[:200], command=mission_id, channel="web",
    )
    return result


@router.get("", response_model=list[MissionOut])
async def list_missions(
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[MissionOut]:
    rows = await mission_service.list_missions_for_user(
        current_user.id, status=status_filter, limit=limit, offset=offset
    )
    return [MissionOut.model_validate(r) for r in rows]


@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(
    mission_id: str,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    return MissionOut.model_validate(m)


class StepRunOut(BaseModel):
    """Sprint 4c — statut d'un item de step structuré (viewer J4)."""
    step_id: str
    item_index: int
    item_value: Optional[str]
    status: str
    note: Optional[str]
    output: Optional[str]
    answer: Optional[str] = None  # J3 — réponse utilisateur (audit + viewer)
    attempts: int

    model_config = {"from_attributes": True}


class SpecStepOut(BaseModel):
    """Sprint 4c J4 — un step de la spec, pour l'outline du viewer."""
    id: str
    do: str
    foreach: Optional[str]
    handler_cases: list[str]


class MissionStructureOut(BaseModel):
    """Outline de la spec + statuts par item — UN appel pour le viewer."""
    steps: list[SpecStepOut]
    runs: list[StepRunOut]


@router.get("/{mission_id}/structure", response_model=MissionStructureOut)
async def mission_structure(
    mission_id: str,
    current_user: User = Depends(get_current_user),
) -> MissionStructureOut:
    """Sprint 4c J4 — la matière du viewer LISTE en un seul round-trip.

    ``steps`` = l'outline de la spec (TOUS les steps, y compris ceux pas
    encore touchés — le viewer montre le chemin complet) ; ``runs`` = les
    statuts par item (✓ done · ⏳ pending/running · ⏸ waiting_user ·
    ⊝ skipped · ✗ failed). Les deux listes vides pour une mission legacy.
    """
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")

    steps: list[SpecStepOut] = []
    if m.spec_yaml:
        from app.services.mission_spec import MissionSpecError, parse_mission_spec
        try:
            spec = parse_mission_spec(m.spec_yaml)
            steps = [
                SpecStepOut(
                    id=s.id, do=s.do, foreach=s.foreach,
                    handler_cases=sorted(s.handlers.keys()),
                )
                for s in spec.steps
            ]
        except MissionSpecError:
            steps = []  # spec corrompue en DB — le viewer dégrade en legacy

    from app.services.mission_spec_runtime import list_step_runs
    runs = await list_step_runs(mission_id)
    return MissionStructureOut(
        steps=steps,
        runs=[StepRunOut.model_validate(r) for r in runs],
    )


class StepRunAnswerIn(BaseModel):
    """Sprint 4c J3 — réponse de l'utilisateur à une question ask_user."""
    answer: str = Field(..., min_length=1, max_length=4000)


@router.post("/{mission_id}/step-runs/{step_id}/{item_index}/answer", response_model=StepRunOut)
async def answer_step_run(
    mission_id: str,
    step_id: str,
    item_index: int,
    body: StepRunAnswerIn,
    current_user: User = Depends(get_current_user),
) -> StepRunOut:
    """Sprint 4c J3 — répondre à une question posée par la mission.

    L'item ⏸ ``waiting_user`` repasse en ``pending`` avec la réponse
    (injectée au prompt acteur du prochain tick), tentatives remises à
    zéro, et la mission redevient due immédiatement — c'est le « mode
    chat fait à la main », automatisé : Ely hésite → question → réponse
    → reprise.
    """
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")

    from app.services.mission_spec_runtime import submit_answer
    run = await submit_answer(mission_id, step_id, item_index, body.answer)
    if run is None:
        raise HTTPException(
            status_code=409,
            detail="Cet item n'attend pas de réponse (déjà traité ou inexistant).",
        )
    return StepRunOut.model_validate(run)


@router.get("/{mission_id}/steps", response_model=list[MissionStepOut])
async def list_steps(
    mission_id: str,
    limit: int = 200,
    current_user: User = Depends(get_current_user),
) -> list[MissionStepOut]:
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    rows = await mission_service.list_steps(mission_id, limit=limit)
    return [MissionStepOut.model_validate(r) for r in rows]


@router.get("/{mission_id}/plan", response_model=Optional[MissionPlanOut])
async def get_latest_plan(
    mission_id: str,
    current_user: User = Depends(get_current_user),
):
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    p = await mission_service.get_latest_plan(mission_id)
    return MissionPlanOut.model_validate(p) if p else None


# ── State transitions ───────────────────────────────────────────────────────

async def _own_or_404(mission_id: str, user: User):
    m = await mission_service.get_mission(mission_id)
    if not m or m.user_id != user.id:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    return m


@router.post("/{mission_id}/activate", response_model=MissionOut)
async def activate_mission_mandate(
    mission_id: str, current_user: User = Depends(get_current_user),
) -> MissionOut:
    """J6 (D6) — validation HUMAINE du mandat : ``pending_validation →
    active``. C'est l'UNIQUE transition qui allume le moteur d'autonomie
    (enforcement J2, disjoncteurs J3, carnet J4, mode strict J5) ; la
    reprise (``/start``) ne couvre que ``paused_* → active``, mandat déjà
    validé. Le clic explicite dans l'UI — sur le résumé lisible du mandat —
    EST la validation ; Ely ne peut jamais modifier un mandat."""
    from app.config import get_settings
    if not get_settings().autonomous_missions_enabled:
        raise HTTPException(
            status_code=403,
            detail="Missions autonomes désactivées (AUTONOMOUS_MISSIONS_ENABLED).",
        )
    m = await _own_or_404(mission_id, current_user)
    if not m.mandate_json:
        raise HTTPException(status_code=400,
                            detail="Cette mission n'a pas de mandat d'autonomie.")
    if (m.autonomy_state or "") != "pending_validation":
        raise HTTPException(
            status_code=409,
            detail=f"Mandat non activable depuis l'état {m.autonomy_state!r}.",
        )
    await mission_service.set_autonomy_state(mission_id, "active")
    from app.services.audit_log import audit
    await audit(current_user.id, "mission_mandate_activated",
                details=(getattr(m, "title", None) or "")[:200],
                command=mission_id, channel="web")
    m = await mission_service.get_mission(mission_id)
    return MissionOut.model_validate(m)


@router.get("/{mission_id}/workspace", response_model=MissionWorkspaceOut)
async def get_mission_workspace(
    mission_id: str, current_user: User = Depends(get_current_user),
) -> MissionWorkspaceOut:
    """J6 — carnet de bord + queue du journal + compteurs du jour, pour le
    viewer. Lecture seule, vide proprement si la mission n'a pas de
    workspace (jamais activée / flag OFF)."""
    await _own_or_404(mission_id, current_user)
    from app.services import mission_workspace as ws
    from app.services.mission_budget import get_today

    try:
        carnet = ws.read_carnet(mission_id)
        journal = ws.read_journal_tail(mission_id, n=30)
    except Exception:  # noqa: BLE001 — id hostile ou FS indisponible → vide
        carnet, journal = None, []
    today = await get_today(mission_id)
    counters = None
    if today is not None:
        counters = {
            "day": today.day,
            "tool_actions": today.tool_actions,
            "llm_calls": today.llm_calls,
            "tool_ack": today.tool_ack,
            "llm_ack": today.llm_ack,
        }
    return MissionWorkspaceOut(carnet=carnet, journal=journal, counters=counters)


@router.post("/{mission_id}/start", response_model=MissionOut)
async def start(mission_id: str, current_user: User = Depends(get_current_user)) -> MissionOut:
    await _own_or_404(mission_id, current_user)
    try:
        m = await mission_service.start_mission(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Mark the mission for immediate pickup by the heartbeat loop.
    # Without this the heartbeat would wait `tick_interval_seconds` (or
    # forever for single-shot missions) before the first tick.
    from app.services.mission_heartbeat import schedule_first_tick
    await schedule_first_tick(mission_id)
    # Audit trail (mai 2026 — Admin → Logs visibility)
    from app.services.audit_log import audit
    await audit(current_user.id, "mission_start",
                details=(getattr(m, "title", None) or "")[:200],
                command=mission_id, channel="web")
    return MissionOut.model_validate(m)


@router.post("/{mission_id}/pause", response_model=MissionOut)
async def pause(mission_id: str, current_user: User = Depends(get_current_user)) -> MissionOut:
    await _own_or_404(mission_id, current_user)
    try:
        m = await mission_service.pause_mission(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.services.audit_log import audit
    await audit(current_user.id, "mission_pause",
                details=(getattr(m, "title", None) or "")[:200],
                command=mission_id, channel="web")
    return MissionOut.model_validate(m)


@router.post("/{mission_id}/abort", response_model=MissionOut)
async def abort(
    mission_id: str,
    body: AbortBody,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    await _own_or_404(mission_id, current_user)
    try:
        m = await mission_service.abort_mission(mission_id, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.services.audit_log import audit
    await audit(current_user.id, "mission_abort",
                details=(body.reason or "")[:200],
                command=mission_id, channel="web")
    return MissionOut.model_validate(m)


@router.post("/{mission_id}/tick", response_model=dict)
async def tick(mission_id: str, current_user: User = Depends(get_current_user)) -> dict:
    """Un réveil manuel de la mission (debug / bouton « Tick »).

    ⚠️ Passe par le MÊME aiguillage que le heartbeat (02/09/2026). Avant, cet
    endpoint compilait `build_mission_graph()` en dur : depuis que la mission
    libre tourne sur la boucle du chat, un Tick pressé lançait l'AUTRE moteur
    sur une mission qui n'est pas dessus.

    ⚠️ Et il prend `_in_flight`, le garde-fou par mission du heartbeat. Tant
    que les deux chemins étaient le même graphe sur le même checkpointer,
    leurs écritures se sérialisaient. Ce sont maintenant deux moteurs
    distincts : un Tick pressé pendant qu'un passage est en vol ferait
    tourner plan/act/eval EN PARALLÈLE, sur les mêmes `mission_steps` et le
    même `complete_mission`.
    """
    m = await _own_or_404(mission_id, current_user)
    if m.status in {"completed", "failed", "aborted"}:
        raise HTTPException(status_code=400, detail=f"Mission est en état terminal ({m.status})")

    # Budget guard
    reason = await mission_service.check_budget(mission_id)
    if reason:
        await mission_service.fail_mission(mission_id, reason)
        raise HTTPException(status_code=400, detail=f"Budget dépassé : {reason}")

    # ⚠️ 02/09/2026 — le budget LLM QUOTIDIEN du compte, distinct de celui de
    # la mission ci-dessus. Le heartbeat l'applique (mission_heartbeat.py,
    # A-6b) ; ce bouton ne l'appliquait pas, et il déclenche désormais un
    # passage COMPLET (plusieurs outils, plusieurs appels de modèle) là où il
    # ne lançait qu'un tour de graphe. Un Tick pressé sur un compte à sec
    # dépensait donc quand même. On refuse (429) au lieu de reporter : un
    # geste manuel n'a pas de `next_tick_at` à repousser, et la mission n'est
    # pas tuée — elle reprendra au prochain battement.
    from app.services.budget_guard import check_user_budget

    quotidien = await check_user_budget(current_user.id)
    if quotidien:
        raise HTTPException(
            status_code=429, detail=f"Budget quotidien épuisé : {quotidien}",
        )

    # Ensure status reflects we're working
    if m.status == "draft":
        try:
            await mission_service.start_mission(mission_id)
        except ValueError:
            pass

    from app.services.mission_heartbeat import (
        _est_passagere,
        _in_flight,
        _tick_one_mission,
    )

    # Prise SYNCHRONE (pas d'await entre le test et l'ajout), comme au
    # dispatch du heartbeat : c'est ce qui rend le garde-fou atomique.
    if mission_id in _in_flight:
        raise HTTPException(
            status_code=409,
            detail="Un passage de cette mission est déjà en cours.",
        )
    _in_flight.add(mission_id)
    try:
        try:
            result = await _tick_one_mission(mission_id, current_user.id, m.goal)
        except Exception as exc:
            logger.exception("Mission %s tick failed: %s", mission_id, exc)
            if _est_passagere(exc):
                # Une limite de débit n'est pas un bug de la mission : le
                # heartbeat REPORTE le tick au lieu de la tuer (c41d758). Un
                # Tick manuel ne doit pas faire pire, d'autant que le passage
                # vient de consigner au carnet ce qu'il avait déjà fait.
                raise HTTPException(
                    status_code=503, detail=f"Fournisseur indisponible : {exc}",
                )
            await mission_service.fail_mission(mission_id, f"graph error: {exc}")
            raise HTTPException(status_code=500, detail=f"Tick a échoué: {exc}")

        # Note : the nodes themselves persist MissionStep rows (plan/act/eval/replan).
        # We don't double-log here. We only handle the terminal transition.

        # If the graph signaled done, complete the mission
        #
        # ⚠️ 02/09/2026 — la clôture est DANS la portée de `_in_flight`. Le
        # heartbeat tient le garde-fou pendant tout `_process_one_mission`,
        # clôture comprise ; le relâcher avant `complete_mission` laissait une
        # fenêtre étroite mais réelle où un battement pouvait dépêcher un tick
        # neuf sur une mission en cours de clôture, sur les mêmes
        # `mission_steps`.
        if result.get("done") and result.get("final_summary"):
            try:
                await mission_service.complete_mission(mission_id, result["final_summary"])
            except ValueError:
                # already terminal, ignore
                pass
    finally:
        _in_flight.discard(mission_id)

    return {
        "iteration": result.get("iteration"),
        "plan_version": result.get("plan_version"),
        "done": bool(result.get("done")),
        "final_summary": result.get("final_summary"),
        "last_eval_success": result.get("last_eval_success"),
    }


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    mission_id: str,
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a mission, its plan and its steps.

    Allowed regardless of mission state — useful for cleaning up failed
    missions stuck in the list (e.g. after a code-level crash like the
    `langgraph.checkpoint.sqlite` import error of April 2026). The mission's
    LangGraph checkpoint state is also cleared via thread_id.
    """
    m = await _own_or_404(mission_id, current_user)

    # Remove any LangGraph checkpoint persisted under this mission's thread_id
    # so a future mission with the same id doesn't inherit stale state. This
    # is best-effort — failures here don't block the DB delete.
    try:
        from app.agent.missions.graph import build_mission_graph
        graph = build_mission_graph()
        config = {"configurable": {"thread_id": mission_id}}
        # AsyncSqliteSaver exposes adelete_thread on recent versions
        ckpt = getattr(graph, "checkpointer", None)
        if ckpt is not None and hasattr(ckpt, "adelete_thread"):
            try:
                await ckpt.adelete_thread(mission_id)
            except Exception:
                pass
    except Exception:
        pass

    # ⚠️ TOUTES les tables filles, pas seulement celles qu'on a en tête.
    #
    # Cinq tables portent une FK vers `missions`. Quatre déclarent
    # ON DELETE CASCADE, `mission_daily_counters` non — et c'est justement
    # celle qui manquait ici. Résultat (28/08/2026) : « FOREIGN KEY
    # constraint failed », HTTP 500, mission impossible à supprimer depuis
    # l'interface dès qu'elle avait consommé un quota journalier.
    #
    # On les supprime explicitement plutôt que de s'en remettre au CASCADE :
    # il dépend de `PRAGMA foreign_keys`, qui n'est pas garanti sur tous les
    # chemins d'accès. Une suppression explicite ne dépend, elle, de rien.
    from app.database import async_session
    from app.models.mission import (
        Mission, MissionDailyCounter, MissionPlan, MissionStep, MissionStepRun,
    )
    from app.models.mission_critique import MissionCritique
    from sqlalchemy import delete as _sqldel
    async with async_session() as db:
        for _modele in (
            MissionStep, MissionPlan, MissionStepRun,
            MissionCritique, MissionDailyCounter,
        ):
            await db.execute(
                _sqldel(_modele).where(_modele.mission_id == mission_id)
            )
        await db.execute(_sqldel(Mission).where(Mission.id == mission_id))
        await db.commit()
    return None  # 204 No Content


class _RestartBody(BaseModel):
    """Optional fresh budgets for the restarted mission."""
    max_iterations: int | None = None
    max_tokens: int | None = None
    keep_history: bool = False  # if False (default) plan + steps wiped, if True kept


@router.post("/{mission_id}/restart", response_model=MissionOut)
async def restart(
    mission_id: str,
    body: _RestartBody | None = None,
    current_user: User = Depends(get_current_user),
) -> MissionOut:
    """Reset a mission to ``draft`` status so it can be started again.

    Useful when a mission failed (e.g. due to a transient bug like a missing
    Python module) and the user wants to retry without re-typing the title +
    goal + budgets.

    Default behaviour : wipe plan history + steps so the next ``start`` produces
    a fresh plan. Pass ``keep_history=true`` if you want the previous plan
    kept for reference (rare).
    """
    body = body or _RestartBody()
    m = await _own_or_404(mission_id, current_user)

    from app.database import async_session
    from app.models.mission import Mission, MissionPlan, MissionStep, MissionStepRun
    from sqlalchemy import delete as _sqldel
    from datetime import datetime, timezone

    async with async_session() as db:
        if not body.keep_history:
            await db.execute(_sqldel(MissionStep).where(MissionStep.mission_id == mission_id))
            await db.execute(_sqldel(MissionPlan).where(MissionPlan.mission_id == mission_id))
            # `mission_step_runs` porte l'état par ITEM : statut terminal,
            # note, sortie archivée, compteur de tentatives. L'oublier ici
            # faisait hériter une mission relancée des verdicts de la
            # précédente (30/08/2026) — un `foreach` dont l'unique item avait
            # été `skipped` la veille était rendu tel quel par
            # `expand_foreach`, idempotent et silencieux : l'étape sautait en
            # 0,1 s, sans action ni ligne de journal.
            await db.execute(
                _sqldel(MissionStepRun).where(MissionStepRun.mission_id == mission_id)
            )

        fresh = await db.get(Mission, mission_id)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Mission not found")

        fresh.status = "draft"
        fresh.failure_reason = None
        fresh.iterations_used = 0
        fresh.tokens_used = 0
        fresh.started_at = None
        fresh.completed_at = None
        fresh.next_tick_at = None
        fresh.final_summary = None
        fresh.updated_at = datetime.now(timezone.utc)
        if body.max_iterations is not None:
            fresh.budget_iterations = max(1, body.max_iterations)
        if body.max_tokens is not None:
            fresh.budget_tokens = max(100, body.max_tokens)
        await db.commit()
        await db.refresh(fresh)

    # Also wipe the LangGraph checkpoint so the next start doesn't replay
    # the previous terminal state. Without this, a mission that had reached
    # 'completed' in its checkpoint will be re-marked completed on the very
    # first tick after restart (no real work performed). The previous
    # implementation called `build_mission_graph()` without compiling, which
    # always returned `checkpointer=None` — so the deletion never ran.
    try:
        from app.agent.missions.checkpointer import get_mission_checkpointer
        cp = await get_mission_checkpointer()
        if cp is not None and hasattr(cp, "adelete_thread"):
            await cp.adelete_thread(mission_id)
            logger.info("Mission checkpoint wiped for %s", mission_id[:8])
    except Exception as _exc:
        logger.warning("Mission checkpoint wipe failed for %s: %s", mission_id[:8], _exc)

    return MissionOut.model_validate(fresh)
