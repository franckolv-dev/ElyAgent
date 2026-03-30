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
"""Maps / Itinéraires tools — geocoding, directions and place search via OpenStreetMap APIs.

All APIs used are free and require no API key:
- Nominatim (OSM) for geocoding / place search
- OSRM for routing (driving / cycling / walking)
- Overpass API for nearby places (POI)
"""
from __future__ import annotations

import httpx

from langchain_core.tools import tool

_NOMINATIM_URL = "https://nominatim.openstreetmap.org"
_OSRM_URL = "https://router.project-osrm.org"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_HEADERS = {"User-Agent": "ElyAgent/1.0 (personal assistant)"}


@tool
async def maps_geocode(address: str) -> str:
    """Find the coordinates (latitude, longitude) of an address or place name.

    Args:
        address: Address or place name (e.g. 'Tour Eiffel Paris', '12 rue de Rivoli Paris')
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            resp = await client.get(
                f"{_NOMINATIM_URL}/search",
                params={"q": address, "format": "json", "limit": 3, "accept-language": "fr"},
            )
            resp.raise_for_status()
            results = resp.json()

        if not results:
            return f"Aucun résultat trouvé pour « {address} »."

        lines = [f"Résultats pour « {address} » :"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. {r['display_name']}\n"
                f"   Coordonnées : {r['lat']}, {r['lon']}"
            )
        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur de géocodage : {exc}"


@tool
async def maps_directions(
    origin: str,
    destination: str,
    mode: str = "driving",
) -> str:
    """Get turn-by-turn directions between two places.

    Args:
        origin: Starting point (address or place name)
        destination: End point (address or place name)
        mode: Transport mode — 'driving' (default), 'cycling', or 'walking'
    """
    mode_map = {"driving": "car", "cycling": "bike", "walking": "foot", "voiture": "car",
                "vélo": "bike", "pied": "foot", "marche": "foot"}
    osrm_profile = mode_map.get(mode.lower(), "car")

    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            # Geocode origin
            r1 = await client.get(
                f"{_NOMINATIM_URL}/search",
                params={"q": origin, "format": "json", "limit": 1, "accept-language": "fr"},
            )
            places_origin = r1.json()
            if not places_origin:
                return f"Adresse de départ introuvable : « {origin} »."

            # Geocode destination
            r2 = await client.get(
                f"{_NOMINATIM_URL}/search",
                params={"q": destination, "format": "json", "limit": 1, "accept-language": "fr"},
            )
            places_dest = r2.json()
            if not places_dest:
                return f"Adresse d'arrivée introuvable : « {destination} »."

            o = places_origin[0]
            d = places_dest[0]

            # Get route from OSRM
            route_resp = await client.get(
                f"{_OSRM_URL}/route/v1/{osrm_profile}/{o['lon']},{o['lat']};{d['lon']},{d['lat']}",
                params={"overview": "false", "steps": "true"},
            )
            route_resp.raise_for_status()
            route_data = route_resp.json()

        if route_data.get("code") != "Ok":
            return f"Impossible de calculer l'itinéraire : {route_data.get('message', 'erreur inconnue')}"

        route = route_data["routes"][0]
        legs = route["legs"][0]

        # Summary
        distance_km = route["distance"] / 1000
        duration_min = route["duration"] / 60
        mode_labels = {"car": "voiture", "bike": "vélo", "foot": "à pied"}
        mode_label = mode_labels.get(osrm_profile, osrm_profile)

        lines = [
            f"Itinéraire {mode_label} de « {origin} » à « {destination} » :",
            f"Distance : {distance_km:.1f} km",
            f"Durée estimée : {int(duration_min)} min",
            "",
            "Étapes :",
        ]

        for step in legs.get("steps", []):
            maneuver = step.get("maneuver", {})
            name = step.get("name", "")
            dist = step.get("distance", 0)
            mtype = maneuver.get("type", "")
            modifier = maneuver.get("modifier", "")

            instruction = mtype.replace("-", " ")
            if modifier:
                instruction += f" {modifier}"
            if name:
                instruction += f" sur {name}"
            if dist > 0:
                instruction += f" ({dist:.0f} m)"

            lines.append(f"• {instruction.capitalize()}")

        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur lors du calcul d'itinéraire : {exc}"


@tool
async def maps_nearby(
    location: str,
    category: str,
    radius_m: int = 1000,
) -> str:
    """Find nearby places of interest (restaurants, pharmacies, ATMs, etc.).

    Args:
        location: Center location (address or place name)
        category: Category to search — e.g. 'restaurant', 'pharmacie', 'distributeur', 'hôtel',
                  'supermarché', 'café', 'hôpital', 'école', 'parking', 'station-service'
        radius_m: Search radius in meters (default 1000)
    """
    # OSM amenity mapping
    category_map: dict[str, str] = {
        "restaurant": "amenity=restaurant",
        "café": "amenity=cafe",
        "cafe": "amenity=cafe",
        "pharmacie": "amenity=pharmacy",
        "hôpital": "amenity=hospital",
        "hopital": "amenity=hospital",
        "distributeur": "amenity=atm",
        "atm": "amenity=atm",
        "parking": "amenity=parking",
        "station-service": "amenity=fuel",
        "essence": "amenity=fuel",
        "école": "amenity=school",
        "supermarché": "shop=supermarket",
        "supermarche": "shop=supermarket",
        "hôtel": "tourism=hotel",
        "hotel": "tourism=hotel",
        "banque": "amenity=bank",
        "poste": "amenity=post_office",
        "médecin": "amenity=doctors",
        "medecin": "amenity=doctors",
    }

    osm_filter = category_map.get(category.lower().replace("é", "e").replace("ô", "o"))
    if not osm_filter:
        # Try generic amenity
        osm_filter = f"amenity={category.lower()}"

    tag_key, tag_val = osm_filter.split("=", 1)

    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            # Geocode location
            geo = await client.get(
                f"{_NOMINATIM_URL}/search",
                params={"q": location, "format": "json", "limit": 1, "accept-language": "fr"},
            )
            places = geo.json()
            if not places:
                return f"Lieu introuvable : « {location} »."

            lat = float(places[0]["lat"])
            lon = float(places[0]["lon"])

            # Query Overpass for nearby POIs
            query = (
                f"[out:json][timeout:10];"
                f"("
                f"  node[\"{tag_key}\"=\"{tag_val}\"](around:{radius_m},{lat},{lon});"
                f"  way[\"{tag_key}\"=\"{tag_val}\"](around:{radius_m},{lat},{lon});"
                f");"
                f"out center 10;"
            )
            overpass = await client.post(_OVERPASS_URL, data={"data": query})
            overpass.raise_for_status()
            data = overpass.json()

        elements = data.get("elements", [])
        if not elements:
            return f"Aucun(e) {category} trouvé(e) dans un rayon de {radius_m} m autour de « {location} »."

        lines = [f"{len(elements)} {category}(s) proches de « {location} » (rayon {radius_m} m) :"]
        for el in elements[:10]:
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("brand") or "(sans nom)"
            addr_parts = [
                tags.get("addr:housenumber", ""),
                tags.get("addr:street", ""),
                tags.get("addr:city", ""),
            ]
            addr = " ".join(p for p in addr_parts if p) or ""
            phone = tags.get("phone") or tags.get("contact:phone") or ""
            opening = tags.get("opening_hours", "")

            line = f"• {name}"
            if addr:
                line += f" — {addr}"
            if phone:
                line += f" — ☎ {phone}"
            if opening:
                line += f" — 🕐 {opening}"
            lines.append(line)

        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur lors de la recherche de lieux : {exc}"


@tool
async def maps_reverse_geocode(latitude: float, longitude: float) -> str:
    """Get the address corresponding to GPS coordinates.

    Args:
        latitude: Latitude (e.g. 48.8566)
        longitude: Longitude (e.g. 2.3522)
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            resp = await client.get(
                f"{_NOMINATIM_URL}/reverse",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "format": "json",
                    "accept-language": "fr",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if "error" in data:
            return f"Aucune adresse trouvée pour ({latitude}, {longitude})."

        return (
            f"Adresse pour ({latitude}, {longitude}) :\n"
            f"{data.get('display_name', 'Adresse inconnue')}"
        )

    except Exception as exc:
        return f"Erreur de géocodage inverse : {exc}"
