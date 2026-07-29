# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_context.py
# @brief      Contexte de tour accessible aux outils — l'identifiant de la
#             conversation courante.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""L'identifiant de la conversation courante, vu depuis un outil.

Un outil reçoit ses arguments du modèle et n'a donc aucun moyen de savoir dans
quelle conversation il s'exécute. `tool_node` pose la valeur au début du tour ;
les outils qui en ont besoin la lisent ici.

Consommateurs actuels :
  - ``delegate_tool`` — propage la conversation aux sous-tâches ;
  - ``find_tool_skill`` — consigne les découvertes et les manques d'outil sur
    la bonne conversation.

⚠️ Cette variable s'appelait ``ORCHESTRATE_CONVERSATION_ID`` et vivait dans
``orchestrate_tool``, démantelé le 29/07 (ménage lot 5). Le nom mentait depuis
longtemps : plus aucun de ses lecteurs n'avait de rapport avec `orchestrate`.
Un module neutre évite en prime le cycle d'import qu'aurait créé son
hébergement dans ``tool_node``, qui la POSE.
"""
from __future__ import annotations

from contextvars import ContextVar

CURRENT_CONVERSATION_ID: ContextVar[str] = ContextVar(
    "current_conversation_id", default=""
)
