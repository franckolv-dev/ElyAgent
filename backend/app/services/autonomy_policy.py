"""User controls add restrictions; existing ACL, HITL and scoped access still apply."""

import json
import logging
from app.database import async_session
from app.models.autonomy import AutonomyPreferences

logger = logging.getLogger(__name__)


async def _preferences(user_id):
    """Absent or unreadable preferences add nothing: ACL and HITL still apply."""
    try:
        async with async_session() as db:
            return await db.get(AutonomyPreferences, user_id)
    except Exception as exc:
        logger.warning("Autonomy preferences unreadable for %s: %s", user_id[:8], type(exc).__name__)
        return None


async def permission_for(user_id, tool_name):
    from app.agent.tool_nature import effect_of

    row = await _preferences(user_id)
    if not row:
        return "inherit"
    rules = json.loads(row.rules_json)
    effect = effect_of(tool_name)
    category = {"LECTURE": "read", "ECRITURE": "write", "ENGAGEANT": "engage"}.get(effect, "unknown")
    values = [rules.get(category, "inherit")]
    if tool_name.startswith("desktop_"):
        values.append(rules.get("system", "inherit"))
    if "deny" in values:
        return "deny"
    if "confirm" in values:
        return "confirm"
    return "inherit"


async def should_notify(user_id, kind):
    p = await _preferences(user_id)
    mode = p.notifications if p else "important"
    return mode != "none" and (mode == "all" or kind != "completed")
