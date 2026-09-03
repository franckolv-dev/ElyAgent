# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/compact_prompt.py
# @brief      Compact system prompt for small local LLMs (LM Studio, Ollama)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Compact prompt mode for small local LLMs.

Rationale (2026-04-24):
The historical ELY sub-agent system prompts are 2000-3000 tokens
(identity + 20+ behavioral rules + tool routing hints + user profile
extended + active memories + past interactions + constraints + date).
Coupled with 76 tool schemas → 10 000-15 000 tokens per request.

Frontier models (Claude/GPT-4/Gemini Pro) navigate this richness well
and know when to tool-call vs text-respond. Small local models
(Qwen 2.5-VL 7B, Qwen 3, Gemma 9B…) read the literal instruction
"Rédige TOUJOURS en texte naturel" and respond in text even when a tool
would be the right answer. The signal-to-noise ratio is too low.

This module produces a drastically shorter system prompt (~300 tokens)
that puts the tool-calling priority FIRST and keeps only the strict
identity minimum. It is used ONLY for local OpenAI-compatible LLMs
(detected via `is_local_openai_llm()`); frontier cloud models keep
their full prompt.
"""
from __future__ import annotations

from typing import Iterable


# One-line core identity — replaces the 3-paragraph _IDENTITY block.
_CORE_IDENTITY = (
    'Tu es Ely (prononcé "Éli"), assistante IA personnelle féminine. '
    "Tu parles toujours de toi au féminin. "
    "Ton prénom s'écrit Ely (sans accent) — si on t'appelle Ely, Éli ou ely c'est toi, ne corrige jamais."
)

# Domain-specific compact specialties. We keep the tool-calling priority
# FIRST so the model reads it before any textual guidance.
_AGENT_COMPACT_SPECIALTIES: dict[str, str] = {
    "workspace": (
        "Tu gères Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts. "
        "Pour toute action demandée, APPELLE directement le tool correspondant."
    ),
    "research": (
        "Tu fais des recherches web, YouTube, Maps, météo, traductions. "
        "APPELLE directement le tool adapté à la demande."
    ),
    "memory": (
        "Tu gères les notes locales, préférences utilisateur et la base de connaissances. "
        "APPELLE directement le tool adapté (notes_*, knowledge_*, save_user_preference)."
    ),
    "infra": (
        "Tu exécutes des commandes SSH, supervises des serveurs, "
        "surveilles des sites. APPELLE directement le tool adapté."
    ),
    "creative": (
        "Tu génères des images, QR codes, serveurs MCP, et exécutes du code Python. "
        "APPELLE directement le tool adapté."
    ),
    "general": (
        "Pour toute demande qui correspond à un tool disponible, "
        "APPELLE directement le tool. Sinon, réponds en texte court."
    ),
}

_TOOL_PRIORITY = (
    "PRIORITÉ ABSOLUE : si la demande correspond à un tool disponible, "
    "appelle-le IMMÉDIATEMENT via function calling natif. Tool call > texte.\n"
    "\n"
    "❌ JAMAIS — ces 3 patterns sont STRICTEMENT INTERDITS :\n"
    '  1. Sortir un tool call comme du texte JSON : `[{"name":"x","arguments":{}}]`\n'
    "  2. Écrire du code Python qui simule un tool : `print(tool_name(...))`\n"
    "  3. Annoncer en texte ce que tu vas faire : « Je vais utiliser X »\n"
    "✅ TOUJOURS — utilise le mécanisme function calling natif (tool_calls field).\n"
    "\n"
    "❌ JAMAIS de faux succès : ne dis PAS « supprimé », « envoyé », « créé », "
    "« OK » si le tool n'a PAS retourné un succès explicite. Si la réponse "
    "contient « erreur », « error », un exception, ou est vide → DIS-le et "
    "propose une correction. JAMAIS prétendre qu'une action est faite si elle "
    "ne l'est pas.\n"
    "\n"
    "🔀 EN CAS D'AMBIGUÏTÉ : si la demande pourrait relever d'un autre domaine "
    "(ex. « messages dans répertoire X » = Gmail OU dossier local ?), POSE UNE "
    "question de clarification courte. INTERDICTION ABSOLUE de répondre "
    "« je n'ai pas la capacité » ou « je suis un agent X spécialisé » — ces "
    "phrases sont des refus paresseux. Pose la question, l'utilisateur répondra "
    "et tu sauras quel tool utiliser au tour suivant.\n"
    "\n"
    "Réponds en texte UNIQUEMENT quand aucun tool ne convient."
)


def build_compact_system_prompt(
    agent_name: str,
    date_str: str,
    user_ctx: str = "",
    memories: Iterable[str] | None = None,
    constraints: Iterable[str] | None = None,
) -> str:
    """Build a compact (<500 tokens) system prompt for small local LLMs.

    Structure:
      1. Identity (one line)
      2. Agent speciality (one line)
      3. Tool-calling priority directive (paragraph)
      4. Compact user context (single-line or empty)
      5. Top-3 memories (truncated to 100 chars each) — ONLY if present
      6. Top-3 constraints (truncated) — ONLY if present
      7. Date (last line, most volatile → preserves cache prefix)

    The structure puts IMMUTABLE sections (1, 2, 3) first so LM Studio's
    prefix cache can retain them across turns, and volatile data (user
    context, memories, date) at the end where invalidation affects only
    the trailing tokens.
    """
    parts: list[str] = [_CORE_IDENTITY]

    speciality = _AGENT_COMPACT_SPECIALTIES.get(agent_name, _AGENT_COMPACT_SPECIALTIES["general"])
    parts.append(speciality)

    parts.append(_TOOL_PRIORITY)

    # Compact user context (already <800 chars from get_user_context(compact=True))
    if user_ctx:
        parts.append(user_ctx)

    # Top-3 constraints only, truncated
    if constraints:
        top_c = list(constraints)[:3]
        if top_c:
            c_block = " ; ".join(c[:120] for c in top_c)
            parts.append(f"Contraintes actives : {c_block}")

    # Top-3 memories only, truncated to keep prompt lean
    if memories:
        top_m = list(memories)[:3]
        if top_m:
            m_block = " ; ".join(m[:100] for m in top_m)
            parts.append(f"Mémoires : {m_block}")

    # Date at the END (most volatile — minute-level changes shouldn't
    # invalidate the whole prefix cache)
    parts.append(f"Date : {date_str} (Europe/Paris).")

    return "\n\n".join(parts)
