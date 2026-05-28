# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_d_hitl_refusal_persisted.py
# @brief      Sprint 3.7 V1.5 Jalon 7 — canonical scenario D : ensure a
#             HITL refusal recorded via the learning signals service
#             lands in the `hitl_refusals` table with the expected shape.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario D — HITL refusal persistence.

The scenario simulates the agent code path that fires when the user
clicks "Refuser" or "Toujours interdire" on a HITL prompt. It does
NOT spin up the full LangGraph agent — it calls the recording service
directly with a synthetic payload and verifies the row hits the SQL
table with the right fields. That's exactly what we need to know is
unbroken end-to-end.

Used by `bench.run_canonical` to detect regressions on Sprint 3.7 V1
Jalon 2 wiring.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select


NAME = "D — HITL refusal persisted"
DESCRIPTION = (
    "Records a synthetic HITL `deny` and verifies the row lands "
    "in `hitl_refusals` with the expected fields + prompt_version hash."
)


async def run() -> dict:
    from app.database import async_session, init_db
    from app.models.hitl_refusal import HitlRefusal
    from app.models.user import User
    from app.services.learning import record_hitl_refusal

    await init_db()

    # Unique user_id per run avoids cross-run pollution on the shared
    # SQLite file and makes the scenario idempotent.
    uid = f"bench_d_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"bench_d_{uid[-8:]}",
            email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()

    row_id = await record_hitl_refusal(
        user_id=uid,
        conversation_id="bench-conv-d",
        tool_name="gmail_trash_emails",
        args={"query": "newsletter"},
        action_description="Trash 12 newsletter emails",
        decision="deny",
        reason="user-provided",
    )

    if row_id is None:
        return {"pass": False, "reason": "record_hitl_refusal returned None"}

    async with async_session() as db:
        row = (await db.execute(
            select(HitlRefusal).where(HitlRefusal.id == row_id)
        )).scalar_one_or_none()

    if row is None:
        return {"pass": False, "reason": f"row id {row_id} not found"}

    # Assertions
    checks = {
        "user_id_match": row.user_id == uid,
        "conversation_id_match": row.conversation_id == "bench-conv-d",
        "tool_name_match": row.tool_name == "gmail_trash_emails",
        "decision_match": row.decision == "deny",
        "reason_match": row.reason == "user-provided",
        "prompt_version_filled": bool(row.prompt_version),
        "args_redacted_json": "newsletter" in (row.args_redacted or ""),
    }
    failed = [k for k, v in checks.items() if not v]
    return {
        "pass": not failed,
        "checks": checks,
        "row_id": row_id,
        "failed_checks": failed,
    }
