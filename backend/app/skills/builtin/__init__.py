"""Builtin skill registration.

Importing this package (or calling ``register_all()``) registers all
built-in skills into the global SkillRegistry.  ``app.main`` does this
once at application startup, before any request is served.

To add a new built-in skill:
  1. Create ``app/skills/builtin/my_skill.py``
  2. At module level, call ``get_skill_registry().register(Skill(...))``
  3. Add an import of your module in the list below.
"""


def register_all() -> None:
    """Import every builtin skill module to trigger side-effect registration."""
    # Existing tools wrapped as skills
    from app.skills.builtin import system_skill      # noqa: F401
    from app.skills.builtin import gmail_skill       # noqa: F401
    from app.skills.builtin import calendar_skill    # noqa: F401
    from app.skills.builtin import drive_skill       # noqa: F401
    from app.skills.builtin import docs_skill        # noqa: F401
    from app.skills.builtin import sheets_skill      # noqa: F401
    from app.skills.builtin import tasks_skill       # noqa: F401
    from app.skills.builtin import scheduler_skill   # noqa: F401
    # New packaged skills
    from app.skills.builtin import weather_skill     # noqa: F401
    from app.skills.builtin import news_skill        # noqa: F401
    from app.skills.builtin import translate_skill   # noqa: F401
    from app.skills.builtin import browser_skill     # noqa: F401
