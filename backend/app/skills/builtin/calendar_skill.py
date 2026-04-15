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
from app.agent.tools.calendar_tool import (
    calendar_list_events,
    calendar_create_event,
    calendar_get_event,
    calendar_update_event,
    calendar_delete_event,
    calendar_check_availability,
    calendar_list_calendars,
    calendar_quick_add,
    calendar_create_meet_event,
    calendar_raw_api_call,
)

get_skill_registry().register(Skill(
    name="google_calendar",
    display_name="Google Calendar",
    description=(
        "Consulter, créer, modifier et supprimer des événements Google Calendar. "
        "Créer en langage naturel, visio Meet, récurrences, rappels — plus "
        "accès complet via calendar_raw_api_call."
    ),
    icon="📅",
    scopes=["google_oauth"],
    tools=[
        calendar_list_events,
        calendar_create_event,
        calendar_get_event,
        calendar_update_event,
        calendar_delete_event,
        calendar_check_availability,
        calendar_list_calendars,
        calendar_quick_add,
        calendar_create_meet_event,
        calendar_raw_api_call,
    ],
))
