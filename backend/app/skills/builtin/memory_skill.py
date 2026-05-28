# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/memory_skill.py
# @brief      Memory Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.memory_tool import save_user_preference, save_constraint
from app.agent.tools.memgpt_tool import (
    memory_archive, memory_search, memory_recent,
)

get_skill_registry().register(Skill(
    name="memory_preferences",
    display_name="Préférences & Contraintes",
    description="Sauvegarder les préférences de communication et les contraintes permanentes de l'utilisateur",
    icon="🧠",
    scopes=[],
    domains=[Domain.UNIVERSAL],
    tools=[save_user_preference, save_constraint],
    enabled_by_default=True,
))

# MemGPT-style hierarchical memory — active recall by the LLM via tool calls.
# These tools are DISTINCT from the always-injected memories/constraints path :
# they are NEVER pushed into the prompt automatically, only called by the
# agent when it needs to archive a durable fact or pull one from storage.
# Keeps the system prompt lean for small local models.
get_skill_registry().register(Skill(
    name="memgpt_memory",
    display_name="Mémoire hiérarchique (MemGPT)",
    description=(
        "Archivage et rappel actif de faits durables via function calling. "
        "L'agent décide lui-même d'archiver ou de récupérer des informations "
        "dans la mémoire long-terme Qdrant, au lieu de tout injecter dans le prompt."
    ),
    icon="🗄️",
    scopes=[],
    domains=[Domain.MEMORY],
    tools=[memory_archive, memory_search, memory_recent],
    enabled_by_default=True,
))

# Sprint 1 (2026-05-15) — Cross-conversation memory recall.
# Sprint 2 (2026-05-17) — MIGRATED to the @register decorator pattern.
# The skill_name="memory_recall" is now declared on the tool itself
# (see app/agent/tools/session_search_tool.py). auto_discover_tools()
# in app/skills/builtin/__init__.py picks it up at startup. This file
# no longer needs to know about session_search_tool — proof that the
# triple-registration trap is dead for new tools.
