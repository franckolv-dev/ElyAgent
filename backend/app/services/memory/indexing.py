"""Progressive derived indexes with durable checkpoints and canonical hydration."""

import asyncio
import hashlib
import json
import uuid
from sqlalchemy import select
from app.database import async_session
from app.models.user_memory import UserProfile
from app.models.memory_context import MemoryCheckpoint
from app.services.memory._infra import get_memory_infra
from app.services.memory._constants import VECTOR_DIM
from app.services.fts_store import _connect, _db_path, _CREATE_TABLE

PROFILE_COLLECTION = "profile_facts"


async def index_batch():
    """At most 64 changed facts + one knowledge page per tick; no LLM required."""
    from qdrant_client.models import VectorParams, Distance, PointStruct

    infra = get_memory_infra()
    async with async_session() as db:
        pending = (
            (await db.execute(select(MemoryCheckpoint).where(MemoryCheckpoint.key.like("profile-delete:%")).limit(64)))
            .scalars()
            .all()
        )
    from app.services.memory.editing import remove_profile_index

    for row in pending:
        item = json.loads(row.value)
        await remove_profile_index(item["user_id"], item["entry_id"])

    if not await asyncio.to_thread(infra.client.collection_exists, PROFILE_COLLECTION):
        await asyncio.to_thread(
            infra.client.create_collection,
            collection_name=PROFILE_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
    async with async_session() as db:
        rows = (await db.execute(select(UserProfile).order_by(UserProfile.id))).scalars().all()
        versions = {
            r.key: r.value
            for r in (await db.execute(select(MemoryCheckpoint).where(MemoryCheckpoint.key.like("profile-index:%"))))
            .scalars()
            .all()
        }
    indexed = 0
    for row in rows:
        content = f"{row.key}: {row.value}"
        version = hashlib.sha256(
            json.dumps([content, row.scope, row.pinned, str(row.expires_at)], ensure_ascii=False).encode()
        ).hexdigest()
        key = f"profile-index:{row.id}:{row.user_id}"
        if versions.get(key) == version:
            continue
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ely:{key}"))
        payload = {
            "user_id": row.user_id,
            "profile_id": row.id,
            "content": content,
            "scope": row.scope,
            "pinned": row.pinned,
            "source": row.source,
            "created_at": str(row.last_seen),
            "expires_at": str(row.expires_at) if row.expires_at else None,
        }
        await asyncio.to_thread(
            infra.client.upsert,
            collection_name=PROFILE_COLLECTION,
            points=[PointStruct(id=point_id, vector=await infra.embed(content), payload=payload)],
        )
        async with async_session() as db:
            still_exists = await db.scalar(
                select(UserProfile.id).where(UserProfile.id == row.id, UserProfile.user_id == row.user_id)
            )
        if not still_exists:
            # Deletion may race a slow embedding/upsert. Do not resurrect its index.
            await remove_profile_index(row.user_id, str(row.id))
            continue
        await write_fts([(content, row.user_id, PROFILE_COLLECTION, point_id)])
        async with async_session() as db:
            record = await db.get(MemoryCheckpoint, key)
            if record:
                record.value = version
            else:
                db.add(MemoryCheckpoint(key=key, value=version))
            await db.commit()
        indexed += 1
        if indexed >= 64:
            break
    # Existing documents remain readable by dense search while FTS catches up.
    key = "knowledge-fts-v1"
    async with async_session() as db:
        record = await db.get(MemoryCheckpoint, key)
        cursor = record.value if record else ""
    if cursor != "done":
        points, next_cursor = await asyncio.to_thread(
            infra.client.scroll, collection_name="knowledge", offset=cursor or None, limit=128, with_payload=True
        )
        await write_fts(
            [
                (p.payload.get("content", ""), p.payload["user_id"], "knowledge", str(p.id))
                for p in points
                if p.payload.get("user_id")
            ]
        )
        async with async_session() as db:
            record = await db.get(MemoryCheckpoint, key)
            value = str(next_cursor) if next_cursor else "done"
            if record:
                record.value = value
            else:
                db.add(MemoryCheckpoint(key=key, value=value))
            await db.commit()
    return indexed


async def write_fts(rows):
    from app.services.memory.query_cache import invalidate

    async with _connect(_db_path()) as db:
        await db.execute(_CREATE_TABLE)
        for text, uid, collection, pid in rows:
            await db.execute(
                "DELETE FROM memory_fts WHERE user_id=? AND collection=? AND qdrant_id=?", (uid, collection, pid)
            )
            await db.execute(
                "INSERT INTO memory_fts(text,user_id,collection,qdrant_id) VALUES(?,?,?,?)",
                (text, uid, collection, pid),
            )
        await db.commit()
    for uid in {r[1] for r in rows}:
        invalidate(uid)
