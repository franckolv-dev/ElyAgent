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
"""Google Contacts (People API) tools for ELY agent."""
from __future__ import annotations

import asyncio
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


async def _get_people_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
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
    service = await _get_people_service(user_google_credentials_json)
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
            resource = p.get("resourceName", "")
            names = p.get("names", [{}])
            name = names[0].get("displayName", "Sans nom") if names else "Sans nom"

            emails = [e["value"] for e in p.get("emailAddresses", [])]
            phones = [ph["value"] for ph in p.get("phoneNumbers", [])]
            orgs   = [o.get("name", "") for o in p.get("organizations", [])]

            line = f"• {name}"
            if emails: line += f" — {', '.join(emails)}"
            if phones: line += f" — {', '.join(phones)}"
            if orgs:   line += f" ({', '.join(o for o in orgs if o)})"
            if resource: line += f"\n  resourceName: {resource}"
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
    service = await _get_people_service(user_google_credentials_json)
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
            resource = p.get("resourceName", "")
            names  = p.get("names", [{}])
            name   = names[0].get("displayName", "Sans nom") if names else "Sans nom"
            emails = [e["value"] for e in p.get("emailAddresses", [])]
            phones = [ph["value"] for ph in p.get("phoneNumbers", [])]

            line = f"• {name}"
            if emails: line += f" — {', '.join(emails)}"
            if phones: line += f" — {', '.join(phones)}"
            if resource: line += f"\n  resourceName: {resource}"
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
    service = await _get_people_service(user_google_credentials_json)
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
        resource = result.get("resourceName", "")
        return f"Contact créé : {display}" + (f" ({email})" if email else "") + f"\nresourceName: {resource}"

    except Exception as exc:
        return f"Erreur lors de la création du contact : {exc}"


@tool
async def contacts_get(
    resource_name: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Get full details of a Google Contact.

    Args:
        resource_name: The contact resource name (e.g. 'people/c1234567890')
    """
    service = await _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connecte ton compte Google dans les paramètres."

    try:
        person = await asyncio.to_thread(
            lambda: service.people().get(
                resourceName=resource_name,
                personFields="names,emailAddresses,phoneNumbers,organizations,addresses,birthdays,biographies",
            ).execute()
        )

        names = person.get("names", [{}])
        name = names[0].get("displayName", "Sans nom") if names else "Sans nom"
        emails = [e["value"] for e in person.get("emailAddresses", [])]
        phones = [ph["value"] for ph in person.get("phoneNumbers", [])]
        orgs = [o.get("name", "") for o in person.get("organizations", [])]
        addresses = [a.get("formattedValue", "") for a in person.get("addresses", [])]
        birthdays = person.get("birthdays", [])
        bios = [b.get("value", "") for b in person.get("biographies", [])]

        lines = [f"Contact : {name}", f"resourceName: {resource_name}"]
        if emails:    lines.append(f"Email : {', '.join(emails)}")
        if phones:    lines.append(f"Téléphone : {', '.join(phones)}")
        if orgs:      lines.append(f"Organisation : {', '.join(o for o in orgs if o)}")
        if addresses: lines.append(f"Adresse : {', '.join(a for a in addresses if a)}")
        if birthdays:
            bd = birthdays[0].get("date", {})
            lines.append(f"Anniversaire : {bd.get('year', '??')}-{bd.get('month', '??'):02}-{bd.get('day', '??'):02}")
        if bios:      lines.append(f"Notes : {'; '.join(b for b in bios if b)}")

        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur lors de la récupération du contact : {exc}"


@tool
async def contacts_update(
    resource_name: str,
    name: str = "",
    email: str = "",
    phone: str = "",
    company: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Update an existing Google Contact. Only non-empty fields are modified.

    Args:
        resource_name: The contact resource name (e.g. 'people/c1234567890')
        name: New full name (optional)
        email: New email address (optional)
        phone: New phone number (optional)
        company: New company or organization (optional)
    """
    service = await _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connecte ton compte Google dans les paramètres."

    try:
        # Fetch current contact to get etag
        current = await asyncio.to_thread(
            lambda: service.people().get(
                resourceName=resource_name,
                personFields="names,emailAddresses,phoneNumbers,organizations",
            ).execute()
        )

        body: dict = {"etag": current["etag"]}
        if name:    body["names"] = [{"givenName": name}]
        else:       body["names"] = current.get("names", [])
        if email:   body["emailAddresses"] = [{"value": email}]
        else:       body["emailAddresses"] = current.get("emailAddresses", [])
        if phone:   body["phoneNumbers"] = [{"value": phone}]
        else:       body["phoneNumbers"] = current.get("phoneNumbers", [])
        if company: body["organizations"] = [{"name": company}]
        else:       body["organizations"] = current.get("organizations", [])

        result = await asyncio.to_thread(
            lambda: service.people().updateContact(
                resourceName=resource_name,
                updatePersonFields="names,emailAddresses,phoneNumbers,organizations",
                body=body,
            ).execute()
        )

        display = result.get("names", [{}])[0].get("displayName", resource_name)
        return f"Contact mis à jour : {display} ({resource_name})"

    except Exception as exc:
        return f"Erreur lors de la mise à jour du contact : {exc}"


@tool
async def contacts_delete(
    resource_name: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Delete a Google Contact. This action is irreversible — requires user confirmation (HITL).

    Args:
        resource_name: The contact resource name (e.g. 'people/c1234567890')
    """
    service = await _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connecte ton compte Google dans les paramètres."

    try:
        await asyncio.to_thread(
            lambda: service.people().deleteContact(
                resourceName=resource_name,
            ).execute()
        )

        return f"Contact supprimé : {resource_name}"

    except Exception as exc:
        return f"Erreur lors de la suppression du contact : {exc}"
