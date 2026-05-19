# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/tool_policy_service.py
# @brief      Tool policy service — declarative per-user allow/deny/require_hitl
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Tool policy service.

Evaluates per-user policies before the legacy HITL check in tool_node, and
exposes import/export helpers so policies can be maintained as YAML files
under config/tool_policies/. The first read for a user warms an in-memory
cache; mutations invalidate the cache for that user.

YAML format (one per user, OR a "default" file used for fresh users):

    # config/tool_policies/<user_id>.yaml
    version: 1
    rules:
      gmail_send_email: allow            # auto-send without HITL
      drive_delete_file: require_hitl    # already default — but explicit
      ssh_execute: deny                  # never run SSH for this user
      browser_click:
        mode: require_hitl
        reason: "we don't trust autonomous clicks yet"

The string-only short form and the dict long form are both accepted on import.
"""
from __future__ import annotations

import logging
from typing import Literal

import yaml
from sqlalchemy import select, delete

from app.database import async_session
from app.models.tool_policy import ToolPolicy

logger = logging.getLogger(__name__)

PolicyMode = Literal["allow", "deny", "require_hitl"]
_VALID_MODES: frozenset[str] = frozenset({"allow", "deny", "require_hitl"})


class ToolPolicyService:
    """Async service backed by SQLite + a per-user in-memory cache.

    The cache is a `dict[user_id, dict[tool_name, mode]]`. It is populated
    lazily on first `evaluate()` for a user, and invalidated on every
    mutation (`set_policy`, `delete_policy`, `import_from_yaml`).
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------ #
    # Cache management                                                    #
    # ------------------------------------------------------------------ #

    async def _load_user_policies(self, user_id: str) -> dict[str, str]:
        async with async_session() as db:
            result = await db.execute(
                select(ToolPolicy).where(ToolPolicy.user_id == user_id)
            )
            rows = result.scalars().all()
        policies = {row.tool_name: row.mode for row in rows}
        self._cache[user_id] = policies
        return policies

    def invalidate(self, user_id: str) -> None:
        self._cache.pop(user_id, None)

    # ------------------------------------------------------------------ #
    # Hot path — called on every tool call                                #
    # ------------------------------------------------------------------ #

    async def evaluate(self, user_id: str, tool_name: str) -> PolicyMode | None:
        """Return the policy mode for (user, tool) or None if no rule applies."""
        if not user_id or not tool_name:
            return None
        policies = self._cache.get(user_id)
        if policies is None:
            policies = await self._load_user_policies(user_id)
        mode = policies.get(tool_name)
        if mode in _VALID_MODES:
            return mode  # type: ignore[return-value]
        return None

    # ------------------------------------------------------------------ #
    # CRUD                                                                #
    # ------------------------------------------------------------------ #

    async def list_policies(self, user_id: str) -> list[dict]:
        async with async_session() as db:
            result = await db.execute(
                select(ToolPolicy).where(ToolPolicy.user_id == user_id)
            )
            rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "tool_name": r.tool_name,
                "mode": r.mode,
                "reason": r.reason,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    async def set_policy(
        self,
        user_id: str,
        tool_name: str,
        mode: PolicyMode,
        reason: str | None = None,
        source: str = "ui",
    ) -> ToolPolicy:
        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}' (allowed: {sorted(_VALID_MODES)})")
        async with async_session() as db:
            result = await db.execute(
                select(ToolPolicy).where(
                    ToolPolicy.user_id == user_id,
                    ToolPolicy.tool_name == tool_name,
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.mode = mode
                row.reason = reason
                row.source = source
            else:
                row = ToolPolicy(
                    user_id=user_id,
                    tool_name=tool_name,
                    mode=mode,
                    reason=reason,
                    source=source,
                )
                db.add(row)
            await db.commit()
            await db.refresh(row)
        self.invalidate(user_id)
        return row

    async def delete_policy(self, user_id: str, tool_name: str) -> bool:
        async with async_session() as db:
            result = await db.execute(
                delete(ToolPolicy).where(
                    ToolPolicy.user_id == user_id,
                    ToolPolicy.tool_name == tool_name,
                )
            )
            await db.commit()
        self.invalidate(user_id)
        return result.rowcount > 0

    # ------------------------------------------------------------------ #
    # YAML import / export                                                #
    # ------------------------------------------------------------------ #

    async def import_from_yaml(
        self, user_id: str, yaml_text: str, replace: bool = False
    ) -> dict:
        """Import policies from a YAML string.

        - replace=False (default): merge — upsert each rule, keep the rest.
        - replace=True            : delete all existing policies for the user
                                    first, then insert the new ones.
        Returns a summary dict with counts of imported / replaced / errors.
        """
        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML: {exc}") from exc

        rules_raw = data.get("rules", {}) if isinstance(data, dict) else {}
        if not isinstance(rules_raw, dict):
            raise ValueError("YAML 'rules' must be a mapping of tool_name → mode")

        if replace:
            async with async_session() as db:
                await db.execute(
                    delete(ToolPolicy).where(ToolPolicy.user_id == user_id)
                )
                await db.commit()
            self.invalidate(user_id)

        imported = 0
        errors: list[str] = []
        for tool_name, raw in rules_raw.items():
            try:
                if isinstance(raw, str):
                    mode, reason = raw, None
                elif isinstance(raw, dict):
                    mode = raw.get("mode")
                    reason = raw.get("reason")
                else:
                    raise ValueError(f"unexpected value type {type(raw).__name__}")
                if mode not in _VALID_MODES:
                    raise ValueError(
                        f"invalid mode '{mode}' (allowed: {sorted(_VALID_MODES)})"
                    )
                await self.set_policy(
                    user_id=user_id,
                    tool_name=str(tool_name),
                    mode=mode,
                    reason=reason,
                    source="yaml",
                )
                imported += 1
            except Exception as exc:
                errors.append(f"{tool_name}: {exc}")

        return {
            "imported": imported,
            "replaced": replace,
            "errors": errors,
            "total_rules_in_yaml": len(rules_raw),
        }

    async def export_to_yaml(self, user_id: str) -> str:
        """Export all policies for a user as a YAML string."""
        policies = await self.list_policies(user_id)
        rules: dict[str, dict | str] = {}
        for p in policies:
            if p["reason"]:
                rules[p["tool_name"]] = {"mode": p["mode"], "reason": p["reason"]}
            else:
                rules[p["tool_name"]] = p["mode"]
        doc = {"version": 1, "rules": rules}
        return yaml.safe_dump(doc, sort_keys=True, allow_unicode=True)


_service = ToolPolicyService()


def get_tool_policy_service() -> ToolPolicyService:
    return _service
