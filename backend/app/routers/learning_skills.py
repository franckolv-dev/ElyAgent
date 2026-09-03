# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/learning_skills.py
# @brief      Sprint 4b Phase 3.c — admin endpoints for the skill_creator loop
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Admin endpoints for the autonomous skill-creation loop.

Admin-only (`require_admin`) endpoints :

  - `POST   /admin/learning/skill-creator/run`         (3.c)
        Trigger one full batch of create → eval → iterate for a user.

  - `POST   /admin/learning/tool-creator/run`          (Sprint 4b V2)
        Trigger one python_tool generate → validate (5 stages) → persist
        loop. The V2 analogue of skill-creator/run (Markdown playbooks).

  - `GET    /admin/learning/skills/candidates`         (3.c)
        List candidate skills, filterable by status / user.

Phase 4.a — skill lifecycle :

  - `POST   /admin/learning/skills/{skill_id}/promote`
        Move a `candidate` skill to `active` (HITL promotion).
        Active skills get injected into the agent prompt (Phase 4.b).

  - `POST   /admin/learning/skills/{skill_id}/archive`
        Move an `active` or `stale` skill to `archived`. Recoverable.
        The curator (Phase 5) flips skills automatically too.

  - `POST   /admin/learning/skills/{skill_id}/restore`
        Move an `archived` skill back to `candidate` for re-review.

  - `DELETE /admin/learning/skills/{skill_id}`
        Permanently delete a `rejected` or `archived` skill. The
        underlying `failure_cases` rows are untouched (kept for
        forensic / future re-processing).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.config import get_settings

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillStatus,
)
from app.models.user import User
from app.services.learning.skill_iteration import MAX_ITERATIONS
from app.services.learning.skill_orchestrator import run_full_loop
from app.services.learning.learned_tools_runtime import python_tools_enabled
from app.services.learning.tool_creator import generate_and_persist_tool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/learning", tags=["learning"])


# ── Request / response schemas ──────────────────────────────────────────────


class SkillCreatorRunRequest(BaseModel):
    user_id: str = Field(
        ...,
        description=(
            "The user whose failure_cases the creator should process. "
            "Required: every LearnedSkill is user-scoped."
        ),
    )
    batch_size: int = Field(
        3,
        ge=1,
        le=10,
        description=(
            "How many failure-pattern clusters to process this run. "
            "Each cluster becomes at most one candidate skill."
        ),
    )
    max_iterations: int = Field(
        MAX_ITERATIONS,
        ge=1,
        le=MAX_ITERATIONS,
        description=(
            "Cap on patch attempts per candidate before marking it "
            "rejected. Default = MAX_ITERATIONS (5)."
        ),
    )


class ToolCreatorRunRequest(BaseModel):
    """Sprint 4b V2 — trigger one python_tool generation loop."""

    task_description: str = Field(
        ...,
        min_length=8,
        description=(
            "Plain-language description of the tool to generate. Be explicit "
            "about the signature when it matters, e.g. 'compute the n-th "
            "Fibonacci number — fibonacci(n: int) -> int'."
        ),
    )
    user_id: str = Field(
        ...,
        description=(
            "User the generated python_tool is scoped to "
            "(every LearnedSkill is user-scoped)."
        ),
    )
    force: bool = Field(
        False,
        description=(
            "C4-2 — outrepasser le pré-check sémantique anti-doublon "
            "(générer même si un outil existant semble couvrir la capacité)."
        ),
    )
    smoke_kwargs: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "Optional sample kwargs to exercise the function in the smoke "
            "sandbox stage (e.g. {\"n\": 10}). Omit to skip smoke — the other "
            "4 validation stages still run."
        ),
    )
    max_iterations: int = Field(
        3,
        ge=1,
        le=5,
        description=(
            "Cap on generate→validate retries; the failing stage's error is "
            "fed back into the next generation. Default 3."
        ),
    )
    profile: str = Field(
        "pure",
        pattern="^(pure|io)$",
        description=(
            "Sprint 4b V3 J7 — 'pure' (V2: composition + calcul, in-process) "
            "ou 'io' (V3: intégration réseau réelle, exécutée en sandbox avec "
            "egress déclaré, secrets Vault et deps bornées). Les candidats io "
            "affichent leurs déclarations sur la page de revue."
        ),
    )


class CandidateOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: str
    # The body the admin reviews before promoting — promoting on name+score
    # alone would be flying blind. For a markdown_playbook it's the Markdown
    # body; for a python_tool (Sprint 4b V2) it's the generated Python source.
    # Capped server-side by the candidates `limit`, so payload size stays bounded.
    content: str
    # Sprint 4b V2 J8 — tells the review UI how to render `content`
    # (markdown_playbook → ReactMarkdown ; python_tool → code + validation report).
    content_format: str
    # Sprint 4b V2 J8 — JSON report from the 5-stage validation pipeline
    # (ast/ruff/mypy/smoke/registration). "{}" for markdown playbooks (they
    # don't go through it). The UI surfaces per-stage verdicts so the human
    # gate is informed, not a blind click.
    validation_report_json: str
    status: str
    iteration_count: int
    last_eval_score: Optional[int]
    rationale: Optional[str]
    from_failure_case_ids: str  # JSON string
    # Sprint 4b V3 J8 — la revue d'un outil io exige de voir ce qu'il
    # DÉCLARE (la promotion valide aussi un périmètre réseau/secrets/deps,
    # pas seulement du code). None pour les playbooks et les tools pure.
    tool_profile: str = "pure"
    v3_network_allow: Optional[list[str]] = None
    v3_requires: Optional[list[str]] = None
    v3_requires_secrets: Optional[list[str]] = None
    created_at: str

    model_config = {"from_attributes": True}


