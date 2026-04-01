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
"""Google Calendar tools for ELY agent."""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

logger = logging.getLogger(__name__)


async def _get_calendar_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)


@tool
async def calendar_list_events(
    max_results: int = 10,
    time_min: str = "",
    time_max: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List upcoming events from Google Calendar.

    Args:
        max_results: Number of events to return (default 10)
        time_min: Start time filter in ISO 8601 format (e.g. '2025-01-01T00:00:00Z'), defaults to now
        time_max: End time filter in ISO 8601 format
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    try:
        from datetime import datetime, timezone
        params = {
            "calendarId": "primary",
            "maxResults": min(max_results, 50),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min
        else:
            params["timeMin"] = datetime.now(timezone.utc).isoformat()
        if time_max:
            params["timeMax"] = time_max

        result = service.events().list(**params).execute()
        events = result.get("items", [])

        if not events:
            return "Aucun événement trouvé."

        lines = []
        for e in events:
            start = e.get("start", {})
            start_str = start.get("dateTime", start.get("date", "?"))
            lines.append(
                f"• {e.get('summary', 'Sans titre')} — {start_str}\n"
                f"  Lieu: {e.get('location', 'Non spécifié')}\n"
                f"  ID: {e.get('id', '')}"
            )

        return f"{len(events)} événement(s):\n\n" + "\n\n".join(lines)
    except Exception as e:
        return f"Erreur Calendar: {e}"


@tool
async def calendar_create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create an event in Google Calendar. ALWAYS confirm with user before creating.

    Args:
        title: Event title
        start_datetime: Start in ISO 8601 format (e.g. '2025-06-15T14:00:00+02:00')
        end_datetime: End in ISO 8601 format
        description: Optional event description
        location: Optional location
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        event = {
            "summary": title,
            "start": {"dateTime": start_datetime},
            "end": {"dateTime": end_datetime},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location

        logger.info("Creating calendar event: %s at %s → %s", title, start_datetime, end_datetime)
        created = service.events().insert(calendarId="primary", body=event).execute()
        logger.info("Calendar event created: ID=%s, link=%s", created.get("id"), created.get("htmlLink"))
        return (
            f"Événement créé avec succès : '{created.get('summary')}'\n"
            f"Date : {start_datetime}\n"
            f"Lien : {created.get('htmlLink', 'N/A')}\n"
            f"ID : {created.get('id')}"
        )
    except Exception as e:
        logger.error("Failed to create calendar event: %s", e)
        return f"Erreur création événement: {e}"


@tool
async def calendar_get_event(
    event_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Get full details of a specific Google Calendar event.

    Args:
        event_id: The event ID to retrieve
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        start = event.get("start", {})
        start_str = start.get("dateTime", start.get("date", "?"))
        end = event.get("end", {})
        end_str = end.get("dateTime", end.get("date", "?"))

        attendees = event.get("attendees", [])
        attendees_str = ", ".join(
            a.get("email", "?") for a in attendees
        ) if attendees else "Aucun"

        return (
            f"Titre : {event.get('summary', 'Sans titre')}\n"
            f"Début : {start_str}\n"
            f"Fin : {end_str}\n"
            f"Description : {event.get('description', 'Aucune')}\n"
            f"Lieu : {event.get('location', 'Non spécifié')}\n"
            f"Participants : {attendees_str}\n"
            f"Lien : {event.get('htmlLink', 'N/A')}\n"
            f"ID : {event.get('id')}"
        )
    except Exception as e:
        logger.error("Failed to get calendar event: %s", e)
        return f"Erreur récupération événement: {e}"


@tool
async def calendar_update_event(
    event_id: str,
    title: str = "",
    start_datetime: str = "",
    end_datetime: str = "",
    description: str = "",
    location: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Update an existing Google Calendar event. Only provided fields are modified.

    Args:
        event_id: The event ID to update
        title: New event title (leave empty to keep current)
        start_datetime: New start in ISO 8601 format (leave empty to keep current)
        end_datetime: New end in ISO 8601 format (leave empty to keep current)
        description: New description (leave empty to keep current)
        location: New location (leave empty to keep current)
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    try:
        body: dict = {}
        if title:
            body["summary"] = title
        if start_datetime:
            body["start"] = {"dateTime": start_datetime}
        if end_datetime:
            body["end"] = {"dateTime": end_datetime}
        if description:
            body["description"] = description
        if location:
            body["location"] = location

        if not body:
            return "Aucun champ à mettre à jour."

        logger.info("Updating calendar event %s with fields: %s", event_id, list(body.keys()))
        updated = service.events().patch(
            calendarId="primary", eventId=event_id, body=body
        ).execute()
        logger.info("Calendar event updated: ID=%s", updated.get("id"))

        return (
            f"Événement mis à jour : '{updated.get('summary')}'\n"
            f"Lien : {updated.get('htmlLink', 'N/A')}\n"
            f"ID : {updated.get('id')}"
        )
    except Exception as e:
        logger.error("Failed to update calendar event: %s", e)
        return f"Erreur mise à jour événement: {e}"


@tool
async def calendar_delete_event(
    event_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Supprime un événement. ALWAYS ask user confirmation.

    Args:
        event_id: The event ID to delete
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    try:
        logger.info("Deleting calendar event: %s", event_id)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info("Calendar event deleted: ID=%s", event_id)
        return f"Événement supprimé avec succès (ID : {event_id})."
    except Exception as e:
        logger.error("Failed to delete calendar event: %s", e)
        return f"Erreur suppression événement: {e}"


@tool
async def calendar_check_availability(
    time_min: str,
    time_max: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Check availability (free/busy) on Google Calendar for a given time range.

    Args:
        time_min: Start of the range in ISO 8601 format (e.g. '2024-01-15T09:00:00Z')
        time_max: End of the range in ISO 8601 format (e.g. '2024-01-15T18:00:00Z')
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    try:
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_slots = result.get("calendars", {}).get("primary", {}).get("busy", [])

        if not busy_slots:
            return f"Vous êtes libre entre {time_min} et {time_max}."

        lines = []
        for slot in busy_slots:
            lines.append(f"• Occupé : {slot.get('start')} → {slot.get('end')}")

        return (
            f"{len(busy_slots)} créneau(x) occupé(s) entre {time_min} et {time_max} :\n\n"
            + "\n".join(lines)
        )
    except Exception as e:
        logger.error("Failed to check availability: %s", e)
        return f"Erreur vérification disponibilité: {e}"


@tool
async def calendar_list_calendars(
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List all calendars accessible by the user.

    Returns id, name, primary flag and timezone for each calendar.
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte Google dans les paramètres."

    try:
        result = service.calendarList().list().execute()
        calendars = result.get("items", [])

        if not calendars:
            return "Aucun calendrier trouvé."

        lines = []
        for cal in calendars:
            primary_flag = " (principal)" if cal.get("primary") else ""
            lines.append(
                f"• {cal.get('summary', 'Sans nom')}{primary_flag}\n"
                f"  ID : {cal.get('id')}\n"
                f"  Fuseau : {cal.get('timeZone', 'Non spécifié')}"
            )

        return f"{len(calendars)} calendrier(s) :\n\n" + "\n\n".join(lines)
    except Exception as e:
        logger.error("Failed to list calendars: %s", e)
        return f"Erreur liste calendriers: {e}"
