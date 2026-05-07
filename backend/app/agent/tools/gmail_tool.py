# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/gmail_tool.py
# @brief      Gmail tools for ELY agent — read, send, organize and clean emails.
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
"""Gmail tools for ELY agent — read, send, organize and clean emails."""
from __future__ import annotations

import base64
import json
import logging
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.google_raw_api import execute_raw_call

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup categories — shared between gmail_search_for_cleanup and
# gmail_trash_by_category. The user vocabulary is FR-first so we accept many
# aliases (singular/plural, FR/EN, common synonyms) and normalize to a
# canonical key. Each canonical key maps to a Gmail search query.
#
# Why so many aliases : the LLM often parrots the user's exact wording
# ("vide les indésirables", "supprime mes mailings", "purge les achats").
# Without aliases the tool returns "category not recognized" and the LLM has
# to guess — which sometimes fails. Aliases eliminate the guessing.
# ──────────────────────────────────────────────────────────────────────────────

_CLEANUP_QUERIES: dict[str, str] = {
    # Gmail tab categories (the 5 system tabs)
    "promotions":   "category:promotions",
    "social":       "category:social",
    "forums":       "category:forums",
    "updates":      "category:updates",
    "purchases":    "category:purchases",  # Onglet "Achats" Gmail
    # Special folders
    "spam":         "in:spam",
    "trash":        "in:trash",
    # Heuristic-based searches
    "newsletters":  (
        "category:updates OR (unsubscribe AND (newsletter OR mailing)) "
        "OR subject:(newsletter OR \"se désabonner\" OR unsubscribe)"
    ),
    "demarchage":   (
        "(démarchage OR prospection OR \"offre commerciale\" OR \"offre exclusive\" "
        "OR \"ne manquez pas\" OR \"offre limitée\" OR soldes) "
        "AND (unsubscribe OR désabonner OR \"se désinscrire\")"
    ),
    # Aggregations
    "all_cleanup":  (
        "category:promotions OR category:updates OR category:purchases OR "
        "(unsubscribe AND (newsletter OR mailing OR promo OR offre))"
    ),
    "all_categories": (
        "category:promotions OR category:social OR category:forums OR "
        "category:updates OR category:purchases"
    ),
}

# Alias → canonical key. Lowercased on lookup. Accept singular/plural,
# FR/EN, and common user wording. Maintained alphabetically.
_CLEANUP_ALIASES: dict[str, str] = {
    # spam
    "spams":               "spam",
    "indesirable":         "spam",
    "indesirables":        "spam",
    "indésirable":         "spam",
    "indésirables":        "spam",
    "courrier indesirable":  "spam",
    "courriers indesirables": "spam",
    "courrier indésirable":   "spam",
    "courriers indésirables": "spam",
    "junk":                "spam",
    # trash / corbeille
    "corbeille":           "trash",
    "poubelle":            "trash",
    # newsletters / mailings
    "newsletter":          "newsletters",
    "mailing":             "newsletters",
    "mailings":            "newsletters",
    "infolettre":          "newsletters",
    "infolettres":         "newsletters",
    "abonnement":          "newsletters",
    "abonnements":         "newsletters",
    "lettre d'information":   "newsletters",
    "lettres d'information":  "newsletters",
    # promotions
    "promo":               "promotions",
    "promos":              "promotions",
    "promotion":           "promotions",
    "soldes":              "promotions",
    "offre":               "promotions",
    "offres":              "promotions",
    "offres commerciales": "promotions",
    "deals":               "promotions",
    # social
    "réseaux sociaux":     "social",
    "reseaux sociaux":     "social",
    "réseaux":             "social",
    "reseaux":             "social",
    "social media":        "social",
    "facebook":            "social",
    "instagram":           "social",
    "linkedin":            "social",
    "twitter":             "social",
    # forums
    "forum":               "forums",
    "discussion":          "forums",
    "discussions":         "forums",
    "groupes":             "forums",
    # updates / notifications
    "notification":        "updates",
    "notifications":       "updates",
    "alerte":              "updates",
    "alertes":             "updates",
    "mise à jour":         "updates",
    "mises à jour":        "updates",
    "mise a jour":         "updates",
    "mises a jour":        "updates",
    # purchases / achats
    "achat":               "purchases",
    "achats":              "purchases",
    "commande":            "purchases",
    "commandes":           "purchases",
    "factures":            "purchases",
    "facture":             "purchases",
    "receipts":            "purchases",
    "receipt":             "purchases",
    # demarchage
    "prospection":         "demarchage",
    "publicité":           "demarchage",
    "publicités":          "demarchage",
    "publicites":          "demarchage",
    "pub":                 "demarchage",
    "pubs":                "demarchage",
    "spam commercial":     "demarchage",
    # all
    "tout":                "all_cleanup",
    "tous":                "all_cleanup",
    "all":                 "all_cleanup",
    "everything":          "all_cleanup",
    "all categories":      "all_categories",
    "toutes catégories":   "all_categories",
    "toutes categories":   "all_categories",
}


