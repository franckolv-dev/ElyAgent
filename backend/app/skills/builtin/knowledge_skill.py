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
from app.agent.tools.knowledge_tool import knowledge_search, knowledge_list

get_skill_registry().register(Skill(
    name="knowledge",
    display_name="Base de connaissances",
    description="Rechercher et consulter les documents personnels indexes",
    icon="📚",
    scopes=[],
    tools=[knowledge_search, knowledge_list],
    enabled_by_default=True,
))
