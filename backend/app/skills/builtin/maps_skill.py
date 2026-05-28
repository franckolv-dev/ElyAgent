# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/maps_skill.py
# @brief      Maps / Itinéraires skill — geocoding, directions and POI search via OpenStreetMap.
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
"""Maps / Itinéraires skill — geocoding, directions and POI search via OpenStreetMap."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.maps_tool import (
    maps_geocode,
    maps_directions,
    maps_nearby,
    maps_reverse_geocode,
)

get_skill_registry().register(Skill(
    name="maps",
    display_name="Maps & Itinéraires",
    description=(
        "Géolocalisation, calcul d'itinéraires (voiture / vélo / pied) et recherche de lieux "
        "à proximité via OpenStreetMap — sans clé API."
    ),
    icon="🗺️",
    scopes=["internet"],
    domains=[Domain.RESEARCH, Domain.DATA],
    tools=[
        maps_geocode,
        maps_directions,
        maps_nearby,
        maps_reverse_geocode,
    ],
))
