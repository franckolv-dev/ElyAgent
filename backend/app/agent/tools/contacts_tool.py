"""Google Contacts (People API) tools for ELY agent."""
from __future__ import annotations

import asyncio
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


def _get_people_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("people", "v1", credentials=creds)


@tool
async def contacts_search(
    query: str,
    max_results: int = 10,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search Google Contacts by name, email or phone number.

    Args:
        query: Name, email or keyword to search for
        max_results: Maximum number of results (default 10)
    """
    service = _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connecte ton compte Google dans les paramètres."

    try:
        result = await asyncio.to_thread(
            lambda: service.people().searchContacts(
                query=query,
                readMask="names,emailAddresses,phoneNumbers,organizations",
                pageSize=min(max_results, 30),
            ).execute()
        )

        results = result.get("results", [])
        if not results:
            return f"Aucun contact trouvé pour « {query} »."

        lines = [f"{len(results)} contact(s) trouvé(s) pour « {query} » :"]
        for r in results:
            p = r.get("person", {})
            names = p.get("names", [{}])
            name = names[0].get("displayName", "Sans nom") if names else "Sans nom"

            emails = [e["value"] for e in p.get("emailAddresses", [])]
            phones = [ph["value"] for ph in p.get("phoneNumbers", [])]
            orgs   = [o.get("name", "") for o in p.get("organizations", [])]

            line = f"• {name}"
            if emails: line += f" — {', '.join(emails)}"
            if phones: line += f" — {', '.join(phones)}"
            if orgs:   line += f" ({', '.join(o for o in orgs if o)})"
            lines.append(line)

        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur lors de la recherche de contacts : {exc}"


@tool
async def contacts_list(
    max_results: int = 20,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List Google Contacts (most recently updated first).

    Args:
        max_results: Number of contacts to return (default 20, max 100)
    """
    service = _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connecte ton compte Google dans les paramètres."

    try:
        result = await asyncio.to_thread(
            lambda: service.people().connections().list(
                resourceName="people/me",
                pageSize=min(max_results, 100),
                personFields="names,emailAddresses,phoneNumbers",
                sortOrder="LAST_MODIFIED_DESCENDING",
            ).execute()
        )

        connections = result.get("connections", [])
        if not connections:
            return "Aucun contact dans Google Contacts."

        lines = [f"{len(connections)} contact(s) :"]
        for p in connections:
            names  = p.get("names", [{}])
            name   = names[0].get("displayName", "Sans nom") if names else "Sans nom"
            emails = [e["value"] for e in p.get("emailAddresses", [])]
            phones = [ph["value"] for ph in p.get("phoneNumbers", [])]

            line = f"• {name}"
            if emails: line += f" — {', '.join(emails)}"
            if phones: line += f" — {', '.join(phones)}"
            lines.append(line)

        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur lors de la récupération des contacts : {exc}"


@tool
async def contacts_create(
    name: str,
    email: str = "",
    phone: str = "",
    company: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a new Google Contact.

    Args:
        name: Full name of the contact
        email: Email address (optional)
        phone: Phone number (optional)
        company: Company or organization (optional)
    """
    service = _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connecte ton compte Google dans les paramètres."

    body: dict = {"names": [{"givenName": name}]}
    if email:   body["emailAddresses"] = [{"value": email}]
    if phone:   body["phoneNumbers"]   = [{"value": phone}]
    if company: body["organizations"]  = [{"name": company}]

    try:
        result = await asyncio.to_thread(
            lambda: service.people().createContact(body=body).execute()
        )
        display = result.get("names", [{}])[0].get("displayName", name)
        return f"Contact créé : {display}" + (f" ({email})" if email else "")

    except Exception as exc:
        return f"Erreur lors de la création du contact : {exc}"
