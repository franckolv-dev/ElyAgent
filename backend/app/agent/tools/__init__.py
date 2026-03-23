# Tools are now managed by the SkillRegistry (app.skills).
# This shim exists for backward-compatibility only.
# New code should use: from app.skills import get_skill_registry

from app.skills.registry import get_skill_registry as _get_registry


def _all_tools():
    """Lazily fetched tool list — always reflects the current registry state."""
    return _get_registry().all_tools


# WARNING: do NOT add a module-level `all_tools = _all_tools()` here.
# register_all() has not been called yet at import time, so the registry
# is empty and the call would always return an empty list.
# Use get_skill_registry().all_tools directly instead.
