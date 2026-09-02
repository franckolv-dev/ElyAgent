# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/system_diag_skill.py
# @brief      🔍 System diagnostic skill — ELY introspects herself
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""🔍 System diagnostic skill — read-only self-introspection.

Lets ELY answer questions like :
  - "Pourquoi mon mail planifié de ce matin n'est pas arrivé ?"
  - "Tous les canaux fonctionnent-ils ?"
  - "Quel modèle utilises-tu pour les missions ?"
  - "Comment tu te portes ?"

All tools are read-only. Self-modification (restart bot, change tier,
edit DB) is reserved for a future Phase B with HITL gating.
"""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.system_diag_tool import (
    system_get_logs,
    system_list_scheduled_tasks,
    system_list_missions,
    system_check_channels,
    system_check_llm_providers,
    system_get_health,
)

get_skill_registry().register(Skill(
    name="system_diag",
    display_name="Diagnostic système",
    description=(
        # 02/09/2026 : le retrait de « Discord, Slack, WhatsApp), » avait
        # emporté la parenthèse fermante. Cette phrase part au modèle dans le
        # catalogue de sélection d'outil : cassée, elle se lit mal.
        "Permet à ELY de lire ses propres logs, lister ses tâches planifiées "
        "et missions, vérifier l'état des canaux conversationnels (Telegram), "
        "inspecter la configuration LLM et "
        "produire un bilan de santé du backend. Lecture seule — aucune "
        "modification, aucune commande shell, aucun secret divulgué (les "
        "tokens et mots de passe sont automatiquement masqués dans les logs)."
    ),
    icon="🔍",
    scopes=[],
    enabled_by_default=True,
    domains=[Domain.DIAG],
    tools=[
        system_get_logs,
        system_list_scheduled_tasks,
        system_list_missions,
        system_check_channels,
        system_check_llm_providers,
        system_get_health,
    ],
))
