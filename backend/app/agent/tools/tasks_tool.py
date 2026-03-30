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
"""Google Tasks tools for ELY agent."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


async def _get_tasks_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("tasks", "v1", credentials=creds)


@tool
async def tasks_list(
    show_completed: bool = False,
    max_results: int = 20,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List tasks from Google Tasks.

    Args:
        show_completed: Include completed tasks (default False)
        max_results: Maximum number of tasks to return (default 20)
    """
    service = await _get_tasks_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        result = service.tasks().list(
            tasklist="@default",
            maxResults=min(max_results, 100),
            showCompleted=show_completed,
            showHidden=show_completed,
        ).execute()

        items = result.get("items", [])
        if not items:
            return "Aucune tâche trouvée."

        lines = []
        for t in items:
            status = "✓" if t.get("status") == "completed" else "○"
            due = f" (échéance: {t['due'][:10]})" if t.get("due") else ""
            notes = f"\n  Note: {t['notes']}" if t.get("notes") else ""
            lines.append(f"{status} {t.get('title', 'Sans titre')}{due}{notes}\n  ID: {t['id']}")

        return f"{len(items)} tâche(s):\n\n" + "\n\n".join(lines)
    except Exception as e:
        return f"Erreur récupération tâches : {e}"


@tool
async def tasks_create(
    title: str,
    notes: str = "",
    due_date: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a new task in Google Tasks.

    Args:
        title: Task title
        notes: Optional notes or description
        due_date: Optional due date in ISO 8601 format (e.g. '2025-06-15T00:00:00.000Z')
    """
    service = await _get_tasks_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        body: dict = {"title": title}
        if notes:
            body["notes"] = notes
        if due_date:
            body["due"] = due_date

        task = service.tasks().insert(tasklist="@default", body=body).execute()
        return f"Tâche créée : '{task.get('title')}' (ID: {task.get('id')})"
    except Exception as e:
        return f"Erreur création tâche : {e}"


@tool
async def tasks_complete(
    task_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Mark a Google Task as completed.

    Args:
        task_id: The task ID returned by tasks_list
    """
    service = await _get_tasks_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        task = service.tasks().patch(
            tasklist="@default",
            task=task_id,
            body={"status": "completed"},
        ).execute()
        return f"Tâche '{task.get('title')}' marquée comme terminée."
    except Exception as e:
        return f"Erreur mise à jour tâche : {e}"
