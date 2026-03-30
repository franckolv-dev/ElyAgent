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
