# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/calendar_tool.py
# @brief      Google Calendar tools for ELY agent.
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
"""Google Calendar tools for ELY agent."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.google_raw_api import execute_raw_call

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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create an event in Google Calendar.

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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Delete a Google Calendar event.

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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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


# ──────────────────────────────────────────────────────────────────────────────
# Advanced Calendar tools
# ──────────────────────────────────────────────────────────────────────────────


@tool
async def calendar_quick_add(
    text: str,
    calendar_id: str = "primary",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a calendar event from a free-form natural-language string.

    Uses Google Calendar's `events.quickAdd` — the same parser as the
    "Quick add" box in the Google Calendar UI. Handles phrases like
    'Dentist appointment tomorrow at 3pm' or 'Lunch with Alice Friday 12h'.

    Args:
        text: Natural language description of the event.
        calendar_id: Calendar ID (default 'primary').
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    try:
        logger.info("calendar_quick_add: '%s' on calendar=%s", text, calendar_id)
        created = service.events().quickAdd(
            calendarId=calendar_id, text=text
        ).execute()
        start = created.get("start", {})
        start_str = start.get("dateTime", start.get("date", "?"))
        return (
            f"✓ Événement créé : '{created.get('summary', 'Sans titre')}'\n"
            f"  Date : {start_str}\n"
            f"  Lien : {created.get('htmlLink', 'N/A')}\n"
            f"  ID : {created.get('id')}"
        )
    except Exception as e:
        logger.error("calendar_quick_add failed: %s", e)
        return f"Erreur calendar_quick_add : {e}"


@tool
async def calendar_create_meet_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    attendees: str = "",
    description: str = "",
    location: str = "",
    recurrence: str = "",
    reminders_minutes: str = "",
    calendar_id: str = "primary",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a Google Calendar event WITH a Google Meet video conference link.

    Also supports attendees, recurrence, and custom reminders in a single
    call — much richer than `calendar_create_event`.

    Args:
        title: Event title.
        start_datetime: ISO 8601 (e.g. '2025-06-15T14:00:00+02:00').
        end_datetime: ISO 8601.
        attendees: Comma-separated list of email addresses (empty = none).
        description: Optional description.
        location: Optional physical location.
        recurrence: Optional RFC-5545 RRULE (e.g. 'RRULE:FREQ=WEEKLY;BYDAY=MO'
            for every Monday; 'RRULE:FREQ=DAILY;COUNT=10' for 10 daily events).
        reminders_minutes: Comma-separated minutes for popup reminders
            (e.g. '10,60' = 10 min and 1 h before). Empty = default reminders.
        calendar_id: Calendar ID (default 'primary').
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    event: dict = {
        "summary": title,
        "start": {"dateTime": start_datetime},
        "end": {"dateTime": end_datetime},
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if description:
        event["description"] = description
    if location:
        event["location"] = location
    if attendees:
        event["attendees"] = [
            {"email": e.strip()} for e in attendees.split(",") if e.strip()
        ]
    if recurrence:
        rule = recurrence if recurrence.upper().startswith("RRULE:") else f"RRULE:{recurrence}"
        event["recurrence"] = [rule]
    if reminders_minutes:
        try:
            overrides = [
                {"method": "popup", "minutes": int(m.strip())}
                for m in reminders_minutes.split(",")
                if m.strip()
            ]
            if overrides:
                event["reminders"] = {"useDefault": False, "overrides": overrides}
        except ValueError:
            return "Erreur : reminders_minutes doit être une liste d'entiers séparés par des virgules (ex. '10,60')."

    try:
        logger.info(
            "calendar_create_meet_event: '%s' %s → %s attendees=%d",
            title, start_datetime, end_datetime,
            len(event.get("attendees", [])),
        )
        created = service.events().insert(
            calendarId=calendar_id,
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all" if attendees else "none",
        ).execute()
        meet_link = "—"
        entry_points = created.get("conferenceData", {}).get("entryPoints", [])
        if entry_points:
            meet_link = entry_points[0].get("uri", "—")
        return (
            f"✓ Événement Meet créé : '{created.get('summary')}'\n"
            f"  Date : {start_datetime} → {end_datetime}\n"
            f"  Participants : {len(event.get('attendees', []))}\n"
            f"  Meet : {meet_link}\n"
            f"  Lien Calendar : {created.get('htmlLink', 'N/A')}\n"
            f"  ID : {created.get('id')}"
        )
    except Exception as e:
        logger.error("calendar_create_meet_event failed: %s", e)
        return f"Erreur création événement Meet : {e}"


@tool
async def calendar_raw_api_call(
    method_path: str,
    params_json: str = "{}",
    body_json: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Call ANY method of the Google Calendar API (v3) directly.

    Escape hatch for advanced Calendar operations: events.move (between
    calendars), events.import, ACL management, calendar colors, settings,
    calendars.insert/delete, etc.

    Args:
        method_path: Dot-separated Calendar API method, e.g.
            'events.move', 'events.list', 'events.instances', 'acl.list',
            'acl.insert', 'calendars.insert', 'calendars.delete',
            'colors.get', 'settings.list'.
        params_json: JSON object of kwargs.
            Example: '{"calendarId": "primary", "eventId": "abc",
                        "destination": "other-cal@group.calendar.google.com"}'
        body_json: Optional JSON body for POST/PATCH methods.
    """
    service = await _get_calendar_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    return execute_raw_call(service, method_path, params_json, body_json, "calendar")
