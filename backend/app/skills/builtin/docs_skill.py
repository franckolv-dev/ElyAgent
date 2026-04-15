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
from app.skills.base import Skill
from app.skills.registry import get_skill_registry
from app.agent.tools.docs_tool import (
    docs_create_document,
    docs_read_document,
    docs_append_text,
    docs_replace_text,
    docs_insert_table,
    docs_batch_update,
    docs_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_docs",
    display_name="Google Docs",
    description=(
        "Créer, lire et modifier des documents Google Docs. "
        "Styles, titres, listes, images, sauts de page — accès complet via "
        "docs_batch_update et docs_raw_api_call."
    ),
    icon="📝",
    scopes=["google_oauth"],
    tools=[
        docs_create_document,
        docs_read_document,
        docs_append_text,
        docs_replace_text,
        docs_insert_table,
        docs_batch_update,
        docs_raw_api_call,
    ],
))
