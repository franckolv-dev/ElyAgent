# Adding a tool to ELY

> **TL;DR** — Write your `@tool` callable, add `@register(...)` on top.
> That's it. ELY's auto-discovery (Sprint 2, May 2026) picks it up at
> boot and groups it into the right `Skill` automatically.

---

## The modern pattern (recommended since v1.2)

Drop a new file under `backend/app/agent/tools/` containing your tool
and a `@register` decorator. **No other file needs to be touched** for
the tool to become available to the agent across the matching
specialist domain.

```python
# backend/app/agent/tools/my_new_tool.py

from typing import Annotated
from langchain_core.tools import InjectedToolArg, tool

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,                       # specialist domain(s)
    skill_name="my_new_skill",                     # stable DB key
    skill_display_name="My New Capability",        # shown in Settings
    skill_description="Does X with Y.",            # one-liner in Settings
    skill_icon="🆕",                                # single emoji
    enabled_by_default=True,                       # default for new users
)
@tool
async def my_new_tool(
    arg: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Docstring shown to the LLM — be precise about WHEN to call this tool.

    Tools without precise call-time guidance get called either never or
    constantly. The LLM only has this docstring to decide.
    """
    return f"got {arg}"
```

That's it. At app boot, `auto_discover_tools()` walks
`backend/app/agent/tools/`, imports every module, finds the
`@register` decorations, and creates the `Skill("my_new_skill", ...)`
automatically with `[my_new_tool]` as its tool list.

### Multiple tools, one skill

Two or more tools sharing the same `skill_name` collapse into a single
`Skill`. Useful when you have a related set of operations
(e.g. `gmail_list_emails` + `gmail_send_email`).

```python
@register(domain=Domain.WORKSPACE, skill_name="my_skill", skill_display_name=..., ...)
@tool
def list_things(): ...

@register(domain=Domain.WORKSPACE, skill_name="my_skill", skill_display_name=..., ...)
@tool
def update_thing(): ...
```

Both end up under the same `Skill("my_skill", tools=[list_things, update_thing])`.

### Decorator order matters

`@register` goes **above** `@tool`. The decorator chain runs
bottom-up: first `@tool` wraps your function into a LangChain `Tool`
object (with `.name`, `.description` derived from the function name
and docstring), then `@register` attaches metadata to that wrapped
object.

```python
# ✅ Correct
@register(...)
@tool
def my_tool(): ...

# ❌ Wrong — @register sees the raw function, not the LangChain Tool
@tool
@register(...)
def my_tool(): ...
```

### Default toolset profile

For the tool to be available in the **default** profile that ships to
every user, also add its `.name` to `_DEFAULT_TOOLS` in
`backend/app/agent/toolset_profiles.py`. (This step will be eliminated
by a follow-up refactor — for now it's the only manual touch left.)

---

## The legacy pattern (still supported)

The old pattern with a manual `Skill(...)` declaration in
`backend/app/skills/builtin/<name>_skill.py` still works and will keep
working indefinitely. New skills should use `@register`; existing
skills migrate at their own pace.

The auto-discovery scanner **skips any `skill_name` already in the
registry** when it runs. That means you can have a legacy file and a
decorated tool in different stages of migration — there's never a
conflict.

```python
# backend/app/skills/builtin/legacy_skill.py — old pattern, still works
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.legacy_tool import my_legacy_tool

get_skill_registry().register(Skill(
    name="legacy_skill",
    display_name="Legacy",
    description="Old style, still alive.",
    icon="🛠️",
    tools=[my_legacy_tool],
    domains=[Domain.WORKSPACE],
))
```

### Migrating a legacy skill

1. Move the `Skill(...)` metadata into a `@register(...)` on the tool itself.
2. Delete the corresponding lines from
   `backend/app/skills/builtin/<name>_skill.py`. If that file becomes
   empty, delete it AND remove its import from
   `backend/app/skills/builtin/__init__.py`.
3. Run the test suite — the existing `test_skill_registry.py` and
   `test_toolset_profiles.py` will catch any regression.

The first migrated tool is `search_past_conversations_tool` (commit
introducing Sprint 2) — read its diff for a concrete example.

---

## Why this matters (the triple-registration trap)

Before Sprint 2, adding a tool required touching **three** places, with
silent failures if you forgot one:

1. Define the `@tool` in `backend/app/agent/tools/`
2. Import it into a skill file and `register(Skill(...))` it
3. Add its `.name` string to `_DEFAULT_TOOLS`

Forgetting step 2 → tool exists but is never bound to any LLM.
Forgetting step 3 → tool exists but isn't in the default profile.

The roadmap documented this as a real source of bugs ("tool invisible"
class). The `@register` decorator collapses steps 1+2 into a single
declarative line — and the auto-discovery scanner ensures there's no
silent failure: if a tool can't be imported at boot, you see a
`WARNING` in the logs immediately.

---

## Testing your new tool

Three quick checks before opening a PR:

```bash
cd backend

# 1) Tool gets discovered and registered
.venv/bin/python -m pytest tests/test_auto_discover.py -v

# 2) Tool ends up in the right domain
.venv/bin/python -m pytest tests/test_skill_registry.py -v

# 3) Tool is in the default profile (if it should be)
.venv/bin/python -m pytest tests/test_toolset_profiles.py -v
```

The full suite (`.venv/bin/python -m pytest -q`) should stay green —
zero regression is the bar for any tool addition.

---

*Document created during Sprint 2 (Tool registry auto-discovery), 17 May 2026.
See [ROADMAP.md](../ROADMAP.md#sprint-2--developer-experience) for context.*
