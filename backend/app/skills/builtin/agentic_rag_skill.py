# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits reserves.
#
# Ce logiciel est mis a disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RESUME DES CONDITIONS :
# - AUTORISE : Utilisation personnelle, educative et tests prives.
# - INTERDIT : Toute utilisation commerciale sans accord prealable.
# - INTERDIT : Redistribution de versions modifiees de ce code.
#
# Pour consulter le texte integral de la licence, veuillez vous referer au
# fichier LICENSE a la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.agentic_rag_tool import smart_knowledge_query

get_skill_registry().register(Skill(
    name="agentic_rag",
    display_name="Recherche documentaire intelligente",
    description=(
        "Recherche proactive dans les documents personnels avec detection "
        "de pertinence et reranking document-level"
    ),
    icon="🧠",
    scopes=[],
    tools=[smart_knowledge_query],
    enabled_by_default=True,
))
