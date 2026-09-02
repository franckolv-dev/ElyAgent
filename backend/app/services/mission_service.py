# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_service.py
# @brief      Mission CRUD + lifecycle helpers
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Mission CRUD + lifecycle helpers.

Thin wrapper around the ORM that the rest of the codebase (router,
mission_graph, scheduler) uses to manipulate missions without touching
SQLAlchemy directly. Keeps state-machine transitions in one place.

Design notes :
  - All transition methods (`start`, `pause`, `complete`, `fail`, `abort`)
    validate the source status to prevent illegal moves
    (e.g. you can't `complete` a `draft` — it must go through `running`).
  - Budget guards live HERE, not in the LangGraph nodes — keeps the graph
    pure (each node just runs, the supervisor decides when to stop).
  - Never log the full goal text in INFO logs — goals can contain emails,
    phone numbers, internal project names. Only IDs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.services.mission_spec import MissionMandate

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.mission import (
    Mission, MissionPlan, MissionStep,
    MISSION_STATUSES, MISSION_TERMINAL_STATUSES, MISSION_SOURCES, STEP_PHASES,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Creation ─────────────────────────────────────────────────────────────────

async def create_mission(
    user_id: str,
    title: str,
    goal: str,
    *,
    priority: int = 5,
    source: str = "ui",
    source_ref: Optional[str] = None,
    budget_tokens: int = 50_000,
    budget_iterations: int = 30,
    tick_interval_seconds: Optional[int] = None,
    deadline: Optional[datetime] = None,
    autonomous: bool = False,
    spec_yaml: Optional[str] = None,
) -> Mission:
    """Create a new mission in `draft` status.

    ``spec_yaml`` (Sprint 4c J1) : spec structurée V2 — validée ICI aussi
    (défense en profondeur, le router valide déjà) pour que les autres
    sources (Telegram, scheduler) ne puissent pas persister une spec
    invalide.
    """
    if source not in MISSION_SOURCES:
        raise ValueError(f"invalid source: {source!r}")
    mandate_json: Optional[str] = None
    autonomy_state: Optional[str] = None
    if spec_yaml is not None and spec_yaml.strip():
        from app.services.mission_spec import (
            MissionSpecError,
            mandate_to_json,
            parse_mission_spec,
        )
        try:
            spec = parse_mission_spec(spec_yaml)
        except MissionSpecError as exc:
            raise ValueError(f"spec invalide : {exc}") from exc
        if spec.mandate is not None:
            from app.config import get_settings
            if not get_settings().autonomous_missions_enabled:
                # Défense en profondeur : le router gate déjà, mais les
                # sources non-UI (Telegram, scheduler) passent par ici.
                raise ValueError(
                    "spec invalide : mandate : missions autonomes désactivées "
                    "(flag autonomous_missions_enabled)"
                )
            mandate_json = mandate_to_json(spec.mandate)
            autonomy_state = "pending_validation"
    else:
        spec_yaml = None

    mission = Mission(
        user_id=user_id,
        title=title.strip()[:255] or "Sans titre",
        goal=goal.strip(),
        status="draft",
        priority=priority,
        source=source,
        source_ref=source_ref,
        budget_tokens=budget_tokens,
        budget_iterations=budget_iterations,
        tick_interval_seconds=tick_interval_seconds,
        deadline=deadline,
        autonomous=autonomous,
        spec_yaml=spec_yaml,
        mandate_json=mandate_json,
        autonomy_state=autonomy_state,
    )
    async with async_session() as db:
        db.add(mission)
        await db.commit()
        await db.refresh(mission)
    logger.info("Mission created id=%s user=%s priority=%d", mission.id, user_id, priority)
    return mission


# ── State transitions ───────────────────────────────────────────────────────

async def _transition(mission_id: str, *, from_: set[str], to: str, **fields) -> Mission:
    """Atomic status transition with optimistic source-status check.

    Raises ValueError if the mission isn't in one of the allowed `from_`
    states (prevents illegal transitions like complete→draft).
    """
    async with async_session() as db:
        m = (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()
        if not m:
            raise ValueError(f"mission {mission_id!r} not found")
        if m.status not in from_:
            raise ValueError(
                f"cannot transition mission {mission_id!r} from status {m.status!r} to {to!r}"
            )
        m.status = to
        for k, v in fields.items():
            setattr(m, k, v)
        await db.commit()
        await db.refresh(m)
        logger.info("Mission %s: %s → %s", mission_id, [s for s in from_][0] if len(from_) == 1 else "(any)", to)
        return m


async def start_mission(mission_id: str) -> Mission:
    """draft|paused → planning. Marks `started_at` if first start."""
    fields = {}
    async with async_session() as db:
        m = (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()
        if m and m.started_at is None:
            fields["started_at"] = _utcnow()
    started = await _transition(mission_id, from_={"draft", "paused"}, to="planning", **fields)
    # Missions autonomes J3 — reprise : une mission dont le mandat était en
    # pause (disjoncteur…) repart en autonomie. Les compteurs du jour restent
    # INTACTS (la reprise n'est pas une remise à zéro) ; le snapshot
    # autonomy_pause_json est conservé comme trace (CARNET J4).
    if (started.autonomy_state or "").startswith("paused"):
        await set_autonomy_state(mission_id, "active")
        started.autonomy_state = "active"
    return started


async def mark_running(mission_id: str) -> Mission:
    """planning → running (first plan finalized)."""
    return await _transition(mission_id, from_={"planning"}, to="running")


async def pause_mission(mission_id: str) -> Mission:
    """running|planning → paused."""
    return await _transition(mission_id, from_={"running", "planning"}, to="paused")


def _spawn_mission_outcome(m: Mission, declared_status: str) -> None:
    """Boucle d'auto-diagnostic — verdict d'aboutissement réel d'une mission,
    signaux faibles inclus (réussi sans effet observable, fallback…). L'analyse
    + la persistance sont déléguées à ``outcome_recording`` (best-effort,
    fire-and-forget : ne bloque ni ne casse la transition de statut)."""
    from app.services.background_tasks import spawn
    from app.services.learning.outcome_recording import record_mission_outcome
    spawn(
        record_mission_outcome(
            mission_id=m.id, user_id=m.user_id, declared_status=declared_status,
        ),
        label=f"exec-outcome-mission-{m.id}",
    )


def _spawn_lessons_promotion(m: Mission) -> None:
    """Missions autonomes J4 — promotion des leçons du CARNET.md en mémoire
    durable (fait sémantique, cherchable par ``memory_recall``) quand une
    mission mandatée se termine. Best-effort, fire-and-forget.

    Périmètre assumé : le ProceduralStore V1 est un stub sans voie
    d'écriture (moisson Sprint 2.5 jamais livrée) — on promeut via
    ``store_memory`` ; la vraie voie PROCEDURAL reste une dette séparée."""
    if not m.mandate_json:
        return
    try:
        from app.services.mission_workspace import extract_section
        lessons = extract_section(m.id, "Leçons")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Leçons de %s illisibles : %s", m.id, exc)
        return
    if not lessons.strip():
        return
    from app.services.background_tasks import spawn
    from app.services.memory_manager import get_memory_manager
    spawn(
        get_memory_manager().store_memory(
            f"Leçons de la mission « {m.title} » : {lessons}",
            m.user_id,
            extra_payload={"source": "mission_carnet", "mission_id": m.id},
        ),
        label=f"carnet-lessons-{m.id}",
    )


async def complete_mission(mission_id: str, summary: str) -> Mission:
    """planning|running → completed.

    Note : we accept `planning` because a mission can complete on its
    very first tick (the plan + first action achieves the goal in one
    iteration). Without this, the mission would be stuck reporting
    done=True forever in the heartbeat loop.
    """
    m = await _transition(
        mission_id, from_={"planning", "running"}, to="completed",
        completed_at=_utcnow(), final_summary=summary,
    )
    _spawn_mission_outcome(m, "completed")
    _spawn_lessons_promotion(m)
    return m


async def fail_mission(mission_id: str, reason: str) -> Mission:
    """any-non-terminal → failed."""
    m = await _transition(
        mission_id, from_={"draft", "planning", "running", "paused"}, to="failed",
        completed_at=_utcnow(), failure_reason=reason,
    )
    _spawn_mission_outcome(m, "failed")
    return m


async def abort_mission(mission_id: str, reason: str = "User-requested abort") -> Mission:
    """any-non-terminal → aborted (kill switch)."""
    m = await _transition(
        mission_id, from_={"draft", "planning", "running", "paused"}, to="aborted",
        completed_at=_utcnow(), failure_reason=reason,
    )
    # C6 — l'arrêt d'urgence RÉVOQUE aussi le mandat : sans ça,
    # autonomy_state restait « active » et le badge « Autonomie active »
    # survivait à l'abort (vu au test réel encadré du 19/07). Best-effort :
    # la révocation cosmétique ne doit jamais faire échouer le kill switch.
    if m.autonomy_state:
        try:
            await set_autonomy_state(mission_id, "revoked")
            m.autonomy_state = "revoked"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "abort_mission(%s) : révocation du mandat échouée (%s)",
                mission_id, exc,
            )
    return m


# ── Read helpers ────────────────────────────────────────────────────────────

async def get_mission(mission_id: str) -> Optional[Mission]:
    async with async_session() as db:
        return (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()


async def load_active_mandate(mission_id: str) -> "MissionMandate | None":
    """Le mandat d'une mission SI l'autonomie est active ET le flag global ON.

    Renvoie ``None`` (⇒ comportement supervisé inchangé) dès que : flag OFF,
    mission absente, pas de mandat, ou état ≠ 'active'. C'est le SEUL point
    d'entrée du gate d'enforcement (nodes.dispatch_tool) — Missions autonomes J2."""
    from app.config import get_settings
    if not get_settings().autonomous_missions_enabled:
        return None
    if not mission_id:
        return None
    m = await get_mission(mission_id)
    if m is None or not m.mandate_json or m.autonomy_state != "active":
        return None
    from app.services.mission_spec import mandate_from_json
    try:
        return mandate_from_json(m.mandate_json)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mandat illisible pour mission %s : %s", mission_id, exc)
        return None


async def set_autonomy_state(mission_id: str, state: str) -> None:
    """Transition de l'état d'autonomie du mandat (pending_validation →
    active → paused_*). Utilisé par l'activation (J6) et la pause (J3).
    Missions autonomes J2."""
    async with async_session() as db:
        m = await db.get(Mission, mission_id)
        if m is None:
            raise ValueError(f"mission introuvable : {mission_id!r}")
        m.autonomy_state = state
        await db.commit()
        title, goal, mandate_json = m.title, m.goal, m.mandate_json

    # J4 — l'activation initialise le squelette du CARNET.md (idempotent :
    # une reprise ne touche jamais un carnet existant). Flag OFF ou mission
    # sans mandat ⇒ aucun fichier créé. Best-effort : jamais bloquant.
    if state == "active" and mandate_json:
        from app.config import get_settings
        if not get_settings().autonomous_missions_enabled:
            return
        try:
            from app.services.mission_spec import mandate_from_json
            from app.services.mission_workspace import init_carnet
            try:
                mandate = mandate_from_json(mandate_json)
            except Exception:  # noqa: BLE001 — mandat illisible : carnet sans détail
                mandate = None
            init_carnet(mission_id, title or "", goal or "", mandate)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Carnet de %s non initialisé : %s", mission_id, exc)


async def list_missions_for_user(
    user_id: str,
    *,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Mission]:
    async with async_session() as db:
        q = select(Mission).where(Mission.user_id == user_id)
        if status:
            q = q.where(Mission.status == status)
        q = q.order_by(Mission.created_at.desc()).limit(limit).offset(offset)
        return list((await db.execute(q)).scalars().all())


async def list_due_missions(now: Optional[datetime] = None) -> list[Mission]:
    """Missions whose `next_tick_at` ≤ now and that are still active.

    Used by the heartbeat to know which missions need a tick.
    """
    now = now or _utcnow()
    async with async_session() as db:
        q = (
            select(Mission)
            .where(Mission.status.in_({"running", "planning"}))
            .where(Mission.next_tick_at.isnot(None))
            .where(Mission.next_tick_at <= now)
            .order_by(Mission.priority.asc(), Mission.next_tick_at.asc())
        )
        return list((await db.execute(q)).scalars().all())


# ── Plan operations ─────────────────────────────────────────────────────────

async def add_plan(
    mission_id: str,
    plan_text: str,
    plan_json: Optional[dict] = None,
    reason_for_replan: Optional[str] = None,
) -> MissionPlan:
    """Append a new plan version. Auto-increments `version`."""
    async with async_session() as db:
        # Compute next version number
        result = await db.execute(
            select(func.max(MissionPlan.version)).where(MissionPlan.mission_id == mission_id)
        )
        max_version = result.scalar() or 0
        plan = MissionPlan(
            mission_id=mission_id,
            version=max_version + 1,
            plan_text=plan_text,
            plan_json=plan_json,
            reason_for_replan=reason_for_replan,
        )
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
    logger.info("Mission %s: plan v%d added (%d chars)", mission_id, plan.version, len(plan_text))
    return plan


async def get_latest_plan(mission_id: str) -> Optional[MissionPlan]:
    async with async_session() as db:
        q = (
            select(MissionPlan)
            .where(MissionPlan.mission_id == mission_id)
            .order_by(MissionPlan.version.desc())
            .limit(1)
        )
        return (await db.execute(q)).scalar_one_or_none()


# ── Step operations ─────────────────────────────────────────────────────────

async def add_step(
    mission_id: str,
    phase: str,
    *,
    thought: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_input: Optional[dict] = None,
    tool_output: Optional[str] = None,
    evaluation: Optional[str] = None,
    success: Optional[bool] = None,
    tokens_used: int = 0,
    duration_ms: int = 0,
    model_used: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> MissionStep:
    """Append a new step to the audit trail. Auto-numbers `iteration`.

    Sprint 3.7 Jalon 3 — `prompt_version` is the sha256[:8] of the
    system prompt active when this step ran. If omitted, fall back to
    hashing the current ``_SYSTEM_PROMPT_BASE``. Future A/B testing
    (Jalon 5) will pass an explicit value computed from the chosen
    variant.
    """
    if phase not in STEP_PHASES:
        raise ValueError(f"invalid phase: {phase!r} (allowed: {STEP_PHASES})")

    if prompt_version is None:
        try:
            from app.services.learning import current_system_prompt_version
            prompt_version = current_system_prompt_version()
        except Exception:
            # Best-effort : never block step writing on a missing hash.
            prompt_version = None

    async with async_session() as db:
        # Compute next iteration number (per mission)
        result = await db.execute(
            select(func.max(MissionStep.iteration)).where(MissionStep.mission_id == mission_id)
        )
        max_iter = result.scalar() or 0

        step = MissionStep(
            mission_id=mission_id,
            iteration=max_iter + 1,
            phase=phase,
            thought=thought,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            evaluation=evaluation,
            success=success,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            model_used=model_used,
            prompt_version=prompt_version,
        )
        db.add(step)

        # Concurrently bump the mission's running counters.
        #
        # Une itération est un TOUR DE L'ACTEUR. Le compteur montait à
        # chaque ligne écrite — plan, action, évaluation — si bien qu'un
        # appel d'outil coûtait deux itérations et que le budget par
        # défaut (30) n'en laissait qu'une quinzaine : « Prospection LKDN »
        # a consommé 41 itérations pour 18 appels d'outils (31/08/2026).
        await db.execute(
            update(Mission)
            .where(Mission.id == mission_id)
            .values(
                tokens_used=Mission.tokens_used + tokens_used,
                iterations_used=Mission.iterations_used + (1 if phase == "act" else 0),
            )
        )
        await db.commit()
        await db.refresh(step)
    return step


async def list_steps(mission_id: str, *, limit: int = 200) -> list[MissionStep]:
    async with async_session() as db:
        q = (
            select(MissionStep)
            .where(MissionStep.mission_id == mission_id)
            .order_by(MissionStep.iteration.asc())
            .limit(limit)
        )
        return list((await db.execute(q)).scalars().all())


async def add_tokens_used(mission_id: str, tokens: int) -> None:
    """Cumule la consommation LLM réelle sur le budget de la mission.

    C1a (audit 16/07 §6.4) : avant ce compteur, ``tokens_used`` restait à 0
    — ``add_step`` acceptait le paramètre mais aucun appelant ne le passait —
    et ``check_budget`` (heartbeat + /tick) donnait une fausse assurance.
    UPDATE atomique côté SQL (pas de read-modify-write).
    """
    if tokens <= 0:
        return
    async with async_session() as db:
        await db.execute(
            update(Mission)
            .where(Mission.id == mission_id)
            .values(tokens_used=Mission.tokens_used + int(tokens))
        )
        await db.commit()


# ── Budget guards (called by the loop before each LLM call) ─────────────────

async def check_budget(mission_id: str) -> Optional[str]:
    """Return a failure reason string if mission is out of budget, else None.

    Caller is expected to `fail_mission` with the returned reason if non-null.
    """
    m = await get_mission(mission_id)
    if not m:
        return "mission not found"
    if m.iterations_used >= m.budget_iterations:
        return f"iteration budget exhausted ({m.iterations_used}/{m.budget_iterations})"
    if m.tokens_used >= m.budget_tokens:
        return f"token budget exhausted ({m.tokens_used}/{m.budget_tokens})"
    if m.deadline:
        # SQLite stores naive datetimes; coerce to UTC before comparison
        # to avoid `TypeError: can't compare offset-naive and offset-aware
        # datetimes` which would crash the heartbeat tick and force-fail
        # the mission with a misleading "graph crashed" reason.
        deadline_aware = m.deadline if m.deadline.tzinfo else m.deadline.replace(tzinfo=timezone.utc)
        if _utcnow() > deadline_aware:
            return f"deadline exceeded ({deadline_aware.isoformat()})"
    return None
