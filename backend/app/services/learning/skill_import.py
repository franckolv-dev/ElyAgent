# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_import.py
# @brief      J5-B — import SKILL.md playbooks from a URL into the skill library
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Import external SKILL.md playbooks into the learned-skills library (J5-B).

The community skill standard (agentskills.io, Hermes…) distributes skills as
**SKILL.md** files — YAML frontmatter + a Markdown procedure body. Ely's
learned-skills system already speaks exactly this format
(``skill_creator.parse_playbook_response``), so importing is just a new
*source* on top of the existing J1 machinery.

A fetched playbook is stored as a ``LearnedSkill`` with
``source=imported_marketplace`` and ``status=CANDIDATE`` — it lands in the
existing admin candidate-review queue and is **NOT auto-activated**, because
external content is untrusted (a malicious playbook could carry a
prompt-injection). The admin promotes the worthwhile ones; J1's injection then
surfaces them at run time. Best-effort, never raises.

Note : this is the **markdown-playbook** path (procedural knowledge), distinct
from ``services/marketplace.py`` which installs executable Python *code* skills.
"""
from __future__ import annotations

import ipaddress
import json
import logging
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.database import async_session
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.services.learning.skill_creator import parse_playbook_response

logger = logging.getLogger(__name__)

_MAX_BYTES = 200_000   # a playbook is a few KB; cap defensively
_TIMEOUT_S = 10.0


def _is_blocked_host(url: str) -> bool:
    """Block obvious loopback / link-local / private targets (light SSRF guard;
    the endpoint is admin-only, so this is defence-in-depth, not the main gate)."""
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "ip6-localhost", ""}:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False  # a hostname (not a literal IP) — allowed


async def import_skill_from_url(url: str, user_id: str) -> dict:
    """Fetch a SKILL.md from ``url`` and store it as a CANDIDATE learned skill.

    Returns ``{"status": "imported"|"duplicate"|"error", ...}``. Never raises.
    Idempotent on (user_id, name) — re-importing an existing skill is a no-op.
    """
    url = (url or "").strip()
    if not url:
        return {"status": "error", "error": "URL vide."}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"status": "error", "error": "URL invalide (http(s) requis)."}
    if _is_blocked_host(url):
        return {"status": "error", "error": "Hôte non autorisé (adresse locale/privée)."}

    # ── Fetch ──
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(
                url, headers={"Accept": "text/plain, text/markdown, */*"}
            )
        if resp.status_code != 200:
            return {"status": "error", "error": f"Téléchargement échoué (HTTP {resp.status_code})."}
        raw = resp.text
    except Exception as exc:
        logger.warning("skill_import fetch failed for %s: %s", url, exc)
        return {"status": "error", "error": f"Téléchargement impossible : {exc}"}

    if len(raw.encode("utf-8", "ignore")) > _MAX_BYTES:
        return {"status": "error", "error": "Fichier trop volumineux (> 200 Ko)."}

    # ── Parse (same format as auto-generated playbooks) ──
    parsed = parse_playbook_response(raw)
    if parsed is None:
        return {
            "status": "error",
            "error": "Format SKILL.md invalide (frontmatter avec name + description requis).",
        }

    # ── Store as CANDIDATE — the admin reviews before it goes live ──
    try:
        async with async_session() as db:
            existing = (await db.execute(
                select(LearnedSkill).where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.name == parsed["name"],
                )
            )).scalar_one_or_none()
            if existing is not None:
                return {"status": "duplicate", "name": parsed["name"], "skill_id": existing.id}

            skill = LearnedSkill(
                user_id=user_id,
                name=parsed["name"],
                description=parsed["description"],
                content=parsed["body"],
                frontmatter_json=json.dumps(parsed["frontmatter"], ensure_ascii=False),
                status=SkillStatus.CANDIDATE,
                source=SkillSource.IMPORTED_MARKETPLACE,
                content_format=SkillContentFormat.MARKDOWN_PLAYBOOK,
                from_failure_case_ids=json.dumps([]),
                rationale=f"Importé depuis {url[:400]} — à valider avant activation.",
            )
            db.add(skill)
            await db.commit()
            await db.refresh(skill)
            logger.info(
                "skill_import: candidate %s (%s) created from %s",
                skill.name, skill.id, url,
            )
            return {"status": "imported", "name": skill.name, "skill_id": skill.id}
    except Exception as exc:
        logger.warning("skill_import store failed: %s", exc)
        return {"status": "error", "error": f"Enregistrement impossible : {exc}"}
