# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/weather_skill.py
# @brief      Weather skill — current conditions and forecast via wttr.in
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Weather skill — current conditions and forecast via wttr.in.

No API key required.  Uses the public wttr.in JSON API which supports
French descriptions (lang=fr) and covers worldwide locations.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


@tool
async def weather_get(location: str, days: int = 1) -> str:
    """Get current weather and forecast for any location.

    Args:
        location: City or location name (e.g. 'Paris', 'Lyon France', 'New York')
        days: Number of forecast days to include (1 = today only, max 3)
    """
    import httpx

    try:
        encoded = location.strip().replace(" ", "+")
        url = f"https://wttr.in/{encoded}?format=j1&lang=fr"

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "ELY-Agent/1.0"})
            resp.raise_for_status()
            data = resp.json()

        cur = data["current_condition"][0]
        desc = cur["weatherDesc"][0]["value"]
        temp = cur["temp_C"]
        feels = cur["FeelsLikeC"]
        humidity = cur["humidity"]
        wind = cur["windspeedKmph"]
        precip = cur["precipMM"]
        visibility = cur["visibility"]

        lines = [
            f"Météo à {location} : {desc}",
            f"Température {temp}°C (ressenti {feels}°C)",
            f"Humidité {humidity}%  |  Vent {wind} km/h  |  "
            f"Précipitations {precip} mm  |  Visibilité {visibility} km",
        ]

        # Forecast days (weather[0] = today, [1] = tomorrow, …)
        forecast_days = min(int(days), 3)
        if forecast_days > 1:
            lines.append("")
            for i, day in enumerate(data["weather"][:forecast_days]):
                date = day["date"]
                max_t = day["maxtempC"]
                min_t = day["mintempC"]
                # Noon slot (index 4 = 12:00 in 3-hour increments)
                noon = day["hourly"][4] if len(day["hourly"]) > 4 else day["hourly"][-1]
                day_desc = noon["weatherDesc"][0]["value"]
                label = "Aujourd'hui" if i == 0 else f"J+{i}"
                lines.append(f"{label} ({date}) : {day_desc}, {min_t}°C → {max_t}°C")

        return "\n".join(lines)

    except httpx.HTTPStatusError as exc:
        return f"Erreur météo (HTTP {exc.response.status_code}) pour « {location} »."
    except Exception as exc:
        logger.warning("weather_get failed: %s", exc)
        return f"Impossible d'obtenir la météo pour « {location} » : {exc}"


get_skill_registry().register(Skill(
    name="weather",
    display_name="Météo",
    description="Météo actuelle et prévisions pour n'importe quelle ville (via wttr.in, sans clé API)",
    icon="🌤️",
    scopes=["internet"],
    domains=[Domain.RESEARCH],
    tools=[weather_get],
))
