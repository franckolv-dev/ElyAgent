# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/hitl_descriptions.py
# @brief      Human-readable HITL descriptions with impact estimate + mismatch detection.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Human-readable HITL descriptions.

Goal : when the system asks the user « do you approve this action? », the
user must be able to VERIFY that the args match their intent — not just
blindly click ✅ on a JSON blob.

The May 2026 Temu incident showed why this matters : Franck asked « delete
Temu purchases », received a HITL prompt that just said
`gmail_trash_by_category({"category":"purchases"})`, validated trusting it
matched, and 100+ non-Temu purchases got trashed because the LLM had
silently dropped the « from sender Temu » filter.

This module produces messages that :
  1. Translate the technical tool call into plain French/English
  2. Pre-count the affected items when possible (Gmail messages.list)
  3. Echo the user's original request for visual diff
  4. Highlight obvious mismatches (sender mentioned but no `from_sender` arg)
  5. Emit ⚠️ warnings when filters are missing on destructive batch ops
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Hidden / injected args we never want to display in the HITL message.
_HIDDEN_ARGS = {"user_google_credentials_json", "user_id", "account"}

# Common sender brands users frequently mention by name. If found in the
# user request without a corresponding `from_sender` arg → mismatch warning.
_KNOWN_SENDERS = {
    "temu", "amazon", "facebook", "linkedin", "twitter", "instagram",
    "google", "youtube", "spotify", "netflix", "uber", "deliveroo",
    "bookingcom", "booking", "airbnb", "ebay", "cdiscount", "fnac",
    "lidl", "aldi", "carrefour", "leclerc", "auchan", "intermarché",
    "shein", "aliexpress", "wish", "zalando", "asos",
    "free", "orange", "sfr", "bouygues",
    "edf", "engie", "total",
    "bnp", "lcl", "ca", "credit agricole", "boursorama", "n26", "revolut",
}


async def _count_gmail_query(creds_json: str, query: str, hard_cap: int = 500) -> int | str:
    """Best-effort count of Gmail messages matching a query.

    Returns a count integer, or ``'?'`` if the count couldn't be obtained
    (no creds, network error, etc.). Capped at `hard_cap` to keep the
    pre-check cheap — if we hit the cap we return e.g. ``'500+'``.
    """
    if not creds_json:
        return "?"
    try:
        from app.agent.tools.gmail_tool import _get_gmail_service
        service = await _get_gmail_service(creds_json)
        if service is None:
            return "?"
        # Single page with resultSizeEstimate is the cheapest. But Gmail's
        # estimate is sometimes inaccurate (especially low) — paginate up
        # to hard_cap for an exact count, then declare "hard_cap+" if we
        # still have a nextPageToken.
        total = 0
        page_token = None
        while total < hard_cap:
            req = service.users().messages().list(
                userId="me",
                maxResults=min(100, hard_cap - total),
                q=query,
                pageToken=page_token,
            ).execute()
            batch = req.get("messages", []) or []
            total += len(batch)
            page_token = req.get("nextPageToken")
            if not page_token or not batch:
                return total
        # Hit the cap, more available
        return f"{hard_cap}+"
    except Exception as exc:
        logger.debug("Gmail count failed for query=%r: %s", query, exc)
        return "?"


def _detect_arg_mismatches(user_request: str, args: dict) -> list[str]:
    """Spot user-mentioned filters that are missing from the tool args.

    Returns a list of ⚠️ warnings to surface in the HITL message. Empty
    list = the args look consistent with the request.
    """
    warnings: list[str] = []
    if not user_request:
        return warnings
    text = user_request.lower()

    # Sender mentioned by name but no `from_sender` arg
    sender_arg = (args.get("from_sender") or "").lower()
    for sender in _KNOWN_SENDERS:
        if sender in text and sender not in sender_arg and not sender_arg:
            warnings.append(
                f"Tu mentionnes « {sender} » mais le filtre `from_sender` "
                f"n'est PAS appliqué — tous les expéditeurs seront ciblés."
            )
            break  # one warning is enough, don't spam

    # Subject keyword mentioned but no subject_contains
    subject_keywords = ["sujet", "objet", "titre", "subject"]
    if any(k in text for k in subject_keywords):
        if not args.get("subject_contains"):
            warnings.append(
                "Tu mentionnes un sujet mais le filtre `subject_contains` "
                "n'est pas appliqué."
            )

    # Date range mentioned but no after/before
    date_keywords = ["avant", "après", "apres", "depuis", "datant", "older", "newer", "before", "after"]
    if any(k in text for k in date_keywords):
        if not args.get("after_date") and not args.get("before_date"):
            # Only warn if the tool supports those fields
            warnings.append(
                "Tu mentionnes une période mais aucun filtre de date "
                "(`after_date`/`before_date`) n'est appliqué."
            )

    return warnings


# ── Tool-specific renderers ──────────────────────────────────────────────────

def _build_query_for_trash_by_category(args: dict) -> str:
    """Reconstruct the Gmail query from gmail_trash_by_category args.

    Mirrors the logic in gmail_tool.py:gmail_trash_by_category so we can
    pre-count BEFORE the tool runs. If the tool changes its query
    construction, this needs to follow.
    """
    from app.agent.tools.gmail_tool import _CLEANUP_QUERIES, _resolve_cleanup_category
    canonical = _resolve_cleanup_category(args.get("category", ""))
    if canonical is None:
        return ""
    parts = [f"({_CLEANUP_QUERIES[canonical]})"]
    if (s := (args.get("from_sender") or "").strip()):
        if " " in s:
            s = f'"{s}"'
        parts.append(f"from:{s}")
    if (s := (args.get("subject_contains") or "").strip()):
        if " " in s:
            s = f'"{s}"'
        parts.append(f"subject:{s}")
    if (s := (args.get("after_date") or "").strip()):
        parts.append(f"after:{s}")
    if (s := (args.get("before_date") or "").strip()):
        parts.append(f"before:{s}")
    return " ".join(parts)


