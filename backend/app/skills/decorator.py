# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/decorator.py
# @brief      @register decorator — Sprint 2 (tool registry auto-discovery).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""``@register(...)`` — declarative tool-to-skill binding.

Sprint 2 goal — kill the triple-registration trap:
  Before this module, adding a new tool required touching three places:
    1. Define the @tool in ``backend/app/agent/tools/``
    2. Import it into a file in ``backend/app/skills/builtin/`` and call
       ``get_skill_registry().register(Skill(name=..., tools=[...]))``
    3. Add the tool name as a string to ``_DEFAULT_TOOLS`` in
       ``backend/app/agent/toolset_profiles.py``

  Forgetting step 2 silently dropped the tool. Forgetting step 3 made
  it invisible to the default profile. The trap is documented in
  CLAUDE.md and on the public roadmap.

After this module, the only step left is:

    from app.skills.decorator import register
    from app.skills.base import Domain

    @register(
        domain=Domain.MEMORY,
        skill_name="memory_recall",
        skill_display_name="Mémoire transversale entre conversations",
        skill_description="Recherche cross-conversation via FTS5 + Ministral 3B local.",
        skill_icon="🧭",
    )
    @tool
    async def search_past_conversations_tool(...):
        ...

Decorator order matters: ``@register`` goes **above** ``@tool`` so it
sees the wrapped LangChain tool object (with ``.name`` and
``.description`` already populated) and can attach metadata to it.

How auto-discovery picks it up
-------------------------------
This decorator does NOT call ``get_skill_registry().register(...)``
itself. It only:
  - validates the metadata
  - attaches a sentinel attribute ``__ely_skill_metadata__`` to the
    decorated callable
  - records the callable in the module-level ``_PENDING`` dict so the
    discovery scanner (``auto_discover.py``) can find it after a sweep
    of all tool modules

This split lets the registration happen in a controlled order at app
startup (after the existing manual skills, before any request).

Backward compat
---------------
Skills that are still registered the old way (manual ``Skill(...)``
+ ``get_skill_registry().register(...)``) keep working unchanged. The
auto-discovery scanner skips any skill name that's already in the
registry — so during the migration period both patterns coexist.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.skills.base import Domain

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Metadata attached to each decorated tool
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _RegisteredToolMeta:
    """Metadata captured by ``@register`` and consumed by ``auto_discover``."""

    skill_name: str
    skill_display_name: str
    skill_description: str
    skill_icon: str
    domains: tuple[str, ...]
    scopes: tuple[str, ...]
    enabled_by_default: bool
    skill_version: str


# Sentinel attribute name. ``auto_discover`` searches every module for
# callables that carry this attribute.
META_ATTR = "__ely_skill_metadata__"


# Module-level registry of pending decorations. Populated at import time
# by every module that uses ``@register``. The discovery scanner reads
# from here, then clears the dict — so re-imports during tests don't
# accumulate ghost entries.
#
# Key = fully-qualified name of the decorated callable
#       (``app.agent.tools.session_search_tool.search_past_conversations_tool``)
# Value = (callable, metadata)
_PENDING: dict[str, tuple[Any, _RegisteredToolMeta]] = {}


# ──────────────────────────────────────────────────────────────────────
# The decorator itself
# ──────────────────────────────────────────────────────────────────────


