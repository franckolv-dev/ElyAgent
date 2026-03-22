"""Gmail tools for ELY agent — read and send emails."""
from __future__ import annotations

import base64
from email.mime.text import MIMEText

from langchain_core.tools import tool


def _get_gmail_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)


@tool
async def gmail_list_emails(user_google_credentials_json: str, max_results: int = 10, query: str = "") -> str:
    """List recent emails from Gmail inbox.

    Args:
        user_google_credentials_json: Google credentials JSON (injected by agent context)
        max_results: Number of emails to return (default 10, max 50)
        query: Gmail search query (e.g. 'from:boss@company.com', 'subject:invoice', 'is:unread')
    """
    service = _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Demandez à l'utilisateur de connecter son compte Google dans les paramètres."

    try:
        params = {"userId": "me", "maxResults": min(max_results, 50)}
        if query:
            params["q"] = query
        result = service.users().messages().list(**params).execute()
        messages = result.get("messages", [])

        if not messages:
            return "Aucun email trouvé."

        emails = []
        for msg in messages[:max_results]:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            snippet = detail.get("snippet", "")[:100]
            emails.append(
                f"ID: {msg['id']}\n"
                f"De: {headers.get('From', 'Inconnu')}\n"
                f"Sujet: {headers.get('Subject', 'Sans sujet')}\n"
                f"Date: {headers.get('Date', '')}\n"
                f"Aperçu: {snippet}"
            )

        return f"{len(emails)} email(s) trouvé(s):\n\n" + "\n---\n".join(emails)
    except Exception as e:
        return f"Erreur Gmail: {e}"


@tool
async def gmail_read_email(user_google_credentials_json: str, email_id: str) -> str:
    """Read the full content of a specific email.

    Args:
        user_google_credentials_json: Google credentials JSON (injected by agent context)
        email_id: The email ID returned by gmail_list_emails
    """
    service = _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        msg = service.users().messages().get(userId="me", id=email_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        # Extract body
        body = ""
        payload = msg.get("payload", {})
        if "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        elif "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                    break

        return (
            f"De: {headers.get('From', 'Inconnu')}\n"
            f"À: {headers.get('To', '')}\n"
            f"Sujet: {headers.get('Subject', 'Sans sujet')}\n"
            f"Date: {headers.get('Date', '')}\n\n"
            f"{body[:3000]}"
        )
    except Exception as e:
        return f"Erreur lecture email: {e}"


@tool
async def gmail_send_email(user_google_credentials_json: str, to: str, subject: str, body: str) -> str:
    """Send an email via Gmail. ALWAYS ask user confirmation before sending.

    Args:
        user_google_credentials_json: Google credentials JSON (injected by agent context)
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
    """
    service = _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Email envoyé avec succès à {to} (sujet: {subject})"
    except Exception as e:
        return f"Erreur envoi email: {e}"
