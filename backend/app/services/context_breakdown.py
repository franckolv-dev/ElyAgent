# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/context_breakdown.py
# @brief      P2 — d'où viennent les tokens d'un tour. Port de Hermes v0.19.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
#
# Portage de `agent/context_breakdown.py` (hermes-agent v0.19.0,
# Nous Research, licence MIT) — voir `docs_internes/analyse_hermes_v019.md`.
# =============================================================================
"""Ventilation du contexte d'un tour.

**Le besoin, mesuré sur la production le 25/07** — tokens d'ENTRÉE moyens par
tour sur 7 jours glissants :

    desktop_search_files ... 230 203
    browser_navigate ....... 175 232
    pdf_read ............... 141 867
    find_tool ...............  80 041  (× 14 = 1,12 M au total)

Impossible de dire d'où ils venaient : schémas d'outils re-envoyés à chaque
itération ? historique de conversation ? un seul résultat d'outil énorme ?
Sans cette réponse, toute optimisation du contexte est un pari — et c'est
pour ça que cette ventilation vient AVANT la compression (P1).

**Le principe porté de Hermes, et il compte.** Leur module utilise `chars/4`
*parce que c'est l'estimateur qui pilote leur seuil de compression* : la
ventilation doit parler la même langue que le mécanisme qui décide de
tronquer, sinon elle décrit un contexte que le système ne voit pas. Ely a son
propre estimateur (``context_manager.estimate_tokens``, `chars/3.5`) — c'est
donc lui qu'on utilise. Porter la constante plutôt que le principe donnerait
des chiffres ne correspondant à aucune décision réelle.

**Catégories, adaptées.** Hermes sépare `rules` (leur bloc de règles) et
détecte le MCP au préfixe `mcp_` ; Ely n'a pas ce bloc et utilise `mcp__`.
Leur outil de délégation s'appelle `delegate_task`, celui d'Ely `delegate`.

C'est un **instrument de mesure** : il ne doit jamais coûter un tour à
l'utilisateur, donc il n'échoue pas — il rend des zéros.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# Porte la ventilation du dernier tour depuis le nœud agent (qui la calcule)
# jusqu'au point de journalisation (qui l'écrit). Même patron que
# SOVEREIGNTY_STRICT / CORRELATION_ID : par tâche asyncio, donc pas de fuite
# entre deux conversations concurrentes.
LAST_CONTEXT_BREAKDOWN: ContextVar[str | None] = ContextVar(
    "last_context_breakdown", default=None
)

# Bloc des playbooks injectés dans le prompt (``format_active_skills_block``).
_SKILLS_OPEN = "<learned_skills>"
_SKILLS_CLOSE = "</learned_skills>"

# Outils de délégation : comptés à part, leur schéma est gros et leur usage rare.
_SUBAGENT_TOOL_NAMES: frozenset[str] = frozenset({"delegate"})

_LABELS: dict[str, str] = {
    "system_prompt": "Prompt système",
    "tool_definitions": "Schémas d'outils",
    "mcp": "Outils MCP",
    "subagent_definitions": "Délégation",
    "skills": "Playbooks appris",
    "conversation": "Conversation",
}


def _tokens(text: str) -> int:
    """Estimation alignée sur celle qui pilote les troncatures d'Ely."""
    if not text:
        return 0
    try:
        from app.services.context_manager import estimate_tokens
        return estimate_tokens(text)
    except Exception:  # noqa: BLE001 — un instrument ne casse rien
        return max(1, len(text) // 4)


def _tool_text(tool: Any) -> str:
    """Le texte qu'un outil coûte réellement : son nom + son schéma."""
    name = str(getattr(tool, "name", "") or "")
    description = str(getattr(tool, "description", "") or "")
    schema = ""
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool
        schema = json.dumps(convert_to_openai_tool(tool), ensure_ascii=False)
    except Exception:  # noqa: BLE001 — outil exotique : on retombe sur le texte
        schema = ""
    return schema or f"{name} {description}"


def _split_tools(tools: Sequence[Any] | None) -> tuple[list, list, list]:
    """Natifs / MCP / délégation — la ventilation qui permet d'arbitrer."""
    native: list = []
    mcp: list = []
    subagent: list = []
    for tool in tools or []:
        name = str(getattr(tool, "name", "") or "")
        if name.startswith("mcp__"):
            mcp.append(tool)
        elif name in _SUBAGENT_TOOL_NAMES:
            subagent.append(tool)
        else:
            native.append(tool)
    return native, mcp, subagent


def _message_text(message: Any) -> str:
    if message is None:
        return ""
    content = (
        message.get("content") if isinstance(message, dict)
        else getattr(message, "content", "")
    )
    if isinstance(content, list):
        # Tier codex (Responses API) : content en liste de blocs.
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content or "")


