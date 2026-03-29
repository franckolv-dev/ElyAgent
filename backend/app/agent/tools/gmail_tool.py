"""Gmail tools for ELY agent — read, send, organize and clean emails."""
from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg


async def _get_gmail_service(user_google_credentials_json: str | None):
    from googleapiclient.discovery import build
    from app.services.google_auth import get_user_credentials
    creds = await get_user_credentials(user_google_credentials_json)
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)


@tool
async def gmail_list_emails(
    max_results: int = 10,
    query: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List recent emails from Gmail inbox.

    Args:
        max_results: Number of emails to return (default 10, max 50)
        query: Gmail search query (e.g. 'from:boss@company.com', 'subject:invoice', 'is:unread')
    """
    service = await _get_gmail_service(user_google_credentials_json)
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
async def gmail_read_email(
    email_id: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read the full content of a specific email.

    Args:
        email_id: The email ID returned by gmail_list_emails
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        msg = service.users().messages().get(userId="me", id=email_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

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
async def gmail_send_email(
    to: str,
    subject: str,
    body: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Send an email via Gmail. ALWAYS ask user confirmation before sending.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
    """
    service = await _get_gmail_service(user_google_credentials_json)
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


@tool
async def gmail_list_labels(
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List all Gmail labels (folders) for the user's mailbox.

    Use this before creating a label to check if it already exists.
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        result = service.users().labels().list(userId="me").execute()
        labels = result.get("labels", [])
        # Separate system labels from user-created ones
        system = [l for l in labels if l.get("type") == "system"]
        user_labels = [l for l in labels if l.get("type") == "user"]

        lines = ["📁 **Labels système :**"]
        lines += [f"  - {l['name']} (id: {l['id']})" for l in system]
        lines += ["", "📂 **Labels personnalisés :**"]
        if user_labels:
            lines += [f"  - {l['name']} (id: {l['id']})" for l in user_labels]
        else:
            lines.append("  (aucun label personnalisé)")

        return "\n".join(lines)
    except Exception as e:
        return f"Erreur liste labels: {e}"


@tool
async def gmail_create_label(
    name: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a new Gmail label (folder). Returns the label ID.

    First use gmail_list_labels to check if it already exists.

    Args:
        name: Label name, e.g. 'Newsletters', 'À trier', 'Démarchage'
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        label_body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        result = service.users().labels().create(userId="me", body=label_body).execute()
        return f"Label '{name}' créé avec succès (id: {result['id']})"
    except Exception as e:
        if "already exists" in str(e).lower() or "409" in str(e):
            return f"Le label '{name}' existe déjà."
        return f"Erreur création label: {e}"


@tool
async def gmail_move_emails(
    email_ids: list[str],
    label_name: str,
    remove_from_inbox: bool = True,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Move emails to a label/folder. ALWAYS ask user confirmation before executing.

    Shows a summary of what will be moved and asks for explicit confirmation.
    The label must exist — use gmail_create_label first if needed.

    Args:
        email_ids: List of email IDs to move (from gmail_list_emails)
        label_name: Target label name (e.g. 'Newsletters')
        remove_from_inbox: Whether to also remove from INBOX (default True = move, False = copy label)
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    if not email_ids:
        return "Aucun email fourni."

    try:
        # Find the label ID from its name
        labels_result = service.users().labels().list(userId="me").execute()
        label_id = None
        for lbl in labels_result.get("labels", []):
            if lbl["name"].lower() == label_name.lower():
                label_id = lbl["id"]
                break

        if not label_id:
            return (
                f"Label '{label_name}' introuvable. "
                f"Utilisez gmail_create_label('{label_name}') d'abord."
            )

        # Build modify body
        add_labels = [label_id]
        remove_labels = ["INBOX"] if remove_from_inbox else []

        modify_body = {
            "ids": email_ids,
            "addLabelIds": add_labels,
            "removeLabelIds": remove_labels,
        }
        service.users().messages().batchModify(userId="me", body=modify_body).execute()

        action = "déplacés vers" if remove_from_inbox else "étiquetés"
        return (
            f"✅ {len(email_ids)} email(s) {action} le label '{label_name}' avec succès."
        )
    except Exception as e:
        return f"Erreur déplacement emails: {e}"


@tool
async def gmail_trash_emails(
    email_ids: list[str],
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Move emails to Trash. REQUIRES explicit user confirmation before executing.

    ⚠️ IMPORTANT: ALWAYS present the list of emails to be trashed to the user
    and wait for explicit confirmation (yes/oui/confirme) before calling this tool.
    Never call this tool without prior user approval in the current conversation.

    Args:
        email_ids: List of email IDs to trash (from gmail_list_emails)
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    if not email_ids:
        return "Aucun email fourni."

    try:
        errors = []
        success_count = 0
        for email_id in email_ids:
            try:
                service.users().messages().trash(userId="me", id=email_id).execute()
                success_count += 1
            except Exception as e:
                errors.append(f"{email_id}: {e}")

        result = f"🗑️ {success_count}/{len(email_ids)} email(s) envoyés à la corbeille."
        if errors:
            result += f"\nErreurs ({len(errors)}): " + "; ".join(errors[:3])
        return result
    except Exception as e:
        return f"Erreur suppression emails: {e}"


@tool
async def gmail_search_for_cleanup(
    category: str = "newsletters",
    max_results: int = 50,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search for emails to clean up (newsletters, promotions, marketing, etc.).

    Returns a list of email IDs and summaries for the user to review before acting.
    Always present results to the user before calling gmail_move_emails or gmail_trash_emails.

    Args:
        category: Type of emails to find. Options:
          - 'newsletters' : newsletters et abonnements
          - 'promotions'  : emails promotionnels et offres commerciales
          - 'social'      : notifications réseaux sociaux
          - 'demarchage'  : démarchage commercial et prospection
          - 'all_cleanup' : toutes les catégories ci-dessus combinées
        max_results: Max number of emails to find (default 50, max 100)
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    # Gmail search queries per category
    queries = {
        "newsletters": (
            "category:updates OR (unsubscribe AND (newsletter OR mailing)) "
            "OR subject:(newsletter OR \"se désabonner\" OR unsubscribe)"
        ),
        "promotions": "category:promotions",
        "social": "category:social",
        "demarchage": (
            "(démarchage OR prospection OR \"offre commerciale\" OR \"offre exclusive\" "
            "OR \"ne manquez pas\" OR \"offre limitée\" OR \"promo\" OR soldes) "
            "AND (unsubscribe OR désabonner OR \"se désinscrire\")"
        ),
        "all_cleanup": (
            "category:promotions OR category:updates OR "
            "(unsubscribe AND (newsletter OR mailing OR promo OR offre))"
        ),
    }

    query = queries.get(category, queries["all_cleanup"])
    max_results = min(max_results, 100)

    try:
        result = service.users().messages().list(
            userId="me", maxResults=max_results, q=query
        ).execute()
        messages = result.get("messages", [])

        if not messages:
            return f"Aucun email de type '{category}' trouvé avec ces critères."

        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date", "List-Unsubscribe"]
            ).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            emails.append({
                "id": msg["id"],
                "from": headers.get("From", "?"),
                "subject": headers.get("Subject", "(sans sujet)"),
                "date": headers.get("Date", "?"),
                "has_unsubscribe": bool(headers.get("List-Unsubscribe")),
            })

        # Group by sender for summary
        senders: dict[str, int] = {}
        for e in emails:
            sender = e["from"].split("<")[0].strip().strip('"') or e["from"]
            senders[sender] = senders.get(sender, 0) + 1

        top_senders = sorted(senders.items(), key=lambda x: x[1], reverse=True)[:10]
        ids = [e["id"] for e in emails]

        summary = [
            f"🔍 **{len(emails)} email(s) trouvé(s)** (catégorie: {category})\n",
            "**Top expéditeurs :**",
        ]
        for sender, count in top_senders:
            summary.append(f"  • {sender} : {count} email(s)")

        summary += [
            "",
            f"**IDs (à utiliser avec gmail_move_emails ou gmail_trash_emails) :**",
            str(ids),
            "",
            "⚠️ Présente ce résumé à l'utilisateur et demande confirmation avant toute action.",
        ]

        return "\n".join(summary)
    except Exception as e:
        return f"Erreur recherche emails: {e}"
