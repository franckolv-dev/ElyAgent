"""Owner-scoped corrections and deletion, with historical values and cache eviction."""

import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy import select, delete
from app.database import async_session
from app.models.user_memory import UserProfile
from app.models.memory_context import MemoryVersion, MemorySelection, MemoryCheckpoint
from app.services.memory._infra import get_memory_infra
from app.services.memory.inspection import _INSPECTABLE


async def validate_scope(user_id: str, scope: str):
    if not scope:
        return
    from app.models.mission import Mission

    if scope.startswith("account:"):
        from app.models.google_account import GoogleAccount

        async with async_session() as db:
            found = await db.scalar(
                select(GoogleAccount.id).where(GoogleAccount.id == scope[8:], GoogleAccount.user_id == user_id)
            )
        if not found:
            raise ValueError("Compte introuvable.")
        return
    if not scope.startswith("mission:"):
        raise ValueError("Choisir un périmètre personnel ou une mission existante.")
    async with async_session() as db:
        found = await db.scalar(select(Mission.id).where(Mission.id == scope[8:], Mission.user_id == user_id))
        if not found:
            raise ValueError("Mission introuvable.")


async def invalidate(user_id: str):
    from app.services.frozen_memory import invalidate_user

    invalidate_user(user_id)
    from app.services.memory.query_cache import invalidate as invalidate_queries

    invalidate_queries(user_id)
    # Selection traces contain snippets: correction/forget must remove them too.
    async with async_session() as db:
        await db.execute(delete(MemorySelection).where(MemorySelection.user_id == user_id))
        await db.commit()


async def edit(user_id: str, family: str, entry_id: str, content: str, scope: str, pinned: bool):
    if not content.strip():
        raise ValueError("Le souvenir ne peut pas être vide.")
    await validate_scope(user_id, scope)
    now = datetime.now(timezone.utc)
    if family == "profile":
        if not entry_id.isdigit():
            return False
        async with async_session() as db:
            row = await db.scalar(
                select(UserProfile).where(UserProfile.id == int(entry_id), UserProfile.user_id == user_id)
            )
            if not row:
                return False
            # DB trigger versions value updates, including non-UI writers.
            row.value = content
            row.scope = scope
            row.pinned = pinned
            row.confirmed = True
            row.source = "Correction utilisateur"
            row.last_seen = now
            row.expires_at = None
            await db.commit()
    else:
        if family not in _INSPECTABLE or family == "error":
            raise ValueError("Cette famille ne permet pas la correction d’un souvenir.")
        collection, fields, _ = _INSPECTABLE[family]
        infra = get_memory_infra()
        points = await infra.points_by_ids(collection, [entry_id], user_id)
        if not points:
            return False
        old = dict(points[0].payload)
        from qdrant_client.models import PointStruct

        payload = {
            **old,
            fields[0]: content,
            "scope": scope,
            "pinned": pinned,
            "confirmed": True,
            "source": "Correction utilisateur",
            "updated_at": now.isoformat(),
            "version": int(old.get("version", 1)) + 1,
        }
        # On correction of an episode remove the old response, not just its label.
        for field in fields[1:]:
            payload.pop(field, None)
        vector = await infra.embed(content)
        await asyncio.to_thread(
            infra.client.upsert,
            collection_name=collection,
            points=[PointStruct(id=entry_id, vector=vector, payload=payload)],
        )
        from app.services.fts_store import get_fts_store

        await get_fts_store().store(content, user_id, collection, entry_id)
        async with async_session() as db:
            if old.get("checkpoint_key"):
                checkpoint = await db.get(MemoryCheckpoint, old["checkpoint_key"])
                if checkpoint:
                    checkpoint.value = "corrected"
            db.add(
                MemoryVersion(
                    user_id=user_id,
                    family=family,
                    entry_id=entry_id,
                    content=" ".join(str(old.get(f, "")) for f in fields),
                    metadata_json=json.dumps(old, ensure_ascii=False),
                )
            )
            await db.commit()
    await invalidate(user_id)
    return True


async def forget_profile(user_id: str, entry_id: str):
    if not entry_id.isdigit():
        return False
    async with async_session() as db:
        result = await db.execute(
            delete(UserProfile).where(UserProfile.id == int(entry_id), UserProfile.user_id == user_id)
        )
        if not result.rowcount:
            return False
        pending_key = f"profile-delete:{user_id}:{entry_id}"
        if not await db.get(MemoryCheckpoint, pending_key):
            db.add(MemoryCheckpoint(key=pending_key, value=json.dumps({"user_id": user_id, "entry_id": entry_id})))
        await db.execute(
            delete(MemoryVersion).where(
                MemoryVersion.user_id == user_id, MemoryVersion.family == "profile", MemoryVersion.entry_id == entry_id
            )
        )
        await db.commit()
    await remove_profile_index(user_id, entry_id)
    await invalidate(user_id)
    return True


async def remove_profile_index(user_id, entry_id):
    import uuid
    from app.services.memory.indexing import PROFILE_COLLECTION
    from app.services.fts_store import get_fts_store

    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ely:profile-index:{entry_id}:{user_id}"))
    # SQL is already canonical; absent/unavailable derived storage cannot make
    # the deleted fact visible because hydration rejects it on every read.
    try:
        await get_memory_infra().delete_point(PROFILE_COLLECTION, point_id, user_id)
        await get_fts_store().delete_point(point_id, user_id)
        async with async_session() as db:
            await db.execute(
                delete(MemoryCheckpoint).where(MemoryCheckpoint.key == f"profile-delete:{user_id}:{entry_id}")
            )
            await db.commit()
    except Exception:
        # The durable deletion queue retries; canonical hydration already refuses it.
        return False
    return True
