# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/builders/system_prompt.py
# @brief      Sprint refactor nodes.py Phase 4.2 — pure builders for the
#             system-prompt segments assembled inside agent_node.
# @license    PolyForm Strict License 1.0.0
# @version    1.7.1
# =============================================================================
"""System prompt segment builders.

Pulled out of ``create_agent_node`` as a set of small pure (or near-pure)
functions. Each one targets a single segment of the system prompt :

  - ``compute_date_segment()``           → ``(date_str, date_segment)``
  - ``fetch_user_language(user_id)``     → ``(lang_directive, lang_reminder)``
  - ``LLM_INTROSPECTION_NOTE``           → bilingual IMPORTANT note
  - ``extract_email_block_addendum()``   → email/placeholder reminder block

The actual final concatenation lives in ``agent_node`` because it weaves
these segments with the cacheable / dynamic split required by Hermes
Chantier 2. Pulling the assembly itself out would force every cache-
related primitive (``_spc``, ``_frozen_mem``, ``_conv_id_fb``) into the
builder's interface — that breaks more than it cleans.
"""
from __future__ import annotations

import logging
import re
import zoneinfo
from datetime import datetime

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Date & language
# ─────────────────────────────────────────────────────────────────────────


_PARIS_TZ = zoneinfo.ZoneInfo("Europe/Paris")
_DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTHS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def compute_date_segment(now: datetime | None = None) -> tuple[str, str]:
    """Return ``(date_str, date_segment)``.

    - ``date_str`` is the human-readable French date used inside the SLM
      and compact prompts (``_SYSTEM_PROMPT_SLM.format(date_str=…)``).
    - ``date_segment`` is the full block appended to the cacheable prefix
      in the full-prompt path. Kept DYNAMIC so the prompt cache prefix
      always stops at the same byte regardless of when the turn fires.

    Parameter
    ---------
    now : datetime | None
        Defaults to ``datetime.now(Europe/Paris)``. Injectable for tests.
    """
    if now is None:
        now = datetime.now(_PARIS_TZ)
    date_str = (
        f"{_DAYS_FR[now.weekday()]} {now.day} {_MONTHS_FR[now.month]} "
        f"{now.year}, {now.strftime('%H:%M')}"
    )
    date_segment = (
        f"\n\n📅 Date et heure actuelles : {date_str} (Europe/Paris)\n"
        "Utilise toujours le fuseau Europe/Paris pour les dates et heures.\n"
    )
    return date_str, date_segment


async def fetch_user_language(user_id: str) -> tuple[str, str, str]:
    """Return ``(language_code, lang_directive, lang_reminder)``.

    Reads ``users.language`` for the given user. Defaults to "fr" on any
    failure (missing row, DB blip, empty user_id).

    - ``language_code`` is "fr" or "en" — useful for logging.
    - ``lang_directive`` is prepended to the system prompt (primacy).
    - ``lang_reminder`` is appended at the tail (recency, sandwich pattern).
    """
    lang = "fr"
    if user_id:
        try:
            from sqlalchemy import select as _select

            from app.database import async_session as _async_session
            from app.models.user import User as _U
            async with _async_session() as _db:
                _row = await _db.execute(
                    _select(_U.language).where(_U.id == user_id)
                )
                lang = (_row.scalar_one_or_none() or "fr")
        except Exception:
            pass
    if lang == "en":
        return (
            "en",
            "REPLY LANGUAGE = English. Translate any tool output.\n\n",
            "\n\n[reply in English]",
        )
    return (
        "fr",
        "LANGUE DE RÉPONSE = Français. Traduis si besoin.\n\n",
        "\n\n[réponds en français]",
    )


# ─────────────────────────────────────────────────────────────────────────
# IMPORTANT note (bilingual)
# ─────────────────────────────────────────────────────────────────────────


LLM_INTROSPECTION_NOTE: str = (
    "\n\nIMPORTANT : if the user asks which LLM/model/provider "
    "you are using, you MUST call `system_check_llm_providers` "
    "before answering. Never answer from your training memory.\n"
    "Si l'utilisateur te demande quel LLM/modèle/fournisseur tu "
    "utilises, tu DOIS appeler `system_check_llm_providers` "
    "avant de répondre. Ne réponds jamais depuis ta mémoire.\n"
)


# ─────────────────────────────────────────────────────────────────────────
# Email / placeholder addendum (audit 2026-05-07)
# ─────────────────────────────────────────────────────────────────────────


_EMAIL_PAT = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PLACEHOLDER_PAT = re.compile(r"\[EMAIL_\d+\]")


def extract_email_block_addendum(sanitized_messages: list, *, window: int = 12) -> str:
    """Scan the last ``window`` messages of the conversation and return a
    sticky « EMAILS DÉJÀ FOURNIS » block to append to the system prompt.

    Returns an empty string when no email / placeholder is found in the
    window. The block lives OUTSIDE the cacheable segment (it's dynamic,
    grows per turn).

    Background
    ----------
    Weak models (Ministral 3 8B observed) keep asking for an email already
    given earlier in the conversation. The PII filter has already replaced
    raw addresses with ``[EMAIL_N]`` placeholders ; we look for both
    shapes so the prompt teaches the model that : (a) the address is
    known, (b) the placeholder should be used as-is in tool args, and
    (c) ``contacts_search`` is not needed.
    """
    try:
        seen_addrs: list[str] = []
        seen_placeholders: list[str] = []
        for _m in sanitized_messages[-window:]:
            _content = getattr(_m, "content", None)
            if _content is None and isinstance(_m, dict):
                _content = _m.get("content")
            if not isinstance(_content, str):
                continue
            for _addr in _EMAIL_PAT.findall(_content):
                if _addr not in seen_addrs:
                    seen_addrs.append(_addr)
            for _ph in _PLACEHOLDER_PAT.findall(_content):
                if _ph not in seen_placeholders:
                    seen_placeholders.append(_ph)
        if not (seen_addrs or seen_placeholders):
            return ""
        parts = ["\n\n📧 ADRESSES EMAIL DÉJÀ FOURNIES PAR L'UTILISATEUR :\n"]
        if seen_addrs:
            parts.append("\n".join(f"- {a}" for a in seen_addrs[:10]) + "\n")
        if seen_placeholders:
            parts.append(
                "Placeholders (anonymisation PII active) : "
                + ", ".join(seen_placeholders[:10])
                + "\n"
                "→ Ces placeholders représentent de VRAIES adresses fournies par "
                "l'utilisateur. Utilise-les TELS QUELS comme paramètre ``to`` des "
                "outils gmail (ex: ``gmail_send_email(to='[EMAIL_0]', ...)``). "
                "Le backend remplace automatiquement le placeholder par la vraie "
                "adresse au moment de l'appel.\n"
            )
        parts.append(
            "→ NE redemande PAS l'adresse à l'utilisateur, NE la cherche PAS dans "
            "contacts_search — elle est déjà fournie."
        )
        return "".join(parts)
    except Exception as _ext_exc:
        logger.debug("email extraction skipped: %s", _ext_exc)
        return ""
