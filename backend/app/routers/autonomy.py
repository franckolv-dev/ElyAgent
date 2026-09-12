"""User-owned automations, assurance and autonomy controls."""

import json
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.autonomy import AutomationRule, AutomationEvent, MissionAssurance, AutonomyPreferences
from app.services.event_automations import matches

router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])


from app.services.mission_assurance import Check


class RuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    source: Literal["gmail.received", "calendar.changed", "file.indexed"]
    account: str = Field("default", max_length=160)
    goal: str = Field(min_length=5, max_length=8000)
    sender_contains: str = Field("", max_length=200)
    text_contains: str = Field("", max_length=300)
    folder_prefix: str = Field("", max_length=1000)
    daily_limit: int = Field(5, ge=1, le=50)
    checks: list[Check] = Field(default_factory=list, max_length=20)


def rule_out(r):
    return dict(
        id=r.id,
        name=r.name,
        source=r.source,
        account=r.account,
        goal=r.goal,
        enabled=r.enabled,
        daily_limit=r.daily_limit,
        filters=json.loads(r.filters_json),
        checks=json.loads(r.checks_json),
        last_error=r.last_error,
        last_poll_at=r.last_poll_at,
    )


@router.get("/rules")
async def rules(user=Depends(get_current_user)):
    async with async_session() as db:
        return [
            rule_out(r)
            for r in (
                await db.execute(
                    select(AutomationRule)
                    .where(AutomationRule.user_id == user.id)
                    .order_by(AutomationRule.created_at.desc())
                )
            ).scalars()
        ]


@router.post("/rules")
async def create_rule(body: RuleInput, user=Depends(get_current_user)):
    data = body.model_dump()
    checks = data.pop("checks")
    filters = {k: data.pop(k) for k in ("sender_contains", "text_contains", "folder_prefix")}
    async with async_session() as db:
        rule = AutomationRule(user_id=user.id, **data, filters_json=json.dumps(filters), checks_json=json.dumps(checks))
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule_out(rule)


class Enable(BaseModel):
    enabled: bool


@router.put("/rules/{rule_id}/enabled")
async def toggle_rule(rule_id: str, body: Enable, user=Depends(get_current_user)):
    async with async_session() as db:
        rule = await db.get(AutomationRule, rule_id)
        if not rule or rule.user_id != user.id:
            raise HTTPException(404, "Automatisme introuvable")
        if body.enabled and not rule.enabled:
            rule.cursor_json = json.dumps(
                {"since": int(datetime.now(timezone.utc).timestamp()), "generation": uuid.uuid4().hex}
            )
            # Reactivating does not replay events deliberately paused by the user.
            pending = (
                await db.execute(
                    select(AutomationEvent).where(
                        AutomationEvent.rule_id == rule.id, AutomationEvent.status == "pending"
                    )
                )
            ).scalars()
            for event in pending:
                event.status = "cancelled"
        rule.enabled = body.enabled
        rule.last_error = None
        await db.commit()
        return rule_out(rule)


class Preview(BaseModel):
    sender: str = Field("", max_length=500)
    text: str = Field("", max_length=1000)
    path: str = Field("", max_length=1000)


@router.post("/rules/{rule_id}/preview")
async def preview_rule(rule_id: str, body: Preview, user=Depends(get_current_user)):
    async with async_session() as db:
        rule = await db.get(AutomationRule, rule_id)
        if not rule or rule.user_id != user.id:
            raise HTTPException(404, "Automatisme introuvable")
        return {
            "matches": matches(json.loads(rule.filters_json), body.model_dump()),
            "goal": rule.goal,
            "executed": False,
        }


@router.get("/events")
async def events(user=Depends(get_current_user)):
    from app.models.mission import Mission

    async with async_session() as db:
        rows = (
            await db.execute(
                select(AutomationEvent, Mission)
                .outerjoin(Mission, Mission.id == AutomationEvent.mission_id)
                .where(AutomationEvent.user_id == user.id)
                .order_by(AutomationEvent.created_at.desc())
                .limit(100)
            )
        ).all()
        return [
            dict(
                id=e.id,
                rule_id=e.rule_id,
                created_at=e.created_at,
                status=m.status if m else e.status,
                mission_id=e.mission_id,
                payload=json.loads(e.payload_json),
                summary=m.final_summary if m else None,
            )
            for e, m in rows
        ]


class PreferencesInput(BaseModel):
    read: Literal["inherit", "confirm", "deny"] = "inherit"
    write: Literal["inherit", "confirm", "deny"] = "inherit"
    engage: Literal["inherit", "confirm", "deny"] = "inherit"
    system: Literal["inherit", "confirm", "deny"] = "inherit"
    unknown: Literal["inherit", "confirm", "deny"] = "inherit"
    notifications: Literal["important", "all", "none"] = "important"


@router.get("/preferences")
async def preferences(user=Depends(get_current_user)):
    async with async_session() as db:
        row = await db.get(AutonomyPreferences, user.id)
        return {
            **PreferencesInput().model_dump(),
            **(json.loads(row.rules_json) if row else {}),
            "notifications": row.notifications if row else "important",
        }


@router.put("/preferences")
async def save_preferences(body: PreferencesInput, user=Depends(get_current_user)):
    data = body.model_dump()
    mode = data.pop("notifications")
    async with async_session() as db:
        row = await db.get(AutonomyPreferences, user.id)
        if not row:
            row = AutonomyPreferences(user_id=user.id)
            db.add(row)
        row.rules_json = json.dumps(data)
        row.notifications = mode
        await db.commit()
    return body.model_dump()