class ToolGapOut(BaseModel):
    """A capability ELY's `find_tool` searched for but couldn't surface — the
    `tool_absent_acknowledged` signal (find_tool Phase 2). The admin reviews
    these, decides if it's worth generating a new tool (→ /tool-creator/run)
    or marks it processed to clear the queue."""

    id: int
    user_id: str
    # The natural-language capability the user/model asked for (extracted from
    # the FailureCase replay_payload).
    capability: str
    conversation_id: Optional[str]
    mission_id: Optional[str]
    created_at: str
    # ISO timestamp when an admin (or the auto-pipeline, later) marked this
    # gap as handled. None while the gap is still open.
    processed_at: Optional[str]
    # If the gap was resolved by generating a learned skill, its id is kept
    # here so the UI can link to the candidate page.
    learned_skill_id: Optional[str]


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/skill-creator/run")
async def run_skill_creator(
    body: SkillCreatorRunRequest,
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Trigger one full batch of skill creation + eval + iteration.

    Admin-only. Synchronous : the call blocks until the orchestrator
    is done with the batch (which can take 30-60 s per cluster with
    Opus + 1-5 evaluations). Returns the structured summary so the
    admin can see what happened in one round trip.
    """
    try:
        summary = await run_full_loop(
            user_id=body.user_id,
            batch_size=body.batch_size,
            max_iterations=body.max_iterations,
        )
    except Exception as exc:
        # The orchestrator is built to never raise, but if it does
        # we want a clean 500 instead of letting the stack trace
        # bubble up to the user.
        logger.exception(
            "skill_creator run crashed for user_id=%s", body.user_id,
        )
        raise HTTPException(500, f"skill_creator orchestrator crashed: {exc}")
    return summary


@router.post("/tool-creator/run")
async def run_tool_creator(
    body: ToolCreatorRunRequest,
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Sprint 4b V2 — trigger one python_tool generate→validate→persist loop.

    The V2 analogue of `/skill-creator/run` (which produces V1 Markdown
    playbooks). Admin-only. Calls the tier-S LLM (niveau « S » du Routage) to
    write a PURE python_tool, runs the 5-stage validation pipeline
    (ast → ruff → mypy → smoke → registration), and on success persists a
    `candidate` LearnedSkill (`content_format=python_tool`) for review on the
    candidates page and HITL promotion.

    NEVER auto-activates — promotion stays a human gate, and the tool only
    becomes bindable once promoted AND `LEARNED_PYTHON_TOOLS_ENABLED` is on.
    The response echoes `python_tools_enabled` so the caller knows whether a
    promoted tool would actually go live.
    """
    # Le gel de la fabrique (02/09/2026, `auto_tool_generation_enabled`)
    # coupait la voie automatique mais pas celle-ci : l'endpoint admin
    # générait du code sans lire le drapeau. Même lecture défensive que
    # `auto_tool_generation.py` — illisible vaut gelée (03/09/2026).
    try:
        _fabrique_ouverte = bool(get_settings().auto_tool_generation_enabled)
    except Exception as _exc:  # noqa: BLE001
        logger.warning("tool_creator: drapeau de fabrique illisible (%s) — gelée", _exc)
        _fabrique_ouverte = False
    if not _fabrique_ouverte:
        return {
            "status": "frozen",
            "detail": (
                "La fabrique d'outils est gelée (AUTO_TOOL_GENERATION_ENABLED=false) : "
                "aucun code d'outil n'est généré, y compris à la demande d'un "
                "administrateur. La voie ouverte est la compétence-document."
            ),
            "python_tools_enabled": python_tools_enabled(),
            "attempts": [],
        }
    # C4-2 — pré-check sémantique anti-doublon : ne pas dépenser du tier-S si
    # un outil existant couvre déjà la capacité (trou de binding, leçon
    # Drive/Sheets). `force=true` outrepasse en connaissance de cause.
    if not body.force:
        from app.skills.builtin.find_tool_skill import capability_has_existing_tool

        # V0-4 : inclut les outils déjà fabriqués pour cet utilisateur, quel
        # que soit leur statut (une candidate non promue n'est bindée nulle
        # part, donc invisible au catalogue). `force=true` outrepasse.
        _existing = await capability_has_existing_tool(
            body.task_description, user_id=body.user_id
        )
        if _existing:
            return {
                "status": "exists",
                "tool_name": _existing,
                "detail": (
                    "Un outil existant couvre déjà cette capacité — génération "
                    "refusée (passer force=true pour outrepasser)."
                ),
                "python_tools_enabled": python_tools_enabled(),
                "attempts": [],
            }
    try:
        summary = await generate_and_persist_tool(
            task_description=body.task_description,
            user_id=body.user_id,
            smoke_kwargs=body.smoke_kwargs,
            max_iterations=body.max_iterations,
            profile=body.profile,
        )
    except Exception as exc:
        # generate_and_persist_tool is built to never raise; this is
        # belt-and-braces so a surprise still yields a clean 500.
        logger.exception("tool_creator run crashed for user_id=%s", body.user_id)
        raise HTTPException(500, f"tool_creator orchestrator crashed: {exc}")
    summary["python_tools_enabled"] = python_tools_enabled()
    return summary


@router.get("/skills/candidates")
async def list_candidates(
    user_id: Optional[str] = Query(
        None,
        description="Filter to one user. Omit to list across all users.",
    ),
    status: Optional[str] = Query(
        None,
        description=(
            "Filter by status (candidate | active | stale | archived "
            "| rejected). Default = candidate (the ones awaiting "
            "promotion review)."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CandidateOut]:
    """List `LearnedSkill` rows for admin review.

    Default filter is `status=candidate` because that's what the
    promotion UI (Phase 4) will display. Pass `?status=rejected` to
    audit the failure tail or `?status=active` to see what's live.
    """
    target_status = status or SkillStatus.CANDIDATE
    if target_status not in SkillStatus.ALL:
        raise HTTPException(
            400,
            f"Unknown status {target_status!r}. Valid: {sorted(SkillStatus.ALL)}",
        )

    query = select(LearnedSkill).where(LearnedSkill.status == target_status)
    if user_id:
        query = query.where(LearnedSkill.user_id == user_id)
    query = query.order_by(LearnedSkill.created_at.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()

    def _v3_fields(r: LearnedSkill) -> dict[str, Any]:
        """Déclarations V3 pour la revue J8 — uniquement pour les tools io."""
        if (
            r.content_format != SkillContentFormat.PYTHON_TOOL
            or getattr(r, "tool_profile", "pure") != "io"
        ):
            return {"tool_profile": getattr(r, "tool_profile", "pure") or "pure"}
        try:
            from app.services.learning.v3_declarations import parse_v3_declarations
            decls = parse_v3_declarations(r.content or "")
            return {
                "tool_profile": "io",
                "v3_network_allow": list(decls.network_allow),
                "v3_requires": list(decls.requires),
                "v3_requires_secrets": list(decls.requires_secrets),
            }
        except Exception:  # noqa: BLE001 — la revue reste possible sans le panneau
            return {"tool_profile": "io"}

    return [
        CandidateOut(
            id=r.id,
            user_id=r.user_id,
            name=r.name,
            description=r.description,
            content=r.content,
            content_format=r.content_format,
            validation_report_json=r.validation_report_json,
            status=r.status,
            iteration_count=r.iteration_count,
            last_eval_score=r.last_eval_score,
            rationale=r.rationale,
            from_failure_case_ids=r.from_failure_case_ids,
            created_at=r.created_at.isoformat() if r.created_at else "",
            **_v3_fields(r),
        )
        for r in rows
    ]


# ── Phase 4.a — lifecycle endpoints ────────────────────────────────────────


# Allowed status transitions. Anything not in here returns 409 Conflict.
# We model lifecycle on top of the enum so a future Phase 5 curator can
# transition active→stale and stale→archived without bypassing this map.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    SkillStatus.CANDIDATE: {SkillStatus.ACTIVE, SkillStatus.ARCHIVED},
    SkillStatus.ACTIVE:    {SkillStatus.ARCHIVED, SkillStatus.STALE, SkillStatus.GRADUATED},
    SkillStatus.STALE:     {SkillStatus.ACTIVE, SkillStatus.ARCHIVED},
    SkillStatus.ARCHIVED:  {SkillStatus.CANDIDATE},  # restore back to review
    SkillStatus.REJECTED:  set(),                    # terminal, only DELETE
    # Sprint 4d — un-graduation (PR refusée / revert du core) : retour au
    # binding dynamique. La garde de chargement re-graduera si la collision
    # core existe toujours — le retour ACTIVE n'est effectif qu'après revert.
    SkillStatus.GRADUATED: {SkillStatus.ACTIVE},
}


async def _load_skill_or_404(db: AsyncSession, skill_id: str) -> LearnedSkill:
    row = (await db.execute(
        select(LearnedSkill).where(LearnedSkill.id == skill_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Skill {skill_id!r} not found.")
    return row


async def _transition_status(
    db: AsyncSession,
    skill: LearnedSkill,
    new_status: str,
    *,
    admin_id: str,
) -> LearnedSkill:
    """Apply a status transition with the allowed-transitions check.

    Sets ``updated_at = now`` and persists. Does NOT commit — caller
    commits + reads ``skill`` back. Raises HTTPException 409 if the
    transition isn't allowed.
    """
    allowed = _ALLOWED_TRANSITIONS.get(skill.status, set())
    if new_status not in allowed:
        raise HTTPException(
            409,
            f"Transition {skill.status!r} → {new_status!r} not allowed. "
            f"Valid from {skill.status!r}: {sorted(allowed) or '(none — terminal)'}",
        )
    skill.status = new_status
    skill.updated_at = datetime.now(timezone.utc)
    if new_status == SkillStatus.ACTIVE:
        # C4-3 — every path INTO active (promote, stale/graduated
        # reactivation) restarts the injection grace window.
        skill.promoted_at = skill.updated_at
    return skill


def _invalidate_python_tool_cache(skill: LearnedSkill) -> None:
    """Sprint 4b V2 J7c — drop the per-user runtime cache after a status
    change that alters the user's *active* python_tool set (promote = now
    bindable, archive = no longer bindable). The cache never self-expires,
    so without this an archived tool would stay bound until restart. No-op
    for markdown playbooks (they don't go through the runtime loader).
    """
    if skill.content_format != SkillContentFormat.PYTHON_TOOL:
        return
    from app.services.learning import learned_tools_runtime
    learned_tools_runtime.invalidate(skill.user_id)


@router.post("/skills/{skill_id}/promote", response_model=CandidateOut)
async def promote_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CandidateOut:
    """HITL admin promotion : `candidate` → `active`.

    Active skills get injected into the agent's system prompt at next
    turn (Phase 4.b wires the injection). This is the one moment a
    human reviews what the autonomous loop produced before it goes
    live for the user.
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.status == SkillStatus.ACTIVE:
        # Idempotent — promoting an already-active skill is a no-op.
        return _to_candidate_out(skill)
    await _transition_status(db, skill, SkillStatus.ACTIVE, admin_id=admin.id)
    await db.commit()
    await db.refresh(skill)
    _invalidate_python_tool_cache(skill)
    logger.info(
        "skill_promoted: id=%s name=%s by_admin=%s",
        skill.id, skill.name, admin.id[:8] if admin.id else "?",
    )
    return _to_candidate_out(skill)


class ImportSkillRequest(BaseModel):
    url: str = Field(..., description="URL d'un fichier SKILL.md (playbook Markdown) à importer.")


@router.post("/skills/import")
async def import_skill_from_url_endpoint(
    payload: ImportSkillRequest,
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """J5-B — importer un playbook SKILL.md depuis une URL.

    Le playbook est créé en ``candidate`` (file de revue admin existante) :
    contenu externe = non fiable → l'admin le valide avant qu'il ne soit
    injecté dans le prompt. Réutilise toute la machinerie J1.
    """
    from app.services.learning.skill_import import import_skill_from_url
    result = await import_skill_from_url(payload.url, admin.id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error", "Import échoué."))
    return result


@router.get("/skills/{skill_id}/graduation")
async def graduation_report(
    skill_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sprint 4d J1 — stats + gates de graduation d'un learned tool.

    Retourne invocations / erreurs récentes / refus HITL / âge et le
    verdict gate par gate (seuils env-tunables, design note §4.2).
    ``eligible=true`` = digne d'un dry-run de graduation (J4) — les gates
    de revalidation et de composition seront jouées par le dry-run.

    404 sur un skill inexistant ; 400 sur un format non python_tool (les
    playbooks markdown ne graduent pas — c'est aussi une gate, mais la
    demander explicitement est plus probablement une erreur d'appel).
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.content_format != SkillContentFormat.PYTHON_TOOL:
        raise HTTPException(
            400,
            f"Skill {skill.name!r} is a {skill.content_format} — "
            "only python_tool skills can graduate.",
        )
    from app.services.learning.graduation import compute_graduation_stats
    return await compute_graduation_stats(db, skill)


class GraduateRequest(BaseModel):
    """Corps de POST /skills/{id}/graduate.

    ``dry_run=True`` (défaut) : joue toutes les gates et retourne les
    fichiers générés SANS rien livrer. ``smoke_kwargs`` (optionnel) :
    arguments d'exemple — déclenche l'étage smoke de la revalidation ET
    un test d'invocation réelle dans le pytest généré.
    """
    dry_run: bool = True
    smoke_kwargs: Optional[dict] = None


@router.post("/skills/{skill_id}/graduate")
async def graduate_skill(
    skill_id: str,
    body: GraduateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sprint 4d J4 — graduation d'un learned tool vers le code core.

    Dry-run : gates J1 + revalidation 7 étages + dépendances de
    composition + aperçu des 3 artefacts (tool core, test pytest,
    manifest). La livraison réelle (branche + PR GitHub) est J5.
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.content_format != SkillContentFormat.PYTHON_TOOL:
        raise HTTPException(
            400,
            f"Skill {skill.name!r} is a {skill.content_format} — "
            "only python_tool skills can graduate.",
        )
    from app.services.learning.graduation_codegen import dry_run_graduation
    result = await dry_run_graduation(db, skill, smoke_kwargs=body.smoke_kwargs)
    if body.dry_run:
        return result

    # ── Livraison réelle (J5) — exige un dry-run intégralement vert ──────
    if not result["ready"]:
        raise HTTPException(
            409,
            {
                "message": "Graduation refusée : le dry-run n'est pas vert.",
                "graduation_eligible": result["graduation"]["eligible"],
                "revalidation_ok": result["revalidation"]["ok"],
                "composition_ok": result["composition"]["ok"],
            },
        )
    from app.services.learning.graduation_delivery import (
        GitHubDeliveryError,
        deliver_graduation,
    )
    try:
        delivery = await deliver_graduation(
            manifest=result["manifest"], files=result["files"],
        )
    except GitHubDeliveryError as exc:
        raise HTTPException(502, f"Livraison GitHub échouée : {exc}")

    # Trace de la livraison dans frontmatter_json.graduation — le statut
    # reste ACTIVE : c'est la garde de chargement (J4) qui bascule en
    # 'graduated' après merge + rebuild (collision core détectée).
    try:
        fm = json.loads(skill.frontmatter_json or "{}")
    except ValueError:
        fm = {}
    fm["graduation"] = {
        "delivered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "by_admin": admin.id[:8] if admin.id else "?",
        "status": delivery["status"],
        "pr_url": delivery.get("pr_url"),
        "branch": delivery.get("branch"),
        "export_path": delivery.get("export_path"),
    }
    skill.frontmatter_json = json.dumps(fm, ensure_ascii=False)
    await db.commit()
    logger.info(
        "skill_graduation_delivered: id=%s name=%s via=%s by_admin=%s",
        skill.id, skill.name, delivery["status"],
        admin.id[:8] if admin.id else "?",
    )
    return {**result, "delivery": delivery}


@router.post("/skills/{skill_id}/archive", response_model=CandidateOut)
async def archive_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CandidateOut:
    """Move an `active` or `stale` skill to `archived`.

    Archived skills are hidden from the system prompt injection but
    kept in DB — restorable via `/restore`. The curator (Phase 5) does
    this automatically for skills unused too long.
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.status == SkillStatus.ARCHIVED:
        return _to_candidate_out(skill)
    await _transition_status(db, skill, SkillStatus.ARCHIVED, admin_id=admin.id)
    await db.commit()
    await db.refresh(skill)
    _invalidate_python_tool_cache(skill)
    logger.info(
        "skill_archived: id=%s name=%s by_admin=%s",
        skill.id, skill.name, admin.id[:8] if admin.id else "?",
    )
    return _to_candidate_out(skill)


@router.post("/skills/{skill_id}/restore", response_model=CandidateOut)
async def restore_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CandidateOut:
    """Move an `archived` skill back to `candidate` for re-review.

    Doesn't go straight to active — the admin must re-evaluate
    (possibly with fresh eyes) and explicitly re-promote.
    """
    skill = await _load_skill_or_404(db, skill_id)
    await _transition_status(db, skill, SkillStatus.CANDIDATE, admin_id=admin.id)
    await db.commit()
    await db.refresh(skill)
    logger.info(
        "skill_restored: id=%s name=%s by_admin=%s",
        skill.id, skill.name, admin.id[:8] if admin.id else "?",
    )
    return _to_candidate_out(skill)


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Permanently delete a `rejected` or `archived` skill.

    Active / candidate / stale skills must be archived first — this
    prevents accidental deletion of skills in use. The underlying
    `failure_cases` rows are NOT deleted (audit trail kept).
    """
    skill = await _load_skill_or_404(db, skill_id)
    if skill.status not in {SkillStatus.REJECTED, SkillStatus.ARCHIVED}:
        raise HTTPException(
            409,
            f"Cannot delete skill in status {skill.status!r}. "
            "Archive it first (active/stale → archived → delete).",
        )
    await db.execute(
        delete(LearnedSkill).where(LearnedSkill.id == skill_id)
    )
    await db.commit()
    logger.info(
        "skill_deleted: id=%s name=%s status_was=%s by_admin=%s",
        skill_id, skill.name, skill.status, admin.id[:8] if admin.id else "?",
    )
    return {"status": "deleted", "skill_id": skill_id}


def _to_candidate_out(skill: LearnedSkill) -> CandidateOut:
    return CandidateOut(
        id=skill.id,
        user_id=skill.user_id,
        name=skill.name,
        description=skill.description,
        content=skill.content,
        content_format=skill.content_format,
        validation_report_json=skill.validation_report_json,
        status=skill.status,
        iteration_count=skill.iteration_count,
        last_eval_score=skill.last_eval_score,
        rationale=skill.rationale,
        from_failure_case_ids=skill.from_failure_case_ids,
        created_at=skill.created_at.isoformat() if skill.created_at else "",
    )


# ── tool_absent gaps — find_tool Phase 2 outcomes ──────────────────────────


def _tool_gap_to_out(row) -> ToolGapOut:
    """Build a ToolGapOut from a FailureCase row (signal_table=tool_absent).

    `capability` is extracted from the replay_payload JSON (where Phase 2 puts
    it). Falls back to `expected_outcome` (the truncated capability also kept
    in a dedicated column for indexing).
    """
    capability = row.expected_outcome or ""
    try:
        payload = json.loads(row.replay_payload or "{}")
        capability = payload.get("capability") or capability
    except (ValueError, TypeError):
        pass
    return ToolGapOut(
        id=row.id,
        user_id=row.user_id,
        capability=capability,
        conversation_id=row.conversation_id,
        mission_id=row.mission_id,
        created_at=row.created_at.isoformat() if row.created_at else "",
        processed_at=row.processed_at.isoformat() if row.processed_at else None,
        learned_skill_id=row.learned_skill_id,
    )


@router.get("/tool-gaps")
async def list_tool_gaps(
    status: str = Query(
        "open",
        description="Filter: 'open' (default — unprocessed gaps) or 'all'.",
    ),
    user_id: Optional[str] = Query(None, description="Filter to one user."),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ToolGapOut]:
    """List capability gaps recorded by find_tool Phase 2.

    Each row is a unique capability the user/model asked for but the catalog
    couldn't satisfy (record_tool_absent dedupes on the capability fingerprint
    while still unprocessed, so no row inflation).
    """
    if status not in {"open", "all"}:
        raise HTTPException(400, f"Unknown status {status!r}. Valid: open, all")

    from app.models.failure_case import FailureCase

    query = select(FailureCase).where(FailureCase.signal_table == "tool_absent")
    if status == "open":
        query = query.where(FailureCase.processed_at.is_(None))
    if user_id:
        query = query.where(FailureCase.user_id == user_id)
    query = query.order_by(FailureCase.created_at.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return [_tool_gap_to_out(r) for r in rows]


class ToolGapMarkProcessedRequest(BaseModel):
    """Optional body for /tool-gaps/{id}/mark-processed.

    Both fields are optional: pass `learned_skill_id` to record which skill
    resolved this gap (links gap → candidate in the UI). `reason` is a free
    note (e.g. "out of scope", "duplicate") kept for auditability.
    """

    learned_skill_id: Optional[str] = None
    reason: Optional[str] = None


@router.post("/tool-gaps/{gap_id}/mark-processed", response_model=ToolGapOut)
async def mark_tool_gap_processed(
    gap_id: int,
    body: Optional[ToolGapMarkProcessedRequest] = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ToolGapOut:
    """Mark a `tool_absent` gap as handled — sets processed_at=now().

    Idempotent: a gap already processed simply returns its current state.
    Pass `learned_skill_id` if the gap was resolved by generating a candidate
    (links the gap to the candidate page).
    """
    from app.models.failure_case import FailureCase

    row = (await db.execute(
        select(FailureCase).where(
            FailureCase.id == gap_id,
            FailureCase.signal_table == "tool_absent",
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"tool_absent gap {gap_id} not found")
    if row.processed_at is None:
        row.processed_at = datetime.now(timezone.utc)
        if body and body.learned_skill_id:
            row.learned_skill_id = body.learned_skill_id
        await db.commit()
        await db.refresh(row)
        logger.info("tool_gap_processed: id=%s by_admin=%s skill=%s",
                    row.id, _admin.id[:8] if _admin.id else "?",
                    row.learned_skill_id or "—")
    return _tool_gap_to_out(row)


# ─────────────────────────────────────────────────────────────────────────
# Boucle d'auto-diagnostic J1 — « régression visible » (lecture seule)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/regression")
async def learning_regression(
    window: str = Query("30d", description="Fenêtre d'affichage : 7d, 30d, 90d, 24h."),
    recent: str = Query("3d", description="Fenêtre récente comparée à la référence."),
    baseline: str = Query("14d", description="Fenêtre de référence (précède la récente)."),
    min_samples: int = Query(5, ge=1, le=1000, description="Échantillon mini par côté pour alerter."),
    drop_threshold: float = Query(0.30, ge=0.0, le=1.0, description="Chute mini du taux réel pour alerter."),
    user_id: Optional[str] = Query(None, description="Filtre un user. None = vue globale (infra)."),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Taux de succès RÉEL par groupe (source × tier × modèle × canal) + série
    journalière + alertes de chute — design note §6.

    Lecture seule : agrège la table ``execution_outcomes``. Le verdict
    « dubious » (succès de façade) reste à 0 tant que J2 n'a pas branché les
    heuristiques ; en J1 ``real_success_rate`` == ``declared_success_rate``.
    """
    from app.services.learning.regression import regression_report

    return await regression_report(
        user_id=user_id,
        window=window,
        recent=recent,
        baseline=baseline,
        min_samples=min_samples,
        drop_threshold=drop_threshold,
    )


# ─────────────────────────────────────────────────────────────────────────
# Boucle d'auto-diagnostic J4 — « Incidents & propositions » (remontée)
# ─────────────────────────────────────────────────────────────────────────


class PatchOut(BaseModel):
    """Correctif proposé par Ely pour un incident (voie C, J5)."""

    id: int
    execution_diagnosis_id: int
    kind: str
    target_type: str
    target_id: str
    field: str
    old_value: Optional[str]
    new_value: str
    rationale: Optional[str]
    status: str  # proposed | applied | rejected | reverted
    critic_model: Optional[str]
    applied_at: Optional[str]
    created_at: str


def _patch_to_out(p: Any) -> PatchOut:
    return PatchOut(
        id=p.id,
        execution_diagnosis_id=p.execution_diagnosis_id,
        kind=p.kind,
        target_type=p.target_type,
        target_id=p.target_id,
        field=p.field,
        old_value=p.old_value,
        new_value=p.new_value,
        rationale=p.rationale,
        status=p.status or "proposed",
        critic_model=p.critic_model,
        applied_at=p.applied_at.isoformat() if p.applied_at else None,
        created_at=p.created_at.isoformat() if p.created_at else "",
    )


class IncidentOut(BaseModel):
    """Un incident = une diagnose (cause + catégorie) jointe au verdict de
    l'exécution qui l'a déclenchée. Alimente la page admin de remontée."""

    id: int
    execution_outcome_id: int
    user_id: str
    source: str
    source_id: Optional[str]
    category: str
    hypothesis: str
    confidence: str
    status: str
    resolution: Optional[str]
    critic_model: Optional[str]
    created_at: str
    processed_at: Optional[str]
    # Dédup des récurrences : nombre de runs repliés sur cet incident + date
    # du dernier run vu (None tant que jamais dédupliqué).
    occurrences: int = 1
    last_seen_at: Optional[str] = None
    # Contexte de l'exécution (joint depuis execution_outcomes)
    outcome: str
    declared_status: Optional[str]
    channel: Optional[str]
    tier_llm: Optional[str]
    model_used: Optional[str]
    signals: list[str]
    # J5 — correctif proposé le plus récent (voie C), s'il existe.
    patch: Optional[PatchOut] = None


def _incident_to_out(diag: Any, outcome: Any, patch: Any = None) -> IncidentOut:
    try:
        signals = json.loads(outcome.signals) if outcome.signals else []
        if not isinstance(signals, list):
            signals = []
    except Exception:
        signals = []
    return IncidentOut(
        id=diag.id,
        execution_outcome_id=diag.execution_outcome_id,
        user_id=diag.user_id,
        source=diag.source,
        source_id=diag.source_id,
        category=diag.category,
        hypothesis=diag.hypothesis,
        confidence=diag.confidence or "medium",
        status=diag.status or "open",
        resolution=diag.resolution,
        critic_model=diag.critic_model,
        created_at=diag.created_at.isoformat() if diag.created_at else "",
        processed_at=diag.processed_at.isoformat() if diag.processed_at else None,
        occurrences=diag.occurrences or 1,
        last_seen_at=diag.last_seen_at.isoformat() if diag.last_seen_at else None,
        outcome=outcome.outcome,
        declared_status=outcome.declared_status,
        channel=outcome.channel,
        tier_llm=outcome.tier_llm,
        model_used=outcome.model_used,
        signals=signals,
        patch=_patch_to_out(patch) if patch is not None else None,
    )


@router.get("/incidents")
async def list_incidents(
    status: str = Query("open", description="'open' (non tranchés) ou 'all'."),
    user_id: Optional[str] = Query(None, description="Filtre un user."),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[IncidentOut]:
    """Liste les incidents diagnostiqués (maillon 3). Un incident = une
    diagnose (cause + catégorie) + le contexte de l'exécution douteuse/échouée
    qui l'a déclenchée. L'admin valide / rejette (arbitrage humain)."""
    if status not in {"open", "all"}:
        raise HTTPException(400, f"Unknown status {status!r}. Valid: open, all")

    from app.models.execution_diagnosis import ExecutionDiagnosis
    from app.models.execution_outcome import ExecutionOutcome

    query = (
        select(ExecutionDiagnosis, ExecutionOutcome)
        .join(
            ExecutionOutcome,
            ExecutionOutcome.id == ExecutionDiagnosis.execution_outcome_id,
        )
    )
    if status == "open":
        query = query.where(ExecutionDiagnosis.status == "open")
    if user_id:
        query = query.where(ExecutionDiagnosis.user_id == user_id)
    query = query.order_by(ExecutionDiagnosis.created_at.desc()).limit(limit)

    rows = (await db.execute(query)).all()

    # J5 — attache le correctif le plus récent par incident (voie C).
    from app.models.proposed_patch import ProposedPatch
    diag_ids = [diag.id for diag, _ in rows]
    latest_patch: dict[int, Any] = {}
    if diag_ids:
        patch_rows = (await db.execute(
            select(ProposedPatch)
            .where(ProposedPatch.execution_diagnosis_id.in_(diag_ids))
            .order_by(ProposedPatch.created_at.desc())
        )).scalars().all()
        for p in patch_rows:  # premier vu = le plus récent (tri desc)
            latest_patch.setdefault(p.execution_diagnosis_id, p)

    return [
        _incident_to_out(diag, outcome, latest_patch.get(diag.id))
        for diag, outcome in rows
    ]


class IncidentResolveRequest(BaseModel):
    """Arbitrage humain d'un incident (J4)."""

    status: str = Field(description="validated | rejected | actioned")
    resolution: Optional[str] = Field(default=None, description="Note libre.")


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
async def resolve_incident(
    incident_id: int,
    body: IncidentResolveRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> IncidentOut:
    """Tranche un incident : validated / rejected / actioned. L'humain dans la
    boucle (le diagnostiqueur ne valide jamais ses propres hypothèses)."""
    from app.models.execution_diagnosis import (
        DIAGNOSIS_STATUSES,
        ExecutionDiagnosis,
    )
    from app.models.execution_outcome import ExecutionOutcome

    new_status = (body.status or "").strip().lower()
    # "open" est l'état initial, "merged" est posé par la garde de dédup et
    # "obsolete" par le service quand la cible a disparu — aucun des trois ne
    # se pose à la main.
    if new_status not in DIAGNOSIS_STATUSES or new_status in (
        "open", "merged", "obsolete",
    ):
        raise HTTPException(
            400,
            f"Unknown status {body.status!r}. Valid: validated, rejected, actioned",
        )

    diag = (await db.execute(
        select(ExecutionDiagnosis).where(ExecutionDiagnosis.id == incident_id)
    )).scalar_one_or_none()
    if diag is None:
        raise HTTPException(404, f"incident {incident_id} not found")

    diag.status = new_status
    if body.resolution:
        diag.resolution = body.resolution[:2000]
    diag.processed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(diag)
    logger.info("incident_resolved: id=%s status=%s by_admin=%s",
                diag.id, new_status, _admin.id[:8] if _admin.id else "?")

    outcome = (await db.execute(
        select(ExecutionOutcome).where(ExecutionOutcome.id == diag.execution_outcome_id)
    )).scalar_one_or_none()
    return _incident_to_out(diag, outcome)


# ─────────────────────────────────────────────────────────────────────────
# Boucle d'auto-diagnostic J5 — correctifs validables (voie C : prompt patch)
# ─────────────────────────────────────────────────────────────────────────


@router.post("/incidents/{incident_id}/propose-patch", response_model=PatchOut)
async def propose_incident_patch(
    incident_id: int,
    _admin: User = Depends(require_admin),
) -> PatchOut:
    """Génère un correctif de prompt (réécriture) pour un incident de tâche
    planifiée. NE l'applique PAS — l'admin verra le diff puis Appliquera."""
    from app.services.learning.patch_service import (
        PatchError, PatchTargetGone, propose_patch,
    )

    try:
        patch = await propose_patch(incident_id)
    except PatchTargetGone as exc:
        # 410 et pas 422 : ce n'est pas une demande mal formée, c'est une cible
        # qui a disparu. Le code porte l'information — l'interface s'en sert
        # pour retirer la carte au lieu de laisser l'incident à l'écran.
        raise HTTPException(410, str(exc))
    except PatchError as exc:
        raise HTTPException(422, str(exc))
    if patch is None:
        raise HTTPException(422, "aucun correctif généré")
    logger.info("patch_proposed: incident=%s patch=%s by_admin=%s",
                incident_id, patch.id, _admin.id[:8] if _admin.id else "?")
    return _patch_to_out(patch)


@router.post("/patches/{patch_id}/apply", response_model=PatchOut)
async def apply_incident_patch(
    patch_id: int,
    _admin: User = Depends(require_admin),
) -> PatchOut:
    """Applique un correctif proposé (réversible — l'ancienne valeur est gardée)."""
    from app.services.learning.patch_service import (
        PatchError, PatchTargetGone, apply_patch,
    )

    try:
        patch = await apply_patch(patch_id)
    except PatchTargetGone as exc:
        raise HTTPException(410, str(exc))
    except PatchError as exc:
        raise HTTPException(409, str(exc))
    logger.info("patch_applied: patch=%s by_admin=%s",
                patch_id, _admin.id[:8] if _admin.id else "?")
    return _patch_to_out(patch)


@router.post("/patches/{patch_id}/revert", response_model=PatchOut)
async def revert_incident_patch(
    patch_id: int,
    _admin: User = Depends(require_admin),
) -> PatchOut:
    """Annule un correctif appliqué : restaure la valeur d'avant application."""
    from app.services.learning.patch_service import PatchError, revert_patch

    try:
        patch = await revert_patch(patch_id)
    except PatchError as exc:
        raise HTTPException(409, str(exc))
    logger.info("patch_reverted: patch=%s by_admin=%s",
                patch_id, _admin.id[:8] if _admin.id else "?")
    return _patch_to_out(patch)


@router.post("/patches/{patch_id}/reject", response_model=PatchOut)
async def reject_incident_patch(
    patch_id: int,
    _admin: User = Depends(require_admin),
) -> PatchOut:
    """Rejette un correctif proposé (sans l'appliquer)."""
    from app.services.learning.patch_service import PatchError, reject_patch

    try:
        patch = await reject_patch(patch_id)
    except PatchError as exc:
        raise HTTPException(409, str(exc))
    return _patch_to_out(patch)