async def _render_gmail_trash_by_category(args: dict, creds: str, user_request: str) -> str:
    cat = args.get("category", "?")
    sender = (args.get("from_sender") or "").strip()
    subject = (args.get("subject_contains") or "").strip()
    after = (args.get("after_date") or "").strip()
    before = (args.get("before_date") or "").strip()
    max_r = args.get("max_results", 100)

    query = _build_query_for_trash_by_category(args)
    count = await _count_gmail_query(creds, query) if query else "?"

    lines = [
        "🗑️ **SUPPRESSION GMAIL EN LOT**",
        "",
        f"📂 Catégorie : `{cat}`",
    ]
    filters = []
    if sender:
        filters.append(f"expéditeur ≈ « {sender} »")
    if subject:
        filters.append(f"sujet contient « {subject} »")
    if after:
        filters.append(f"après {after}")
    if before:
        filters.append(f"avant {before}")
    if filters:
        lines.append("🔍 Filtres : " + " + ".join(filters))
    else:
        lines.append("🔍 Filtres : **AUCUN** — toute la catégorie sera ciblée")

    lines.append(f"📊 **Impact estimé : {count} email(s)** seront déplacés en corbeille (limite {max_r}/appel)")
    lines.append(f"🔧 Query Gmail : `{query}`")

    if user_request:
        lines.append("")
        lines.append(f"💬 Ta demande : « {user_request[:300]} »")
        warnings = _detect_arg_mismatches(user_request, args)
        if warnings:
            lines.append("")
            lines.append("⚠️ **ATTENTION — incohérence possible** :")
            for w in warnings:
                lines.append(f"   • {w}")
            lines.append("")
            lines.append("👉 Si ce n'est PAS ce que tu voulais, REFUSE et reformule.")

    return "\n".join(lines)


async def _render_gmail_trash_by_query(args: dict, creds: str, user_request: str) -> str:
    query = (args.get("query") or "").strip()
    max_r = args.get("max_results", 100)
    count = await _count_gmail_query(creds, query) if query else "?"

    lines = [
        "🗑️ **SUPPRESSION GMAIL — query libre**",
        "",
        f"🔧 Query Gmail : `{query}`",
        f"📊 **Impact estimé : {count} email(s)** seront déplacés en corbeille (limite {max_r}/appel)",
    ]
    if user_request:
        lines.append("")
        lines.append(f"💬 Ta demande : « {user_request[:300]} »")
    return "\n".join(lines)


async def _render_gmail_trash_emails(args: dict, creds: str, user_request: str) -> str:
    ids = args.get("email_ids", [])
    n = len(ids) if isinstance(ids, list) else "?"
    lines = [
        "🗑️ **SUPPRESSION GMAIL — IDs explicites**",
        "",
        f"📊 **{n} email(s)** seront déplacés en corbeille",
    ]
    if isinstance(ids, list) and ids:
        sample = ", ".join(str(i)[:16] for i in ids[:5])
        more = f" (et {len(ids) - 5} autres)" if len(ids) > 5 else ""
        lines.append(f"🆔 IDs : {sample}{more}")
    if user_request:
        lines.append("")
        lines.append(f"💬 Ta demande : « {user_request[:300]} »")
    return "\n".join(lines)


async def _render_gmail_send_email(args: dict, _creds: str, user_request: str) -> str:
    to = args.get("to", "?")
    subject = args.get("subject", "(sans sujet)")
    body = (args.get("body", "") or "")[:300]
    lines = [
        "📧 **ENVOI D'EMAIL**",
        "",
        f"📨 À : {to}",
        f"📝 Sujet : {subject}",
        f"📄 Corps (extrait) : {body}",
    ]
    if user_request:
        lines.append("")
        lines.append(f"💬 Ta demande : « {user_request[:300]} »")
    return "\n".join(lines)


# Map tool name → renderer
_RENDERERS = {
    "gmail_trash_by_category": _render_gmail_trash_by_category,
    "gmail_trash_by_query":    _render_gmail_trash_by_query,
    "gmail_trash_emails":      _render_gmail_trash_emails,
    "gmail_send_email":        _render_gmail_send_email,
    "gmail_reply_email":       _render_gmail_send_email,
    "gmail_send_with_attachment": _render_gmail_send_email,
}


async def build_human_hitl_description(
    tool_name: str,
    args: dict,
    user_request: str = "",
    user_credentials_json: str = "",
) -> str:
    """Public entry point — return a human-readable HITL message.

    Falls back to the legacy technical format if the tool has no specific
    renderer registered.
    """
    visible_args = {k: v for k, v in args.items() if k not in _HIDDEN_ARGS}
    renderer = _RENDERERS.get(tool_name)
    if renderer is not None:
        try:
            return await renderer(visible_args, user_credentials_json, user_request)
        except Exception as exc:
            logger.warning("HITL renderer for %s failed: %s — falling back to JSON", tool_name, exc)
    # Generic fallback — keep technical but at least include the user request
    body = f"Outil : `{tool_name}`\nArguments : {json.dumps(visible_args, ensure_ascii=False)}"
    if user_request:
        body += f"\n\n💬 Ta demande : « {user_request[:300]} »"
    return body