def _extract_skills_block(system_prompt: str) -> tuple[str, str]:
    """Sépare le bloc ``<learned_skills>`` du reste du prompt.

    Sans cette séparation, le coût des playbooks serait noyé dans celui du
    prompt — or c'est précisément l'arbitrage qu'on veut pouvoir faire.
    """
    start = system_prompt.find(_SKILLS_OPEN)
    if start == -1:
        return system_prompt, ""
    end = system_prompt.find(_SKILLS_CLOSE, start)
    if end == -1:
        return system_prompt, ""
    end += len(_SKILLS_CLOSE)
    return (system_prompt[:start] + system_prompt[end:]).strip(), system_prompt[start:end]


def compute_context_breakdown(
    *,
    system_prompt: str = "",
    tools: Sequence[Any] | None = None,
    messages: Sequence[Any] | None = None,
    model: str = "",
) -> dict[str, Any]:
    """Décompose ce que pèse la prochaine requête, par catégorie.

    Les catégories à zéro sont retirées — une ventilation lisible ne liste
    pas ce qui ne coûte rien.
    """
    try:
        prompt_rest, skills_block = _extract_skills_block(str(system_prompt or ""))
        native, mcp, subagent = _split_tools(tools)

        conversation = 0
        if isinstance(messages, (list, tuple)):
            conversation = sum(_tokens(_message_text(m)) for m in messages)

        counted = [
            ("system_prompt", _tokens(prompt_rest)),
            ("tool_definitions", sum(_tokens(_tool_text(t)) for t in native)),
            ("mcp", sum(_tokens(_tool_text(t)) for t in mcp)),
            ("subagent_definitions", sum(_tokens(_tool_text(t)) for t in subagent)),
            ("skills", _tokens(skills_block)),
            ("conversation", conversation),
        ]
        total = sum(tokens for _, tokens in counted)

        context_max = 0
        if model:
            try:
                from app.services.context_manager import get_context_window
                context_max = int(get_context_window(model) or 0)
            except Exception as exc:  # noqa: BLE001
                logger.debug("fenêtre de contexte inconnue pour %s: %s", model, exc)

        percent = (
            max(0, min(100, round(total / context_max * 100))) if context_max else 0
        )

        return {
            "categories": [
                {"id": cid, "label": _LABELS.get(cid, cid), "tokens": tokens}
                for cid, tokens in counted
                if tokens > 0
            ],
            "estimated_total": total,
            "context_max": context_max,
            "context_percent": percent,
            "model": model,
        }
    except Exception as exc:  # noqa: BLE001 — instrument de mesure
        logger.debug("context_breakdown indisponible: %s", exc)
        return {
            "categories": [], "estimated_total": 0,
            "context_max": 0, "context_percent": 0, "model": model,
        }


def compact_breakdown(result: dict[str, Any] | None) -> str | None:
    """Forme compacte destinée à ``usage_logs.context_breakdown``.

    JSON plat et stable, interrogeable en SQL sans parser du texte libre —
    c'est ce qui permettra de répondre à « ces 230 000 tokens, ils venaient
    d'où ? » sur du trafic réel plutôt que sur un banc.

    Rend ``None`` quand il n'y a rien à dire : mieux vaut une colonne vide
    qu'un JSON vide qui donnerait l'illusion d'une mesure.
    """
    if not result:
        return None
    categories = result.get("categories") or []
    if not categories:
        return None
    payload: dict[str, Any] = {c["id"]: c["tokens"] for c in categories}
    payload["total"] = result.get("estimated_total", 0)
    if result.get("context_percent"):
        payload["pct"] = result["context_percent"]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