def register(
    *,
    domain: str | list[str],
    skill_name: str,
    skill_display_name: str,
    skill_description: str,
    skill_icon: str = "🔧",
    scopes: list[str] | None = None,
    enabled_by_default: bool = True,
    skill_version: str = "1.0.0",
) -> Callable[[Any], Any]:
    """Attach skill metadata to a LangChain @tool.

    All keyword arguments mirror the ``Skill`` dataclass fields except
    that ``tools`` is implicit — the decorated function IS the tool.
    Multiple tools sharing the same ``skill_name`` will be grouped into
    a single Skill at discovery time.

    Args:
        domain: One specialist domain (``Domain.MEMORY``, …) or a list
            of domains. Use ``Domain.UNIVERSAL`` to inject the tool into
            every specialist.
        skill_name: Stable slug for the parent Skill (e.g.
            ``"memory_recall"``). Used as the DB key for per-user
            preferences — do NOT change it without a migration.
        skill_display_name: Human-readable name shown in Settings.
        skill_description: One-line description shown in Settings.
        skill_icon: Single emoji shown next to the display name.
        scopes: Logical permission scopes (e.g. ``["google_oauth"]``).
        enabled_by_default: Whether the parent Skill is on for new users.
        skill_version: SemVer of the parent Skill.

    Returns:
        The decorated callable, unchanged at the call-site, but with
        ``__ely_skill_metadata__`` attached. Also registered in the
        module-level ``_PENDING`` dict for the discovery scanner.

    Raises:
        ValueError: if any required field is empty or if ``domain``
            contains an unknown domain string.
    """
    # ── Normalise + validate inputs ───────────────────────────────────
    if not skill_name or not skill_name.strip():
        raise ValueError("@register: skill_name must not be empty")
    if not skill_display_name or not skill_display_name.strip():
        raise ValueError("@register: skill_display_name must not be empty")
    if not skill_description or not skill_description.strip():
        raise ValueError("@register: skill_description must not be empty")

    if isinstance(domain, str):
        domains_tuple: tuple[str, ...] = (domain,)
    else:
        domains_tuple = tuple(domain)
    if not domains_tuple:
        raise ValueError("@register: domain must not be empty")

    # Validate each domain string against the known set. This catches
    # typos like Domain.MEMOEY at decoration time rather than at
    # call-time when the agent tries to route a request.
    known = {
        Domain.RESEARCH, Domain.WORKSPACE, Domain.INFRA, Domain.CREATIVE,
        Domain.DATA, Domain.MEMORY, Domain.DESKTOP, Domain.GENERAL,
        Domain.SYSTEM, Domain.DIAG, Domain.UNIVERSAL,
    }
    for d in domains_tuple:
        if d not in known:
            raise ValueError(
                f"@register: unknown domain {d!r}. "
                f"Valid domains: {sorted(known)}"
            )

    scopes_tuple = tuple(scopes or [])

    meta = _RegisteredToolMeta(
        skill_name=skill_name,
        skill_display_name=skill_display_name,
        skill_description=skill_description,
        skill_icon=skill_icon,
        domains=domains_tuple,
        scopes=scopes_tuple,
        enabled_by_default=enabled_by_default,
        skill_version=skill_version,
    )

    def _wrap(target: Any) -> Any:
        # Attach metadata directly to the tool object (or unwrapped
        # function, if @register is applied below @tool by mistake).
        try:
            setattr(target, META_ATTR, meta)
        except (AttributeError, TypeError):
            # Some pydantic-validated tool objects forbid arbitrary
            # attribute setting. We still want to record the binding,
            # so we fall back to _PENDING only.
            logger.debug(
                "@register: cannot set %s on %r — keeping metadata in _PENDING only",
                META_ATTR, target,
            )

        # Use the qualified name so two tools with the same short name
        # (unusual but possible) don't collide in _PENDING.
        module = getattr(target, "__module__", "<unknown>")
        name = getattr(target, "name", None) or getattr(target, "__name__", repr(target))
        key = f"{module}.{name}"

        if key in _PENDING:
            # Re-import during tests can re-decorate. We keep the newer
            # version (last wins) and emit a debug log.
            logger.debug("@register: re-registering pending %s", key)
        _PENDING[key] = (target, meta)

        return target

    return _wrap


# ──────────────────────────────────────────────────────────────────────
# Helpers used by the discovery scanner (kept here to centralise the
# data shape; called only by ``auto_discover.py``)
# ──────────────────────────────────────────────────────────────────────


def _drain_pending() -> dict[str, tuple[Any, _RegisteredToolMeta]]:
    """Return all pending registrations and clear the buffer.

    Called once by the auto-discovery scanner after it has walked all
    tool modules. Clearing prevents accidental double-registration if
    the scanner is invoked multiple times (e.g. in test setup).
    """
    snapshot = dict(_PENDING)
    _PENDING.clear()
    return snapshot


def _peek_pending() -> dict[str, tuple[Any, _RegisteredToolMeta]]:
    """Read-only view of pending registrations — for tests / debug.

    Does NOT clear the buffer.
    """
    return dict(_PENDING)


def _reset_pending_for_tests() -> None:
    """Test-only helper: empty the pending buffer between test cases."""
    _PENDING.clear()
