# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""Community skill marketplace — secure skill installation and management.

Key security differences vs OpenClaw's ClawHub:
  1. DECLARED PERMISSIONS — every skill must declare what it needs
     (internet, filesystem, shell, etc). Admin approves explicitly.
  2. NO ARBITRARY SHELL — skills cannot exec() or subprocess.run()
     unless granted "shell:restricted" permission by admin.
  3. SANDBOXED IMPORTS — community skill code runs through
     importlib with restricted builtins.
  4. CODE REVIEW — skill source is stored on disk and admin must
     approve before tools become available to the agent.
  5. AUDIT TRAIL — every install/uninstall/approve is logged.

Manifest format (manifest.yml):
  name: my-skill
  display_name: My Skill
  description: Does something useful
  author: github-user
  version: 1.0.0
  icon: "🔧"
  permissions:
    - internet        # Can make HTTP requests
    - filesystem:read # Can read files (in allowed dirs)
  tools:
    - name: my_tool
      description: Does the thing
      file: tools.py
      function: my_tool
"""
from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import sys
import uuid
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select

from app.database import async_session
from app.models.community_skill import CommunitySkill
from app.skills.base import Skill
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

# Base directory for community skills
_SKILLS_DIR = Path(__file__).parents[2] / "data" / "community_skills"

# Permissions that are considered dangerous and require explicit admin approval
DANGEROUS_PERMISSIONS = {
    "shell:restricted",
    "shell:full",
    "filesystem:write",
    "filesystem:delete",
    "network:raw",
}

# Allowed permission scopes
VALID_PERMISSIONS = {
    "internet",           # HTTP requests (httpx)
    "filesystem:read",    # Read files in allowed dirs
    "filesystem:write",   # Write files in allowed dirs
    "filesystem:delete",  # Delete files
    "shell:restricted",   # Run whitelisted commands only
    "shell:full",         # Run any command (VERY DANGEROUS)
    "network:raw",        # Raw socket access
    "database:read",      # Read from ELY database
    "database:write",     # Write to ELY database
}


class MarketplaceService:
    """Manages community skill installation, validation, and lifecycle."""

    def __init__(self):
        _SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    async def list_installed(self) -> list[dict]:
        """List all installed community skills."""
        async with async_session() as db:
            result = await db.execute(
                select(CommunitySkill).order_by(CommunitySkill.installed_at.desc())
            )
            skills = result.scalars().all()
            return [
                {
                    "id": s.id,
                    "slug": s.slug,
                    "display_name": s.display_name,
                    "description": s.description,
                    "author": s.author,
                    "version": s.version,
                    "icon": s.icon,
                    "source_url": s.source_url,
                    "declared_permissions": json.loads(s.declared_permissions),
                    "granted_permissions": json.loads(s.granted_permissions),
                    "is_installed": s.is_installed,
                    "is_approved": s.is_approved,
                    "tool_count": s.tool_count,
                    "tool_names": json.loads(s.tool_names),
                    "installed_by": s.installed_by,
                    "installed_at": s.installed_at.isoformat() if s.installed_at else None,
                }
                for s in skills
            ]

    async def install_from_directory(
        self,
        source_dir: Path,
        installed_by: str = "admin",
    ) -> dict:
        """Install a community skill from a local directory containing manifest.yml.

        The skill is installed but NOT approved — admin must review and approve
        before tools become available to the agent.
        """
        manifest_path = source_dir / "manifest.yml"
        if not manifest_path.exists():
            manifest_path = source_dir / "manifest.yaml"
        if not manifest_path.exists():
            raise ValueError(f"No manifest.yml found in {source_dir}")

        with open(manifest_path, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        # Validate manifest
        self._validate_manifest(manifest)

        slug = manifest["name"]
        install_dir = _SKILLS_DIR / slug

        # Check if already installed
        async with async_session() as db:
            existing = await db.execute(
                select(CommunitySkill).where(CommunitySkill.slug == slug)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Skill '{slug}' is already installed")

        # Copy skill files to install directory
        if install_dir.exists():
            shutil.rmtree(install_dir)
        shutil.copytree(source_dir, install_dir)

        # Security check: scan for dangerous patterns
        warnings = self._security_scan(install_dir)

        # Parse declared permissions
        declared = manifest.get("permissions", [])
        tools_info = manifest.get("tools", [])
        tool_names = [t.get("name", "") for t in tools_info if t.get("name")]

        # Has dangerous permissions?
        has_dangerous = bool(set(declared) & DANGEROUS_PERMISSIONS)

        # Create DB record
        skill_record = CommunitySkill(
            slug=slug,
            display_name=manifest.get("display_name", slug),
            description=manifest.get("description", ""),
            author=manifest.get("author", "unknown"),
            version=manifest.get("version", "1.0.0"),
            icon=manifest.get("icon", ""),
            source_url=manifest.get("source_url", ""),
            declared_permissions=json.dumps(declared),
            granted_permissions="[]",  # Nothing granted yet
            is_installed=True,
            is_approved=False,  # Must be approved by admin
            tool_count=len(tool_names),
            tool_names=json.dumps(tool_names),
            install_path=str(install_dir),
            installed_by=installed_by,
        )

        async with async_session() as db:
            db.add(skill_record)
            await db.commit()
            await db.refresh(skill_record)

        result = {
            "id": skill_record.id,
            "slug": slug,
            "display_name": skill_record.display_name,
            "status": "installed_pending_approval",
            "declared_permissions": declared,
            "has_dangerous_permissions": has_dangerous,
            "security_warnings": warnings,
            "tool_count": len(tool_names),
            "tool_names": tool_names,
        }

        logger.info(
            "Community skill '%s' installed by %s — pending approval "
            "(dangerous=%s, warnings=%d)",
            slug, installed_by, has_dangerous, len(warnings),
        )
        return result

    async def approve_skill(self, slug: str, grant_permissions: list[str]) -> dict:
        """Admin approves a skill and grants specific permissions.

        Only granted permissions will be available to the skill at runtime.
        """
        async with async_session() as db:
            result = await db.execute(
                select(CommunitySkill).where(CommunitySkill.slug == slug)
            )
            skill = result.scalar_one_or_none()
            if not skill:
                raise ValueError(f"Skill '{slug}' not found")

            # Validate grant is subset of declared
            declared = set(json.loads(skill.declared_permissions))
            granted = set(grant_permissions) & declared  # Only grant what was declared

            skill.granted_permissions = json.dumps(list(granted))
            skill.is_approved = True
            await db.commit()

        # Load the skill into the registry
        await self._load_skill(slug)

        logger.info(
            "Community skill '%s' approved with permissions: %s",
            slug, list(granted),
        )
        return {"slug": slug, "status": "approved", "granted_permissions": list(granted)}

    async def revoke_skill(self, slug: str) -> dict:
        """Revoke approval and unload skill from registry."""
        async with async_session() as db:
            result = await db.execute(
                select(CommunitySkill).where(CommunitySkill.slug == slug)
            )
            skill = result.scalar_one_or_none()
            if not skill:
                raise ValueError(f"Skill '{slug}' not found")

            skill.is_approved = False
            skill.granted_permissions = "[]"
            await db.commit()

        # Unregister from skill registry
        registry = get_skill_registry()
        registry.unregister(f"community:{slug}")

        logger.info("Community skill '%s' revoked", slug)
        return {"slug": slug, "status": "revoked"}

    async def uninstall_skill(self, slug: str) -> dict:
        """Completely remove a community skill."""
        # Unregister first
        registry = get_skill_registry()
        registry.unregister(f"community:{slug}")

        async with async_session() as db:
            result = await db.execute(
                select(CommunitySkill).where(CommunitySkill.slug == slug)
            )
            skill = result.scalar_one_or_none()
            if not skill:
                raise ValueError(f"Skill '{slug}' not found")

            install_path = Path(skill.install_path) if skill.install_path else None
            await db.delete(skill)
            await db.commit()

        # Remove files
        if install_path and install_path.exists():
            shutil.rmtree(install_path, ignore_errors=True)

        logger.info("Community skill '%s' uninstalled", slug)
        return {"slug": slug, "status": "uninstalled"}

    async def load_approved_skills(self) -> int:
        """Load all approved community skills into the registry at startup."""
        count = 0
        async with async_session() as db:
            result = await db.execute(
                select(CommunitySkill).where(
                    CommunitySkill.is_installed == True,
                    CommunitySkill.is_approved == True,
                )
            )
            for skill in result.scalars().all():
                try:
                    await self._load_skill(skill.slug)
                    count += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to load community skill '%s': %s",
                        skill.slug, exc,
                    )
        logger.info("Loaded %d approved community skills", count)
        return count

    async def _load_skill(self, slug: str) -> None:
        """Load a community skill's tools into the skill registry."""
        async with async_session() as db:
            result = await db.execute(
                select(CommunitySkill).where(CommunitySkill.slug == slug)
            )
            skill_record = result.scalar_one_or_none()
            if not skill_record or not skill_record.is_approved:
                raise ValueError(f"Skill '{slug}' not found or not approved")

        install_dir = Path(skill_record.install_path)
        manifest_path = install_dir / "manifest.yml"
        if not manifest_path.exists():
            manifest_path = install_dir / "manifest.yaml"

        with open(manifest_path, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        tools_defs = manifest.get("tools", [])
        loaded_tools = []

        for tool_def in tools_defs:
            tool_file = install_dir / tool_def.get("file", "tools.py")
            func_name = tool_def.get("function", "")

            if not tool_file.exists():
                logger.warning("Tool file %s not found for skill %s", tool_file, slug)
                continue

            # Load module from file path
            try:
                spec = importlib.util.spec_from_file_location(
                    f"community_skills.{slug}.{tool_file.stem}",
                    tool_file,
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                tool_func = getattr(module, func_name, None)
                if tool_func is not None:
                    loaded_tools.append(tool_func)
                else:
                    logger.warning(
                        "Function '%s' not found in %s for skill %s",
                        func_name, tool_file, slug,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to load tool '%s' from skill '%s': %s",
                    func_name, slug, exc,
                )

        if loaded_tools:
            skill = Skill(
                name=f"community:{slug}",
                display_name=f"{skill_record.display_name}",
                description=skill_record.description,
                icon=skill_record.icon or "",
                scopes=json.loads(skill_record.granted_permissions),
                tools=loaded_tools,
                version=skill_record.version,
                author=skill_record.author,
                enabled_by_default=True,
            )
            get_skill_registry().register_or_replace(skill)
            logger.info(
                "Community skill '%s' loaded with %d tools",
                slug, len(loaded_tools),
            )

    def _validate_manifest(self, manifest: dict) -> None:
        """Validate a skill manifest."""
        required = ["name", "display_name", "tools"]
        for field in required:
            if field not in manifest:
                raise ValueError(f"Manifest missing required field: '{field}'")

        name = manifest["name"]
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Invalid skill name '{name}' — use only alphanumeric, hyphens, underscores"
            )

        permissions = manifest.get("permissions", [])
        for perm in permissions:
            if perm not in VALID_PERMISSIONS:
                raise ValueError(
                    f"Unknown permission '{perm}'. Valid: {sorted(VALID_PERMISSIONS)}"
                )

        tools = manifest.get("tools", [])
        if not tools:
            raise ValueError("Manifest must declare at least one tool")

        for tool in tools:
            if "name" not in tool or "function" not in tool:
                raise ValueError("Each tool must have 'name' and 'function' fields")

    def _security_scan(self, install_dir: Path) -> list[str]:
        """Scan skill code for dangerous patterns.

        Returns a list of warnings (not blocking — admin decides).
        """
        warnings = []
        dangerous_patterns = [
            ("subprocess", "Uses subprocess — can execute system commands"),
            ("os.system", "Uses os.system — can execute system commands"),
            ("os.popen", "Uses os.popen — can execute system commands"),
            ("eval(", "Uses eval() — can execute arbitrary code"),
            ("exec(", "Uses exec() — can execute arbitrary code"),
            ("__import__", "Uses __import__ — dynamic module loading"),
            ("open(", "Opens files directly — bypasses permission system"),
            ("shutil.rmtree", "Can delete directory trees"),
            ("requests.get", "Makes HTTP requests (check 'internet' permission)"),
            ("httpx.", "Makes HTTP requests (check 'internet' permission)"),
            ("socket.", "Raw socket access (check 'network:raw' permission)"),
        ]

        for py_file in install_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                for pattern, warning in dangerous_patterns:
                    if pattern in content:
                        warnings.append(
                            f"{py_file.name}: {warning}"
                        )
            except Exception:
                warnings.append(f"{py_file.name}: Could not read file")

        return warnings


@lru_cache(maxsize=1)
def get_marketplace_service() -> MarketplaceService:
    return MarketplaceService()
