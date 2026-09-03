# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/auto_discover.py
# @brief      Runtime scanner for @register'd tools — Sprint 2.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Auto-discovery of @register'd tools.

Walks one or more packages, imports every submodule (so each module's
``@register`` decorators fire and populate ``decorator._PENDING``),
then groups the pending entries by ``skill_name`` and registers each
group as a single ``Skill`` in the global registry.

Why runtime import (and not AST parsing)
----------------------------------------
- It's the standard Python pattern (Flask blueprints, FastAPI routers,
  pytest fixtures, Django apps all do it this way).
- ~30 lines of code instead of ~150 for an AST walker.
- Failures are clear: an ImportError bubbles up at startup with a
  full traceback.
- Performance cost is negligible: ~5-20 ms at boot.

When this runs
--------------
``app.skills.builtin.register_all()`` calls ``auto_discover_tools()``
exactly once, after the legacy manual skills have been registered.
This ordering matters: any skill_name that's already in the registry
(from the old pattern) wins — auto-discovery skips it. That lets us
migrate tools to the decorator one by one without ever shipping a
period where both patterns try to register the same skill.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Iterable

from app.skills.base import Skill
from app.skills.decorator import _RegisteredToolMeta, _drain_pending
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────


def auto_discover_tools(
    packages: Iterable[str] = ("app.agent.tools",),
    *,
    skip_modules: Iterable[str] = (),
) -> int:
    """Import every submodule of *packages* and register decorated tools.

    Args:
        packages: dotted package paths to scan. Defaults to the
            standard tools tree. Pass extra packages (e.g. plugin
            directories) here in the future.
        skip_modules: dotted module names to skip — useful for modules
            that have heavy import-time side-effects we don't want
            in the scanner path (e.g. legacy modules being migrated).

    Returns:
        Number of skills auto-registered (not number of tools — a
        skill can group several tools).

    Behaviour:
        - Modules already imported are NOT re-imported (importlib caches).
        - If a skill_name already exists in the registry, the
          auto-registration is skipped (legacy wins).
        - Multiple tools sharing the same skill_name are merged into
          one Skill, with the first decoration's metadata winning for
          display_name / description / icon / scopes / enabled_by_default
          / version. (We assume same skill_name means same author.)
        - Imports that fail are logged at WARNING and skipped — they
          don't block other modules from loading. This is intentional:
          one busted tool shouldn't tank app startup.
    """
    skip_set = set(skip_modules)
    imported = _import_all_submodules(packages, skip_set)
    logger.info(
        "auto_discover_tools: imported %d modules from %s",
        imported, list(packages),
    )

    pending = _drain_pending()
    if not pending:
        logger.debug("auto_discover_tools: no @register'd tools found")
        return 0

    skills = _group_pending_by_skill(pending)
    registry = get_skill_registry()
    registered_count = 0
    existing = {s.name for s in registry.list_skills()}

    for skill in skills:
        if skill.name in existing:
            logger.info(
                "auto_discover_tools: skipping %r — already registered "
                "via the legacy pattern",
                skill.name,
            )
            continue
        registry.register(skill)
        registered_count += 1
        logger.info(
            "auto_discover_tools: registered skill %r (%d tools, domains=%s)",
            skill.name, len(skill.tools), skill.domains,
        )

    return registered_count


# ──────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────


def _import_all_submodules(
    packages: Iterable[str],
    skip: set[str],
) -> int:
    """Walk each package and ``importlib.import_module`` every submodule.

    Returns the count of successful imports.
    """
    count = 0
    for pkg_name in packages:
        try:
            pkg = importlib.import_module(pkg_name)
        except ImportError as exc:
            logger.warning(
                "auto_discover_tools: cannot import package %r — %s",
                pkg_name, exc,
            )
            continue

        # Single-module package (no __path__) — just import it.
        if not hasattr(pkg, "__path__"):
            count += 1
            continue

        for mod_info in pkgutil.walk_packages(pkg.__path__, prefix=pkg_name + "."):
            mod_name = mod_info.name
            if mod_name in skip:
                logger.debug("auto_discover_tools: skipping %s (explicit skip)", mod_name)
                continue
            try:
                importlib.import_module(mod_name)
                count += 1
            except Exception as exc:  # noqa: BLE001 — we want to keep going
                # Catch BaseException-ish issues too: a tool's top-level
                # may raise anything during import. Log loudly and continue.
                logger.warning(
                    "auto_discover_tools: failed to import %s — %s: %s",
                    mod_name, type(exc).__name__, exc,
                )
    return count


def _group_pending_by_skill(
    pending: dict[str, tuple[object, _RegisteredToolMeta]],
) -> list[Skill]:
    """Group pending registrations by skill_name, returning Skill objects.

    First metadata wins for skill-level fields (display_name, icon,
    description, scopes, enabled_by_default, version). Different
    metadata for the same skill_name only triggers a debug log —
    silent override is intentional to keep boot quiet on small mismatches.
    """
    grouped: dict[str, dict] = {}
    # Insertion-ordered: tools end up in the same order they were
    # decorated, which makes the prompt/listing reproducible.
    for key, (tool_obj, meta) in pending.items():
        bucket = grouped.setdefault(meta.skill_name, {
            "meta": meta,
            "tools": [],
        })
        existing_meta: _RegisteredToolMeta = bucket["meta"]
        if (
            existing_meta.skill_display_name != meta.skill_display_name
            or existing_meta.skill_description != meta.skill_description
            or existing_meta.skill_icon != meta.skill_icon
            or set(existing_meta.domains) != set(meta.domains)
        ):
            logger.debug(
                "auto_discover_tools: skill %r has inconsistent metadata "
                "across tools — keeping the first occurrence",
                meta.skill_name,
            )
        bucket["tools"].append(tool_obj)

    skills: list[Skill] = []
    for skill_name, bucket in grouped.items():
        meta: _RegisteredToolMeta = bucket["meta"]
        skills.append(Skill(
            name=skill_name,
            display_name=meta.skill_display_name,
            description=meta.skill_description,
            icon=meta.skill_icon,
            tools=bucket["tools"],
            version=meta.skill_version,
            scopes=list(meta.scopes),
            enabled_by_default=meta.enabled_by_default,
            domains=list(meta.domains),
        ))
    return skills
