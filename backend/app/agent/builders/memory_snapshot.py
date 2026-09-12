"""Compatibility builder: memory is selected for this request, never frozen."""

from app.services.memory.context import dossier


async def build_memory_snapshot(*, messages, user_id, user_query, memory, use_compact, conversation_id=""):
    text = await dossier(user_id, user_query, conversation_id)
    # Both model paths receive the same evidence; compact must not truncate proofs.
    return text, {"user_profile": text, "memories": [], "constraints": []} if use_compact else None
