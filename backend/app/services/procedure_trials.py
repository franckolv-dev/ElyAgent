"""Measure procedures served on an actual turn; no success inferred from loading."""

import hashlib
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import async_session
from app.models.autonomy import ProcedureTrial
from app.models.learned_skill import LearnedSkill, SkillStatus


async def record_trial(user_id, skill_id, run_key, outcome):
    if outcome not in {"success", "failed", "pending"}:
        raise ValueError("Verdict invalide")
    async with async_session() as db:
        skill = await db.get(LearnedSkill, skill_id)
        if not skill or skill.user_id != user_id or skill.status != SkillStatus.ACTIVE:
            return
        db.add(ProcedureTrial(user_id=user_id, skill_id=skill_id, run_key=run_key, outcome=outcome))
        try:
            await db.flush()
        except IntegrityError:
            return
        latest = (
            (
                await db.execute(
                    select(ProcedureTrial.outcome)
                    .where(ProcedureTrial.skill_id == skill_id)
                    .order_by(ProcedureTrial.created_at.desc())
                    .limit(3)
                )
            )
            .scalars()
            .all()
        )
        if len(latest) == 3 and all(x == "failed" for x in latest) and not skill.pinned:
            skill.status = SkillStatus.STALE
            fm = json.loads(skill.frontmatter_json or "{}")
            fm["autonomy_suspended"] = "Trois exécutions observées en échec consécutives"
            skill.frontmatter_json = json.dumps(fm, ensure_ascii=False)
        await db.commit()
        if skill.status == SkillStatus.STALE:
            from app.services.frozen_memory import invalidate_user
            from app.services.learning import learned_tools_runtime

            invalidate_user(user_id)
            learned_tools_runtime.invalidate(user_id)


async def observe_turn(user_id, messages, conversation_id, block):
    from app.services.learning.active_skills import playbook_names_in_block
    from app.services.learning.playbook_usage import closest_playbook
    from app.agent.tool_failure import dit_un_echec

    # Earlier turns must not contaminate today's attribution or fingerprint.
    start = next((i for i in range(len(messages) - 1, -1, -1) if getattr(messages[i], "type", "") == "human"), 0)
    turn = messages[start:]
    calls = {
        tc["id"]: tc["name"] for m in turn for tc in getattr(m, "tool_calls", []) if tc.get("id") and tc.get("name")
    }
    names = playbook_names_in_block(block)
    if not calls or not names or not conversation_id:
        return
    async with async_session() as db:
        skills = (
            (
                await db.execute(
                    select(LearnedSkill).where(
                        LearnedSkill.user_id == user_id,
                        LearnedSkill.name.in_(names),
                        LearnedSkill.status == SkillStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
    sid = closest_playbook([(s.id, s.content) for s in skills], calls.values())
    if not sid:
        return
    from app.services.learning.playbook_usage import tools_prescribed_and_called

    skill = next(s for s in skills if s.id == sid)
    prescribed = tools_prescribed_and_called(skill.content, calls.values())
    results = [
        m
        for m in turn
        if getattr(m, "type", "") == "tool" and calls.get(getattr(m, "tool_call_id", None)) in prescribed
    ]
    expected = [cid for cid, name in calls.items() if name in prescribed]
    complete = len({m.tool_call_id for m in results}) == len(expected)
    failed = any(getattr(m, "status", "") == "error" or dit_un_echec(str(m.content)) for m in results)
    outcome = "failed" if failed else ("success" if complete else "pending")
    key = hashlib.sha256(json.dumps([conversation_id, sorted(calls)], ensure_ascii=False).encode()).hexdigest()
    await record_trial(user_id, sid, key, outcome)


def schedule_observation(state, messages):
    from app.services.learning.playbook_usage import _bloc_injecte
    from app.services.background_tasks import spawn

    cid = state.get("conversation_id", "")
    block = _bloc_injecte(cid)
    if block and state.get("user_id"):
        spawn(observe_turn(state["user_id"], list(messages), cid, block), label="procedure_trial", detach_context=True)
