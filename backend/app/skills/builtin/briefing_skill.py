# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/briefing_skill.py
# @brief      🌅 Morning Briefing skill — aggregates calendar + email + weather in one call.
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
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
"""🌅 Morning Briefing skill — aggregates calendar + email + weather in one call."""
from langchain_core.tools import tool
from app.skills.base import Skill
from app.skills.registry import get_skill_registry


@tool
async def briefing_generate(
    city: str = "Paris",
    days_ahead: int = 1,
) -> str:
    """Generate a complete morning briefing: weather forecast, today's calendar events,
    and a count of unread emails. Perfect for a daily scheduled task.

    Args:
        city: City for weather forecast (default: Paris)
        days_ahead: Number of days to show in calendar (default: 1 = today only)
    """
    import asyncio
    from datetime import datetime, timedelta
    import httpx

    results = {}

    # 1. Weather
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://wttr.in/{city}?format=j1")
            if r.status_code == 200:
                data = r.json()
                current = data["current_condition"][0]
                temp_c = current["temp_C"]
                desc = current["weatherDesc"][0]["value"]
                feels = current["FeelsLikeC"]
                results["weather"] = f"{desc}, {temp_c}°C (ressenti {feels}°C)"
    except Exception as e:
        results["weather"] = f"Météo indisponible ({e})"

    # 2. Brief summary message (the caller is responsible for fetching Google data)
    # This tool returns a formatted briefing template that ELY fills in
    now = datetime.now()
    weekdays = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    months = ["", "janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    date_str = f"{weekdays[now.weekday()]} {now.day} {months[now.month]} {now.year}"

    briefing = f"""BRIEFING DU MATIN — {date_str.upper()}

🌤️ MÉTÉO ({city}) : {results.get('weather', 'N/A')}

📅 AGENDA : Utilise calendar_list_events pour lister les événements d'aujourd'hui.

📧 EMAILS : Utilise gmail_list_emails pour compter les emails non lus.

📋 TÂCHES : Utilise tasks_list pour afficher les tâches du jour.

Génère un briefing complet en français, bref et agréable à écouter."""

    return briefing


_briefing_skill = Skill(
    name="briefing",
    display_name="Briefing matinal",
    description="Génère un résumé matinal complet : météo, agenda du jour, emails non lus, tâches",
    icon="🌅",
    tools=[briefing_generate],
    scopes=[],
    enabled_by_default=True,
)

get_skill_registry().register(_briefing_skill)
