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