def _resolve_cleanup_category(category: str) -> str | None:
    """Normalize user input to a canonical category key, or None if unknown.

    Tries (in order) :
      1. Exact match in _CLEANUP_QUERIES (canonical key).
      2. Lowercased exact match.
      3. Alias lookup in _CLEANUP_ALIASES.
      4. Strip plural 's' as last resort.
    """
    if not category:
        return None
    if category in _CLEANUP_QUERIES:
        return category
    low = category.strip().lower()
    if low in _CLEANUP_QUERIES:
        return low
    if low in _CLEANUP_ALIASES:
        return _CLEANUP_ALIASES[low]
    # Last resort : strip trailing 's' (achats → achat → purchases)
    if low.endswith("s") and low[:-1] in _CLEANUP_ALIASES:
        return _CLEANUP_ALIASES[low[:-1]]
    return None


def _extract_body(payload: dict) -> str:
    """Recursively extract text/plain body from a Gmail message payload.

    Handles multipart/mixed > multipart/alternative > text/plain nesting.
    """
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result
    return ""


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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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

        payload = msg.get("payload", {})
        body = _extract_body(payload)

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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
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
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search for emails to clean up (newsletters, promotions, social, spam, etc.).

    Returns a list of email IDs and summaries for the user to review before acting.
    Always present results to the user before calling gmail_move_emails or gmail_trash_emails.

    Args:
        category: Type of emails to find. Many natural-language aliases are
            accepted (singular/plural, FR/EN). Canonical values :
          - 'newsletters'   : newsletters/mailings (aliases: newsletter, mailing,
                              mailings, infolettre, abonnements)
          - 'promotions'    : Gmail tab "Promotions" (aliases: promo, soldes,
                              offres, deals)
          - 'social'        : Gmail tab "Réseaux sociaux" (aliases: reseaux,
                              facebook, linkedin, ...)
          - 'forums'        : Gmail tab "Forums" (alias: discussions, groupes)
          - 'updates'       : Gmail tab "Notifications" (aliases: notifications,
                              alertes, mises a jour)
          - 'purchases'     : Gmail tab "Achats" (aliases: achats, commandes,
                              factures, receipts)
          - 'spam'          : dossier SPAM (aliases: spams, indesirables, junk)
          - 'trash'         : corbeille (aliases: corbeille, poubelle)
          - 'demarchage'    : démarchage / prospection (aliases: pubs, publicites)
          - 'all_cleanup'   : promotions + updates + purchases + heuristique
          - 'all_categories': tous les onglets Gmail combinés
        max_results: Max number of emails to find (default 50, max 100)
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    # Resolve aliases (FR/EN, singular/plural, common synonyms). The shared
    # _resolve_cleanup_category helper accepts e.g. "indesirables", "mailings",
    # "achats", "réseaux sociaux", etc. Hard error if still not recognized so
    # the LLM eval node sees the mistake and replans with a valid category.
    canonical = _resolve_cleanup_category(category)
    if canonical is None:
        return (
            f"Catégorie '{category}' non reconnue. Valeurs acceptées : "
            f"{', '.join(sorted(_CLEANUP_QUERIES.keys()))} "
            f"(alias FR/EN également acceptés : achats, indésirables, mailing, "
            f"promo, notifications, corbeille, ...)."
        )
    query = _CLEANUP_QUERIES[canonical]
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


