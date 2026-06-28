# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/calendar_skill.py
# @brief      Calendar Skill module
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from app.skills.base import Skill, Domain
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
    domains=[Domain.WORKSPACE],
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
