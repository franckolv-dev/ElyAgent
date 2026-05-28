# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/github_skill.py
# @brief      GitHub skill — repo stats, traffic, notifications.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.1.0
# =============================================================================
"""Register the GitHub tools as a Skill.

Created 2026-05-17 alongside the github_tool.py tools, primarily to
unblock Franck's v1.2 screencast scenario (« combien de clones du repo
ElyAgent aujourd'hui ? + log quotidien dans un XLSX »).

All three tools are read-only — no HITL required, no LOCKED_HITL entry.
"""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.github_tool import (
    github_repo_stats,
    github_traffic_stats,
    github_notifications,
)

get_skill_registry().register(Skill(
    name="github",
    display_name="GitHub",
    description=(
        "Statistiques de dépôt (étoiles, forks, issues), trafic 14 jours "
        "(clones + visiteurs), et notifications du compte. Lecture seule. "
        "Configure GITHUB_TOKEN dans le `.env` (scopes : public_repo + "
        "notifications)."
    ),
    icon="🐙",
    scopes=["github_token"],
    domains=[Domain.RESEARCH],
    tools=[github_repo_stats, github_traffic_stats, github_notifications],
    enabled_by_default=True,
))
