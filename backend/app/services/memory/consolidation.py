"""Restart-safe consolidation of execution evidence into existing episodic storage.

Checkpoints are written only after a deterministic-ID upsert succeeds. A crash
between Qdrant and SQL repeats an upsert, never creates another episode.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from app.database import async_session
from app.models.memory_context import MemoryCheckpoint
from app.services.memory.selection import truncate

logger = logging.getLogger(__name__)


async def save_episode(user_id: str, key: str, version: str, text: str, source: str):
    from app.services.memory._infra import get_memory_infra
    from app.services.memory._constants import COLLECTION_INTERACTIONS
    from app.services.fts_store import get_fts_store
    from qdrant_client.models import PointStruct

    async with async_session() as db:
        checkpoint = await db.get(MemoryCheckpoint, key)
        if checkpoint and checkpoint.value in {version, "forgotten", "corrected"}:
            return False
    infra = get_memory_infra()
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ely:episode:{user_id}:{key}"))
    vector = await infra.embed(text)
    await asyncio.to_thread(
        infra.client.upsert,
        collection_name=COLLECTION_INTERACTIONS,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "user_id": user_id,
                    "content": text,
                    "user_message": text,
                    "assistant_message": "",
                    "source": source,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "checkpoint_key": key,
                    "version": version,
                    "scope": "",
                    "kind": "execution_evidence",
                },
            )
        ],
    )
    await get_fts_store().store(text, user_id, COLLECTION_INTERACTIONS, point_id)
    async with async_session() as db:
        row = await db.get(MemoryCheckpoint, key)
        if row:
            row.value = version
        else:
            db.add(MemoryCheckpoint(key=key, value=version))
        await db.commit()
    return True


async def run_consolidation():
    from app.services.memory.indexing import index_batch

    try:
        await index_batch()
    except Exception as exc:
        logger.warning("Memory derived indexing deferred: %s", type(exc).__name__)
    from app.models.mission import Mission
    from app.models.scheduled_task import ScheduledTask
    from app.models.autonomy import ActionReceipt

    async with async_session() as db:
        missions = (await db.execute(select(Mission).where(Mission.started_at.is_not(None)))).scalars().all()
        tasks = (
            (
                await db.execute(
                    select(ScheduledTask).where(
                        ScheduledTask.last_run_at.is_not(None), ScheduledTask.last_status.in_(["success", "error"])
                    )
                )
            )
            .scalars()
            .all()
        )
    for m in missions:
        try:
            async with async_session() as db:
                receipts = (
                    (
                        await db.execute(
                            select(ActionReceipt)
                            .where(
                                ActionReceipt.mission_id == m.id,
                                ActionReceipt.user_id == m.user_id,
                                ActionReceipt.created_at >= m.started_at,
                            )
                            .order_by(ActionReceipt.created_at.desc())
                            .limit(8)
                        )
                    )
                    .scalars()
                    .all()
                )
            evidence = [
                {"receipt": r.id, "tool": r.tool_name, "status": r.status, "result": truncate(r.result or "", 100)}
                for r in receipts
            ]
            text = json.dumps(
                {
                    "mission": m.title,
                    "goal": truncate(m.goal, 150),
                    "status": m.status,
                    "run": str(m.started_at),
                    "evidence": evidence,
                    "note": "Seuls les accusés success prouvent l’exécution. Les actions uncertain/started ne doivent pas être répétées sans vérification.",
                },
                ensure_ascii=False,
            )
            version = hashlib.sha256(text.encode()).hexdigest()
            await save_episode(m.user_id, f"mission:{m.id}:{m.started_at}", version, text, f"mission:{m.id}")
        except Exception as exc:
            logger.warning("Mission memory consolidation deferred: %s", type(exc).__name__)
    for task in tasks:
        try:
            text = f"Exécution de tâche planifiée {task.name} ({task.last_run_at}). Résultat rapporté, à vérifier avant de répéter une action : {truncate(task.last_result or '', 400)}"
            await save_episode(
                task.user_id,
                f"scheduled:{task.id}:{task.last_run_at}",
                str(task.last_run_at),
                text,
                f"scheduled:{task.id}",
            )
        except Exception as exc:
            logger.warning("Scheduled memory consolidation deferred: %s", type(exc).__name__)
    await drain_pending()


async def enqueue_conversation(conversation_id: str, user_id: str):
    from app.models.conversation import Conversation, Message

    async with async_session() as db:
        owner = await db.scalar(
            select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        if not owner:
            return
        last = await db.scalar(
            select(Message.id)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        key = f"conversation:{conversation_id}:{last}"
        if not await db.get(MemoryCheckpoint, key):
            db.add(
                MemoryCheckpoint(
                    key=key,
                    value=json.dumps(
                        {"status": "pending", "user_id": user_id, "conversation_id": conversation_id, "attempts": 0}
                    ),
                )
            )
            await db.commit()


async def drain_pending():
    from app.services.memory.maintenance_rapid import get_maintenance_agent_rapid

    async with async_session() as db:
        pending = (
            (
                await db.execute(
                    select(MemoryCheckpoint)
                    .where(
                        MemoryCheckpoint.key.like("conversation:%"),
                        MemoryCheckpoint.value.like('%"status": "pending"%'),
                    )
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
    for row in pending:
        data = json.loads(row.value)
        try:
            result = await asyncio.wait_for(
                get_maintenance_agent_rapid().consolidate(data["conversation_id"], data["user_id"]), timeout=30
            )
        except Exception as exc:
            result = {"status": "failed", "reason": type(exc).__name__}
        data["attempts"] += 1
        if result.get("status") in {"ok", "skipped"}:
            data["status"] = "done"
        elif data["attempts"] >= 3:
            data["status"] = "failed"
        data["result"] = result
        async with async_session() as db:
            current = await db.get(MemoryCheckpoint, row.key)
            current.value = json.dumps(data)
            await db.commit()
