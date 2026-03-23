# Tools are now managed by the SkillRegistry (app.skills).
# This shim exists for backward-compatibility only.
# New code should use: from app.skills import get_skill_registry

from app.skills.registry import get_skill_registry as _get_registry


def _all_tools():
    """Lazily fetched tool list — always reflects the current registry state."""
    return _get_registry().all_tools


# all_tools is evaluated lazily; any module-level consumer should call
# get_skill_registry().all_tools instead of importing this symbol.
all_tools = _all_tools()
