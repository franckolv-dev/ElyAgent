"""Google Calendar tools for ELY agent."""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

logger = logging.getLogger(__name__)


def _get_calendar_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = get_user_credentials(user_google_credentials_json)
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
    service = _get_calendar_service(user_google_credentials_json)
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
    service = _get_calendar_service(user_google_credentials_json)
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