@router.get("/follow")
async def follow(user=Depends(get_current_user)):
    from app.models.mission import Mission

    async with async_session() as db:
        rows = (
            await db.execute(
                select(Mission, MissionAssurance)
                .outerjoin(MissionAssurance, Mission.id == MissionAssurance.mission_id)
                .where(Mission.user_id == user.id)
                .order_by(Mission.updated_at.desc())
                .limit(100)
            )
        ).all()
        return [
            dict(
                id=m.id,
                title=m.title,
                status=m.status,
                question=m.pending_question,
                waiting_for=a.waiting_for if a else None,
                checks=json.loads(a.checks_json) if a else [],
                results=json.loads(a.results_json) if a else [],
                provider_retries=m.provider_retries,
            )
            for m, a in rows
        ]


class ChecksInput(BaseModel):
    checks: list[Check] = Field(default_factory=list, max_length=20)


@router.put("/missions/{mid}/checks")
async def set_checks(mid: str, body: ChecksInput, user=Depends(get_current_user)):
    from app.models.mission import Mission

    async with async_session() as db:
        m = await db.get(Mission, mid)
        if not m or m.user_id != user.id:
            raise HTTPException(404, "Mission introuvable")
        if m.status not in {"draft", "paused", "waiting_user"}:
            raise HTTPException(409, "Mets la mission en pause pour modifier ses critères.")
        a = await db.get(MissionAssurance, mid)
        if not a:
            a = MissionAssurance(mission_id=mid, user_id=user.id)
            db.add(a)
        a.checks_json = json.dumps([c.model_dump() for c in body.checks])
        a.results_json = "[]"
        a.retries = 0
        a.verified_at = None
        await db.commit()
        return {"checks": body.model_dump()["checks"]}


@router.get("/missions/{mid}/receipts")
async def receipts(mid: str, user=Depends(get_current_user)):
    from app.models.mission import Mission
    from app.models.autonomy import ActionReceipt

    async with async_session() as db:
        m = await db.get(Mission, mid)
        if not m or m.user_id != user.id:
            raise HTTPException(404, "Mission introuvable")
        rows = (
            await db.execute(
                select(ActionReceipt)
                .where(ActionReceipt.mission_id == mid, ActionReceipt.user_id == user.id)
                .order_by(ActionReceipt.created_at.desc())
                .limit(100)
            )
        ).scalars()
        return [
            dict(id=r.id, tool_name=r.tool_name, status=r.status, result=r.result, created_at=r.created_at)
            for r in rows
        ]


class Resolve(BaseModel):
    decision: Literal["done", "retry"]
    note: str = Field(min_length=5, max_length=1000)


@router.post("/receipts/{rid}/resolve")
async def resolve_receipt(rid: str, body: Resolve, user=Depends(get_current_user)):
    from app.models.mission import Mission
    from app.models.autonomy import ActionReceipt

    async with async_session() as db:
        r = await db.get(ActionReceipt, rid)
        if not r or r.user_id != user.id:
            raise HTTPException(404, "Action introuvable")
        m = await db.get(Mission, r.mission_id)
        if not m or m.status not in {"waiting_user", "paused"}:
            raise HTTPException(409, "Attends que la mission soit suspendue.")
        if r.status not in {"started", "uncertain"}:
            raise HTTPException(409, "Action déjà examinée")
        r.status = "human_confirmed" if body.decision == "done" else "retry_allowed"
        r.result = "Vérification humaine : " + body.note
        await db.commit()
    return {"status": r.status}


@router.get("/procedures")
async def procedures(user=Depends(get_current_user)):
    from app.models.learned_skill import LearnedSkill
    from app.models.autonomy import ProcedureTrial
    from sqlalchemy import func

    async with async_session() as db:
        skills = (
            (
                await db.execute(
                    select(LearnedSkill).where(
                        LearnedSkill.user_id == user.id, LearnedSkill.status.in_(["active", "stale"])
                    )
                )
            )
            .scalars()
            .all()
        )
        counts = (
            await db.execute(
                select(ProcedureTrial.skill_id, ProcedureTrial.outcome, func.count())
                .where(ProcedureTrial.user_id == user.id)
                .group_by(ProcedureTrial.skill_id, ProcedureTrial.outcome)
            )
        ).all()
        stats = {}
        for sid, status, n in counts:
            stats.setdefault(sid, {})[status] = n
        return [
            dict(
                id=s.id,
                name=s.name,
                description=s.description,
                status=s.status,
                pinned=s.pinned,
                counts=stats.get(s.id, {}),
                suspension=json.loads(s.frontmatter_json or "{}").get("autonomy_suspended"),
            )
            for s in skills
        ]


@router.put("/procedures/{sid}/enabled")
async def toggle_procedure(sid: str, body: Enable, user=Depends(get_current_user)):
    from app.models.learned_skill import LearnedSkill
    from app.services.frozen_memory import invalidate_user

    async with async_session() as db:
        s = await db.get(LearnedSkill, sid)
        if not s or s.user_id != user.id:
            raise HTTPException(404, "Procédure introuvable")
        if s.status not in {"active", "stale"}:
            raise HTTPException(409, "Cette procédure doit être validée dans Compétences.")
        s.status = "active" if body.enabled else "stale"
        fm = json.loads(s.frontmatter_json or "{}")
        fm.pop("autonomy_suspended", None)
        s.frontmatter_json = json.dumps(fm)
        if body.enabled:
            s.promoted_at = datetime.now(timezone.utc)
        await db.commit()
    invalidate_user(user.id)
    from app.services.learning import learned_tools_runtime

    learned_tools_runtime.invalidate(user.id)
    return {"status": s.status}
