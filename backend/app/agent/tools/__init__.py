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
# Tools are now managed by the SkillRegistry (app.skills).
# This shim exists for backward-compatibility only.
# New code should use: from app.skills import get_skill_registry

from app.skills.registry import get_skill_registry as _get_registry


def _all_tools():
    """Lazily fetched tool list — always reflects the current registry state."""
    return _get_registry().all_tools


# WARNING: do NOT add a module-level `all_tools = _all_tools()` here.
# register_all() has not been called yet at import time, so the registry
# is empty and the call would always return an empty list.
# Use get_skill_registry().all_tools directly instead.
