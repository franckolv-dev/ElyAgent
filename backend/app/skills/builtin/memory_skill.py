# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/memory_skill.py
# @brief      Memory Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.memory_tool import save_user_preference, save_constraint
from app.agent.tools.memgpt_tool import (
    memory_archive, memory_search, memory_recent,
)
# Sprint 1 — Memory recall (cross-conversation FTS5 + Ministral 3B summariser).
# Distinct capability from memory_archive/search above (which operate on the
# structured Qdrant fact store): this one searches the literal messages of
# every past conversation the user had.
from app.agent.tools.session_search_tool import search_past_conversations_tool

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
# Lets the agent answer "tu te souviens de…", "on en était où…",
# "what did we say about…" by searching the literal messages of every
# past conversation (FTS5 index) and summarising the top matches via a
# local LLM (Ministral 3B in the default tier-A setup). Cost: ~0€ per
# call, ~5-10s latency for 3 conversation summaries in parallel.
get_skill_registry().register(Skill(
    name="memory_recall",
    display_name="Mémoire transversale entre conversations",
    description=(
        "Recherche dans tout l'historique des conversations passées du user, "
        "groupe par session, charge le contexte autour des matchs et résume "
        "chaque conversation pertinente via un LLM local. Permet à l'agent de "
        "se souvenir de discussions précédentes sans que le user ait à les "
        "réintroduire en contexte."
    ),
    icon="🧭",
    scopes=[],
    domains=[Domain.MEMORY],
    tools=[search_past_conversations_tool],
    enabled_by_default=True,
))
