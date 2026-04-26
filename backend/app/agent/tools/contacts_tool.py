# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/contacts_tool.py
# @brief      Google Contacts (People API) tools for ELY agent.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
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
"""Google Contacts (People API) tools for ELY agent."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.google_raw_api import execute_raw_call

logger = logging.getLogger(__name__)


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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
            year = bd.get('year', '??')
            month = bd.get('month')
            day = bd.get('day')
            month_s = f"{month:02d}" if isinstance(month, int) else "??"
            day_s = f"{day:02d}" if isinstance(day, int) else "??"
            lines.append(f"Anniversaire : {year}-{month_s}-{day_s}")
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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


# ──────────────────────────────────────────────────────────────────────────────
# Advanced Contacts tools — bulk operations + raw API
# ──────────────────────────────────────────────────────────────────────────────


@tool
async def contacts_batch_operations(
    operation: str,
    payload_json: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Batch create, update, or delete up to 200 Google Contacts in one request.

    Args:
        operation: One of:
            - 'create' : payload_json is a list of contact bodies.
                Example: '[{"names":[{"givenName":"Alice"}],
                "emailAddresses":[{"value":"a@x.com"}]}]'
            - 'update' : payload_json is {resourceName: contact} map with
                an 'update_mask' key (comma-separated field names).
                Example: '{"update_mask": "names,emailAddresses",
                "contacts": {"people/c1234": {"etag": "...",
                "names":[{"givenName":"Bob"}]}}}'
            - 'delete' : payload_json is a list of resource names.
                Example: '["people/c1234","people/c5678"]'
        payload_json: JSON payload (format depends on the operation).
    """
    service = await _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as e:
        return f"Erreur : payload_json doit être un JSON valide. Détail : {e}"

    try:
        if operation == "create":
            if not isinstance(payload, list):
                return "Erreur : pour 'create', payload_json doit être une liste de contacts."
            body = {
                "contacts": [
                    {"contactPerson": c, "clientData": []} if "contactPerson" not in c else c
                    for c in payload
                ],
                "readMask": "names,emailAddresses,phoneNumbers",
            }
            logger.info("contacts_batch_operations: create %d contact(s)", len(payload))
            result = await asyncio.to_thread(
                lambda: service.people().batchCreateContacts(body=body).execute()
            )
            created = result.get("createdPeople", [])
            return f"✓ {len(created)} contact(s) créé(s)"

        elif operation == "update":
            if not isinstance(payload, dict) or "contacts" not in payload:
                return "Erreur : pour 'update', payload_json doit contenir 'contacts' et 'update_mask'."
            body = {
                "contacts": payload["contacts"],
                "updateMask": payload.get("update_mask", "names,emailAddresses,phoneNumbers"),
                "readMask": "names,emailAddresses,phoneNumbers",
            }
            logger.info("contacts_batch_operations: update %d contact(s)", len(payload["contacts"]))
            result = await asyncio.to_thread(
                lambda: service.people().batchUpdateContacts(body=body).execute()
            )
            updated = result.get("updateResult", {})
            return f"✓ {len(updated)} contact(s) mis à jour"

        elif operation == "delete":
            if not isinstance(payload, list):
                return "Erreur : pour 'delete', payload_json doit être une liste de resourceNames."
            body = {"resourceNames": payload}
            logger.info("contacts_batch_operations: delete %d contact(s)", len(payload))
            await asyncio.to_thread(
                lambda: service.people().batchDeleteContacts(body=body).execute()
            )
            return f"✓ {len(payload)} contact(s) supprimé(s)"

        else:
            return "Erreur : operation doit être 'create', 'update' ou 'delete'."

    except Exception as e:
        logger.error("contacts_batch_operations (%s) failed: %s", operation, e)
        return f"Erreur contacts_batch_operations ({operation}) : {e}"


@tool
async def contacts_raw_api_call(
    method_path: str,
    params_json: str = "{}",
    body_json: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Call ANY method of the Google People API (v1) directly.

    Escape hatch for advanced operations: contact groups (labels),
    directory people (for Workspace accounts), etc.

    Args:
        method_path: Dot-separated People API method, e.g.
            'people.get', 'people.connections.list',
            'contactGroups.list', 'contactGroups.create',
            'contactGroups.members.modify', 'otherContacts.list'.
        params_json: JSON object of kwargs.
            Example: '{"resourceName": "people/c1234",
                        "personFields": "names,emailAddresses"}'
        body_json: Optional JSON body for POST/PATCH methods.
    """
    service = await _get_people_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    return execute_raw_call(service, method_path, params_json, body_json, "contacts")