@tool
async def gmail_trash_by_category(
    category: str = "spam",
    max_results: int = 100,
    from_sender: str = "",
    subject_contains: str = "",
    after_date: str = "",
    before_date: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Search emails by category AND move them to trash in ONE atomic call.

    PREFER this tool whenever the goal is to delete, empty, or clean up
    a Gmail folder or category. Combines search + trash so the LLM never
    has to manipulate individual email IDs (which it tends to hallucinate).

    The tool DOES NOT take IDs — just pass the category name.
    HITL is forced (this is a destructive batch operation).

    OPTIONAL FILTERS — combine with the category to narrow down :
      - from_sender       : restrict to a sender (matches `from:<sender>`)
      - subject_contains  : restrict to subjects containing this text
      - after_date        : YYYY/MM/DD lower bound (matches `after:`)
      - before_date       : YYYY/MM/DD upper bound (matches `before:`)
    ⚠️ If the user request mentions a SENDER, a SUBJECT KEYWORD, or a DATE
    RANGE, you MUST pass these filters — otherwise the tool will purge
    the WHOLE category indiscriminately, which is dangerous (May 2026
    incident : « supprime les achats Temu » without from_sender purged
    100+ legitimate non-Temu purchase emails).

    Args:
        category: Category to purge. Many natural-language aliases accepted
          (singular/plural, FR/EN). Canonical values :
          'spam' (alias: spams, indesirables, junk), 'trash' (corbeille,
          poubelle), 'newsletters' (mailing, mailings, infolettre, abonnements),
          'promotions' (promo, soldes, offres), 'social' (reseaux sociaux,
          facebook, linkedin), 'forums' (discussions, groupes), 'updates'
          (notifications, alertes), 'purchases' (achats, commandes, factures),
          'demarchage' (pubs, prospection), 'all_cleanup' (tout),
          'all_categories' (toutes catégories).
        max_results: Max number of emails to trash in one call (default 100,
          max 500). If the folder has more, call this tool again until empty.
        from_sender: Optional. Restrict to emails from this sender (name or
          address). Example: "Temu", "noreply@amazon.fr".
        subject_contains: Optional. Restrict to emails whose subject contains
          this text. Example: "facture", "confirmation".
        after_date: Optional. Format YYYY/MM/DD. Only emails received after
          this date.
        before_date: Optional. Format YYYY/MM/DD. Only emails received before
          this date.

    Returns: a human-readable summary with N emails trashed (and the exact
    Gmail query used, for transparency).
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte dans les paramètres."

    canonical = _resolve_cleanup_category(category)
    if canonical is None:
        return (
            f"Catégorie '{category}' non reconnue. Valeurs acceptées : "
            f"{', '.join(sorted(_CLEANUP_QUERIES.keys()))} "
            f"(alias FR/EN également acceptés : achats, indésirables, mailing, "
            f"promo, notifications, corbeille, ...)."
        )

    max_results = min(max(1, max_results), 500)
    base_query = _CLEANUP_QUERIES[canonical]

    # Compose the final Gmail query with optional filters
    query_parts = [f"({base_query})"]
    if from_sender.strip():
        sender = from_sender.strip()
        # Quote if contains spaces (Gmail accepts both forms)
        if " " in sender and not (sender.startswith('"') and sender.endswith('"')):
            sender = f'"{sender}"'
        query_parts.append(f"from:{sender}")
    if subject_contains.strip():
        sub = subject_contains.strip()
        if " " in sub and not (sub.startswith('"') and sub.endswith('"')):
            sub = f'"{sub}"'
        query_parts.append(f"subject:{sub}")
    if after_date.strip():
        query_parts.append(f"after:{after_date.strip()}")
    if before_date.strip():
        query_parts.append(f"before:{before_date.strip()}")
    query = " ".join(query_parts)

    try:
        # 1. Find all matching IDs (paginated for large folders)
        ids: list[str] = []
        page_token = None
        while len(ids) < max_results:
            req = service.users().messages().list(
                userId="me",
                maxResults=min(100, max_results - len(ids)),
                q=query,
                pageToken=page_token,
            ).execute()
            batch = req.get("messages", [])
            ids.extend([m["id"] for m in batch])
            page_token = req.get("nextPageToken")
            if not page_token or not batch:
                break

        if not ids:
            return f"✅ Rien à faire : aucun email '{category}' trouvé."

        # 2. Trash them all (Gmail API supports up to 1000 IDs per batchModify)
        trashed = 0
        errors = 0
        for i in range(0, len(ids), 1000):
            chunk = ids[i:i + 1000]
            try:
                # batchModify with addLabelIds=['TRASH'] is the bulk trash API
                service.users().messages().batchModify(
                    userId="me",
                    body={"ids": chunk, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
                ).execute()
                trashed += len(chunk)
            except Exception as exc:
                errors += len(chunk)
                logger.warning("gmail_trash_by_category chunk failed: %s", exc)

        # Build a transparent summary mentioning the actual filters applied
        # (so the LLM evaluator + the user can see exactly what was matched).
        filter_desc = []
        if from_sender.strip():
            filter_desc.append(f"expéditeur≈« {from_sender.strip()} »")
        if subject_contains.strip():
            filter_desc.append(f"sujet contient « {subject_contains.strip()} »")
        if after_date.strip():
            filter_desc.append(f"après {after_date.strip()}")
        if before_date.strip():
            filter_desc.append(f"avant {before_date.strip()}")
        filter_str = (" + " + " + ".join(filter_desc)) if filter_desc else ""

        if errors == 0:
            return (
                f"🗑️ ✅ {trashed} email(s) déplacés vers la corbeille. "
                f"Catégorie : '{category}'{filter_str}. "
                f"Query Gmail : `{query}`"
            )
        return (
            f"🗑️ {trashed} email(s) déplacés vers la corbeille, "
            f"{errors} échec(s). Catégorie : '{category}'{filter_str}."
        )
    except Exception as e:
        return f"Erreur gmail_trash_by_category: {e}"


@tool
async def gmail_trash_by_query(
    query: str,
    max_results: int = 100,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Trash emails matching an arbitrary Gmail search query.

    USE THIS for complex deletions that don't map cleanly to a category :
    multiple senders combined with date ranges, custom labels, OR
    expressions, attachments, etc. The query syntax is exactly Gmail's
    search bar syntax.

    For simple « purge a whole category » : prefer `gmail_trash_by_category`.
    For « purge category X from sender Y » : ALSO prefer `gmail_trash_by_category`
    with `from_sender=Y` (it's narrower and safer).

    HITL is forced (this is a destructive batch operation).

    Examples :
      query='from:Temu category:purchases'              → only Temu purchases
      query='label:ELY-Test before:2025/01/01'           → old custom label
      query='subject:facture has:attachment older_than:1y' → 1+ y/o invoices
      query='(from:noreply OR from:no-reply) is:unread'  → unread automated
      query='in:spam from:*@temu.com'                    → only Temu spam

    Args:
        query: A valid Gmail search expression (same syntax as the Gmail
            search bar). The function will paginate up to `max_results`.
        max_results: Max number of emails to trash (default 100, max 500).
            If the query matches more, call again until the result is empty.

    Returns: a summary with N emails trashed and the exact query used.
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté. Connectez votre compte dans les paramètres."

    if not query or not query.strip():
        return (
            "Erreur : query vide. Pour vider toute une catégorie sans filtre, "
            "utilise gmail_trash_by_category(category='...')."
        )

    max_results = min(max(1, max_results), 500)

    try:
        # 1. Find matching IDs (paginated)
        ids: list[str] = []
        page_token = None
        while len(ids) < max_results:
            req = service.users().messages().list(
                userId="me",
                maxResults=min(100, max_results - len(ids)),
                q=query,
                pageToken=page_token,
            ).execute()
            batch = req.get("messages", [])
            ids.extend([m["id"] for m in batch])
            page_token = req.get("nextPageToken")
            if not page_token or not batch:
                break

        if not ids:
            return f"✅ Rien à faire : aucun email ne matche `{query}`."

        # 2. Trash via batchModify (chunks of 1000 max per Gmail API)
        trashed = 0
        errors = 0
        for i in range(0, len(ids), 1000):
            chunk = ids[i:i + 1000]
            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={"ids": chunk, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
                ).execute()
                trashed += len(chunk)
            except Exception as exc:
                errors += len(chunk)
                logger.warning("gmail_trash_by_query chunk failed: %s", exc)

        if errors == 0:
            return f"🗑️ ✅ {trashed} email(s) déplacés vers la corbeille. Query : `{query}`"
        return (
            f"🗑️ {trashed} email(s) déplacés vers la corbeille, {errors} échec(s). "
            f"Query : `{query}`"
        )
    except Exception as e:
        return f"Erreur gmail_trash_by_query: {e}"


@tool
async def gmail_reply_email(
    email_id: str,
    body: str,
    reply_all: bool = False,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Reply to an email. ALWAYS ask user confirmation before sending.

    Args:
        email_id: The email ID to reply to (from gmail_list_emails)
        body: Reply body (plain text)
        reply_all: If True, reply to all recipients (To + Cc)
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        # Fetch original message metadata
        original = service.users().messages().get(
            userId="me", id=email_id, format="metadata",
            metadataHeaders=["Message-ID", "References", "Subject", "From", "To", "Cc"]
        ).execute()
        headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}

        original_message_id = headers.get("Message-ID", "")
        references = headers.get("References", "")
        subject = headers.get("Subject", "")
        from_addr = headers.get("From", "")
        to_addr = headers.get("To", "")
        cc_addr = headers.get("Cc", "")

        # Build reply subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Build reply message
        message = MIMEText(body)
        message["Subject"] = subject
        message["In-Reply-To"] = original_message_id
        message["References"] = f"{references} {original_message_id}".strip()

        if reply_all:
            # Reply to sender
            message["To"] = from_addr
            # Get user's own email to exclude from Cc
            profile = service.users().getProfile(userId="me").execute()
            my_email = profile.get("emailAddress", "").lower()
            # Combine original To + Cc, exclude own email
            all_recipients = f"{to_addr}, {cc_addr}".strip(", ")
            cc_list = [
                addr.strip() for addr in all_recipients.split(",")
                if addr.strip() and my_email not in addr.lower()
            ]
            if cc_list:
                message["Cc"] = ", ".join(cc_list)
        else:
            message["To"] = from_addr

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        thread_id = original.get("threadId", "")
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        service.users().messages().send(userId="me", body=send_body).execute()
        dest = from_addr if not reply_all else f"{from_addr} (+ Cc)"
        return f"Réponse envoyée avec succès à {dest} (sujet: {subject})"
    except Exception as e:
        return f"Erreur réponse email: {e}"


@tool
async def gmail_send_with_attachment(
    to: str,
    subject: str,
    body: str,
    drive_file_id: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Send an email with an attachment from Google Drive. ALWAYS ask user confirmation before sending.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
        drive_file_id: Google Drive file ID to attach (optional)
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(body))

        if drive_file_id:
            from googleapiclient.discovery import build
            from app.services.google_auth import get_user_credentials

            creds = await get_user_credentials(user_google_credentials_json)
            if not creds:
                return "Google non connecté (Drive)."

            drive_service = build("drive", "v3", credentials=creds)
            file_meta = drive_service.files().get(
                fileId=drive_file_id, fields="name,mimeType,size"
            ).execute()
            file_name = file_meta.get("name", "attachment")
            mime_type = file_meta.get("mimeType", "application/octet-stream")

            # Check file size against Gmail's 25 MB attachment limit
            size = int(file_meta.get("size", 0))
            if size > 25 * 1024 * 1024:
                return f"Fichier trop volumineux ({size // (1024*1024)} Mo). Gmail limite les pieces jointes a 25 Mo."

            file_content = drive_service.files().get_media(fileId=drive_file_id).execute()

            maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")
            attachment = MIMEBase(maintype, subtype)
            attachment.set_payload(file_content)
            encoders.encode_base64(attachment)
            attachment.add_header("Content-Disposition", "attachment", filename=file_name)
            message.attach(attachment)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

        attachment_info = f" avec pièce jointe (Drive: {drive_file_id})" if drive_file_id else ""
        return f"Email envoyé avec succès à {to} (sujet: {subject}){attachment_info}"
    except Exception as e:
        return f"Erreur envoi email avec pièce jointe: {e}"


# Whitelist des dossiers où les tools générateurs de fichiers (browser_screenshot,
# os_screenshot, image_*, qrcode_*, etc.) peuvent écrire. Toute tentative
# d'attachement depuis un autre chemin est refusée pour éviter qu'un LLM
# halluciné dise `local_path="/etc/passwd"` ou similaire.
_ALLOWED_ATTACHMENT_DIRS: tuple[str, ...] = (
    "/tmp/ely-attachments",
    "/data/attachments",
    "/app/data/attachments",
)


@tool
async def gmail_send_with_local_attachment(
    to: str,
    subject: str,
    body: str,
    local_path: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Send an email with a LOCAL FILE attachment (NOT from Google Drive).

    Use this when the file was just generated by another tool — for example:
      - `browser_screenshot` returns a `local_path` you can pass here
      - `os_screenshot`, `qrcode_generate`, `generate_image` likewise
      - any tool that writes to /tmp/ely-attachments/

    For files already in Drive, use `gmail_send_with_attachment` instead.
    ALWAYS ask user confirmation before sending.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
        local_path: Filesystem path returned by another tool (must be inside
                    the ELY attachments directory — paths outside are refused)
    """
    import os
    import mimetypes
    from email.mime.base import MIMEBase
    from email import encoders as _encoders

    # ── Garde de sécurité — path whitelist ────────────────────────────────
    # On normalise et on vérifie que le chemin pointe bien dans un dossier
    # autorisé. Refuse explicitement les `..` et tout chemin absolu hors
    # whitelist pour éviter qu'un LLM halluciné dise `/etc/passwd`.
    if not local_path:
        return "Erreur : local_path est vide. Indique le chemin retourné par le tool précédent (ex. browser_screenshot)."
    abs_path = os.path.realpath(local_path)
    in_whitelist = any(abs_path.startswith(d + os.sep) for d in _ALLOWED_ATTACHMENT_DIRS)
    if not in_whitelist:
        return (
            f"Erreur : chemin '{local_path}' refusé pour raisons de sécurité. "
            f"Les pièces jointes locales doivent être dans : "
            f"{', '.join(_ALLOWED_ATTACHMENT_DIRS)}"
        )
    if not os.path.isfile(abs_path):
        return f"Erreur : fichier introuvable à '{abs_path}'."
    size = os.path.getsize(abs_path)
    if size > 25 * 1024 * 1024:
        return f"Fichier trop volumineux ({size // (1024*1024)} Mo). Gmail limite les pièces jointes à 25 Mo."
    if size == 0:
        return "Erreur : le fichier est vide (0 octet)."

    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(body))

        # Détection du MIME type basée sur l'extension
        mime_type, _ = mimetypes.guess_type(abs_path)
        if not mime_type:
            mime_type = "application/octet-stream"
        maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")

        with open(abs_path, "rb") as f:
            file_content = f.read()
        attachment = MIMEBase(maintype, subtype)
        attachment.set_payload(file_content)
        _encoders.encode_base64(attachment)
        file_name = os.path.basename(abs_path)
        attachment.add_header("Content-Disposition", "attachment", filename=file_name)
        message.attach(attachment)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

        return (
            f"Email envoyé avec succès à {to} (sujet: {subject}) "
            f"avec pièce jointe locale '{file_name}' ({size // 1024} Ko)."
        )
    except Exception as e:
        return f"Erreur envoi email avec pièce jointe locale: {e}"


@tool
async def gmail_mark_read(
    email_ids: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Mark emails as read.

    Args:
        email_ids: Comma-separated email IDs (e.g. 'id1,id2,id3')
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        ids = [eid.strip() for eid in email_ids.split(",") if eid.strip()]
        if not ids:
            return "Aucun ID d'email fourni."

        service.users().messages().batchModify(
            userId="me",
            body={"ids": ids, "removeLabelIds": ["UNREAD"]},
        ).execute()
        return f"{len(ids)} email(s) marqué(s) comme lu(s)."
    except Exception as e:
        return f"Erreur marquage emails lus: {e}"


@tool
async def gmail_mark_unread(
    email_ids: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Mark emails as unread.

    Args:
        email_ids: Comma-separated email IDs (e.g. 'id1,id2,id3')
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        ids = [eid.strip() for eid in email_ids.split(",") if eid.strip()]
        if not ids:
            return "Aucun ID d'email fourni."

        service.users().messages().batchModify(
            userId="me",
            body={"ids": ids, "addLabelIds": ["UNREAD"]},
        ).execute()
        return f"{len(ids)} email(s) marqué(s) comme non lu(s)."
    except Exception as e:
        return f"Erreur marquage emails non lus: {e}"


@tool
async def gmail_create_draft(
    to: str,
    subject: str,
    body: str,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Create a draft email (not sent).

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

        draft = service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
        draft_id = draft.get("id", "?")
        return f"Brouillon créé avec succès (id: {draft_id}, destinataire: {to}, sujet: {subject})"
    except Exception as e:
        return f"Erreur création brouillon: {e}"


@tool
async def gmail_list_drafts(
    max_results: int = 10,
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List draft emails from Gmail.

    Args:
        max_results: Number of drafts to return (default 10)
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        result = service.users().drafts().list(
            userId="me", maxResults=max_results
        ).execute()
        drafts = result.get("drafts", [])

        if not drafts:
            return "Aucun brouillon trouvé."

        items = []
        for draft in drafts:
            draft_detail = service.users().drafts().get(
                userId="me", id=draft["id"], format="metadata"
            ).execute()
            msg = draft_detail.get("message", {})
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            snippet = msg.get("snippet", "")[:100]
            items.append(
                f"ID: {draft['id']}\n"
                f"À: {headers.get('To', 'Non défini')}\n"
                f"Sujet: {headers.get('Subject', 'Sans sujet')}\n"
                f"Aperçu: {snippet}"
            )

        return f"{len(items)} brouillon(s) trouvé(s):\n\n" + "\n---\n".join(items)
    except Exception as e:
        return f"Erreur liste brouillons: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Advanced Gmail tools
# ──────────────────────────────────────────────────────────────────────────────


@tool
async def gmail_batch_modify(
    message_ids_json: str,
    add_label_ids: str = "",
    remove_label_ids: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Apply label changes to many Gmail messages in a single request (up to 1000).

    Use to archive, star, mark (un)read, move to a label, unarchive, etc.
    System labels: INBOX, UNREAD, STARRED, IMPORTANT, TRASH, SPAM, SENT, DRAFT.
    Archiving = remove 'INBOX'. Marking read = remove 'UNREAD'.

    Args:
        message_ids_json: JSON array of message IDs, e.g. '["abc","def"]'.
        add_label_ids: Comma-separated labels to add (e.g. 'STARRED,Label_1234').
        remove_label_ids: Comma-separated labels to remove (e.g. 'INBOX,UNREAD').
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        message_ids = json.loads(message_ids_json)
    except json.JSONDecodeError as e:
        return f"Erreur : message_ids_json doit être un tableau JSON. Détail : {e}"
    if not isinstance(message_ids, list) or not message_ids:
        return "Erreur : fournissez au moins un ID de message."

    add_ids = [s.strip() for s in add_label_ids.split(",") if s.strip()]
    rem_ids = [s.strip() for s in remove_label_ids.split(",") if s.strip()]
    if not add_ids and not rem_ids:
        return "Erreur : fournissez au moins un label à ajouter ou à retirer."

    body: dict = {"ids": message_ids}
    if add_ids:
        body["addLabelIds"] = add_ids
    if rem_ids:
        body["removeLabelIds"] = rem_ids

    try:
        logger.info(
            "gmail_batch_modify: %d message(s) add=%s remove=%s",
            len(message_ids), add_ids, rem_ids,
        )
        # batchModify returns 204 No Content on success
        service.users().messages().batchModify(userId="me", body=body).execute()
        return (
            f"✓ {len(message_ids)} message(s) modifié(s)\n"
            f"  Labels ajoutés : {', '.join(add_ids) or '—'}\n"
            f"  Labels retirés : {', '.join(rem_ids) or '—'}"
        )
    except Exception as e:
        logger.error("gmail_batch_modify failed: %s", e)
        return f"Erreur gmail_batch_modify : {e}"


@tool
async def gmail_update_settings(
    setting: str,
    value_json: str,
    send_as_email: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Update Gmail account settings: signature, vacation responder, filters, forwarding.

    Requires the 'gmail.settings.basic' scope for most settings.

    Args:
        setting: One of:
            - 'vacation' : enable/disable auto-reply. value_json example:
                '{"enableAutoReply": true, "responseSubject": "Absent",
                  "responseBodyPlainText": "Je suis absent du...",
                  "restrictToContacts": false, "restrictToDomain": false,
                  "startTime": "1719792000000", "endTime": "1720396800000"}'
                (startTime/endTime in epoch ms, optional.)
            - 'signature' : change the signature of a send-as alias.
                Requires send_as_email. value_json example:
                '{"signature": "<p>Cordialement,<br>Franck</p>"}'
            - 'forwarding' : create a forwarding address. value_json example:
                '{"forwardingEmail": "bak@example.com"}' (then needs confirmation
                via the address receiver).
            - 'filter_create' : create a filter. value_json example:
                '{"criteria": {"from": "newsletter@x.com"},
                  "action": {"addLabelIds": ["TRASH"]}}'
        value_json: JSON body matching the setting (see above).
        send_as_email: Required for 'signature' — the sendAs email whose
            signature is modified (your main address is your Gmail).
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."

    try:
        body = json.loads(value_json)
    except json.JSONDecodeError as e:
        return f"Erreur : value_json doit être un JSON valide. Détail : {e}"

    try:
        settings = service.users().settings()
        if setting == "vacation":
            result = settings.updateVacation(userId="me", body=body).execute()
            enabled = result.get("enableAutoReply", False)
            return f"✓ Répondeur absence {'ACTIVÉ' if enabled else 'désactivé'}\n{result}"
        elif setting == "signature":
            if not send_as_email:
                return "Erreur : send_as_email requis pour modifier la signature."
            result = settings.sendAs().patch(
                userId="me", sendAsEmail=send_as_email, body=body
            ).execute()
            return f"✓ Signature mise à jour pour {send_as_email}"
        elif setting == "forwarding":
            result = settings.forwardingAddresses().create(userId="me", body=body).execute()
            return (
                f"✓ Adresse de transfert ajoutée : {result.get('forwardingEmail')}\n"
                f"  Statut : {result.get('verificationStatus')}"
            )
        elif setting == "filter_create":
            result = settings.filters().create(userId="me", body=body).execute()
            return f"✓ Filtre créé (ID : {result.get('id')})"
        else:
            return (
                "Erreur : setting inconnu. Valeurs : 'vacation', 'signature',"
                " 'forwarding', 'filter_create'."
            )
    except Exception as e:
        logger.error("gmail_update_settings failed (%s): %s", setting, e)
        return f"Erreur gmail_update_settings ({setting}) : {e}"


@tool
async def gmail_raw_api_call(
    method_path: str,
    params_json: str = "{}",
    body_json: str = "",
    user_google_credentials_json: Annotated[str, InjectedToolArg] = "",
    account: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Call ANY method of the Gmail API (v1) directly.

    Escape hatch for advanced Gmail operations: filters.list/delete,
    forwardingAddresses.list/delete, delegates.list/create, sendAs.list,
    threads.get/modify/trash, labels.update, watch/stop, etc.

    Args:
        method_path: Dot-separated Gmail API method, e.g.
            'users.messages.batchDelete', 'users.threads.modify',
            'users.settings.filters.list', 'users.settings.sendAs.list',
            'users.settings.delegates.create', 'users.labels.update',
            'users.getProfile', 'users.watch'.
        params_json: JSON object of kwargs.
            Example: '{"userId": "me", "id": "abc"}'
        body_json: Optional JSON body for POST/PATCH methods.
    """
    service = await _get_gmail_service(user_google_credentials_json)
    if not service:
        return "Google non connecté."
    return execute_raw_call(service, method_path, params_json, body_json, "gmail")
