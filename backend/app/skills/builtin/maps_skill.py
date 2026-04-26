# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/maps_skill.py
# @brief      Maps / Itinéraires skill — geocoding, directions and POI search via OpenStreetMap.
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
"""Maps / Itinéraires skill — geocoding, directions and POI search via OpenStreetMap."""
from app.skills.base import Skill
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
    tools=[
        maps_geocode,
        maps_directions,
        maps_nearby,
        maps_reverse_geocode,
    ],
))
