# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/usage_instrumentation.py
# @brief      V2-1 — attribuer chaque tour à son architecture d'agent, et en
#             extraire le coût réel. Socle du banc A/B de la vague 2.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Attribution et coût d'un tour d'agent.

Trois architectures cohabitent en production, et rien ne disait laquelle
avait servi un tour donné :

- **mono-agent** — le chat web passe un ``toolset_profile``, ce qui
  court-circuite le routeur (``supervisor.py``) : un seul nœud, ~80 outils ;
- **sous-agents** — les canaux et la voix ne passent pas ce champ, le routeur
  s'exécute et la demande part vers un spécialiste (de 15 à 90 outils selon
  le domaine — ``workspace`` est plus lourd que le mono-agent entier) ;
- **graphe plat** — les tâches planifiées (``automated_task=True``), soit la
  population la plus nombreuse en base (815 conversations).

Le domaine compte autant que la famille : mesurer « sous-agents » en bloc
mélangerait ``data`` (4 359 tokens de schémas) et ``workspace`` (20 487).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ARCH_MONO = "mono"
ARCH_FLAT = "flat"
ARCH_UNKNOWN = "unknown"
ARCH_SUB_AGENT_PREFIX = "sub_agent:"


def architecture_label(
    *,
    toolset_profile: str | None = None,
    automated_task: bool = False,
    domain: str | None = None,
) -> str:
    """Nom de l'architecture qui a réellement servi ce tour.

    Ordre de priorité — il reproduit celui du code, pas une préférence :

    1. ``automated_task`` gagne : le scheduler force ``build_simple_agent_graph``
       quel que soit le reste de l'état.
    2. ``toolset_profile`` non vide → le routeur est court-circuité (mono).
    3. sinon, le domaine routé identifie le spécialiste.

    Ne devine jamais : un tour non attribuable rend ``"unknown"`` et se voit
    dans les chiffres, au lieu de gonfler silencieusement une des familles.
    """
    if automated_task:
        return ARCH_FLAT
    if toolset_profile:
        return ARCH_MONO
    if domain:
        return f"{ARCH_SUB_AGENT_PREFIX}{domain}"
    return ARCH_UNKNOWN


def usage_from_result(result: Any) -> dict:
    """Coût d'un tour, extrait d'un résultat ``ainvoke`` bufferisé.

    Les surfaces bufferisées (canaux, voix) n'ont pas le flux d'événements
    du chat web : leur seule source est ``usage_metadata`` porté par chaque
    message du modèle. On les somme — un tour outillé enchaîne plusieurs
    appels, et le coût du tour est leur total, pas celui du dernier.

    ``has_metadata`` distingue « le tour a coûté zéro token » (impossible) de
    « le fournisseur n'a rien renvoyé » (fréquent avec LM Studio). Sans cette
    nuance, un local silencieux passerait pour gratuit dans le banc.

    Ne lève jamais : l'instrumentation ne doit pas casser une réponse.
    """
    out = {
        "input_tokens": 0,
        "output_tokens": 0,
        "has_metadata": False,
        "cached_input_tokens": 0,
        "cache_creation_tokens": 0,
        "domain": None,
        "tools_called": [],
    }
    try:
        if not isinstance(result, dict):
            return out
        out["domain"] = result.get("domain") or None
        for msg in result.get("messages") or []:
            um = getattr(msg, "usage_metadata", None)
            if not um:
                continue
            out["has_metadata"] = True
            out["input_tokens"] += int(um.get("input_tokens", 0) or 0)
            out["output_tokens"] += int(um.get("output_tokens", 0) or 0)
            # Cache de préfixe : la donnée était déjà là, on la jetait.
            # `input_token_details` est le champ standard de LangChain ;
            # les fournisseurs qui ne le remontent pas laissent zéro, ce qui
            # doit se lire « non rapporté » et non « échec de cache ».
            details = um.get("input_token_details") or {}
            if isinstance(details, dict):
                for key, slot in (("cache_read", "cached_input_tokens"),
                                  ("cache_creation", "cache_creation_tokens")):
                    try:
                        out[slot] += int(details.get(key, 0) or 0)
                    except (TypeError, ValueError):
                        pass
        for msg in result.get("messages") or []:
            for call in getattr(msg, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                if name:
                    out["tools_called"].append(name)
    except Exception as exc:  # noqa: BLE001 — l'instrumentation ne casse rien
        logger.debug("usage_from_result: extraction partielle (%s)", exc)
    return out


def dominant_tool(tools_called: list[str]) -> str | None:
    """Outil le plus appelé du tour (départage : le premier vu)."""
    if not tools_called:
        return None
    return max(set(tools_called), key=tools_called.count)


def split_model_used(model_used: str | None) -> tuple[str, str]:
    """``"llm:<provider>/<model>+tools"`` → ``(provider, model)``.

    Même découpage que `chat.py`, extrait ici pour que les canaux n'aient pas
    à le recopier — trois copies auraient dérivé.
    """
    raw = (model_used or "").strip()
    if not raw:
        return "unknown", "unknown"
    stripped = raw.split("+", 1)[0]
    parts = stripped.split(":", 1)
    kind = parts[0]
    rest = parts[1] if len(parts) > 1 else raw
    if "/" in rest:
        provider, model = rest.split("/", 1)
        return provider, model
    return ("ollama" if kind == "slm" else "unknown"), rest


def _last_context_breakdown() -> str | None:
    """Ventilation du contexte du tour, posée par le nœud agent (P2)."""
    try:
        from app.services.context_breakdown import LAST_CONTEXT_BREAKDOWN
        return LAST_CONTEXT_BREAKDOWN.get()
    except Exception:  # noqa: BLE001
        return None


async def record_turn_usage(
    *,
    user_id: str,
    conversation_id: str | None,
    channel: str,
    result: Any,
    started_at: float,
    toolset_profile: str | None = None,
    automated_task: bool = False,
) -> None:
    """Enregistre coût + latence + architecture d'un tour **bufferisé**.

    Pensé pour les surfaces sans flux d'événements (Telegram, Slack, Discord),
    qui n'écrivaient jusqu'ici **aucune ligne d'usage** — l'architecture à
    sous-agents était donc totalement invisible dans les chiffres.

    ``started_at`` est un ``time.monotonic()`` pris avant l'invocation.
    Best-effort : l'analytique ne casse jamais une réponse déjà produite.
    """
    import time

    try:
        from app.services.analytics_service import log_usage

        usage = usage_from_result(result)
        provider, model = split_model_used(
            (result or {}).get("model_used") if isinstance(result, dict) else None
        )
        await log_usage(
            user_id=user_id,
            model=model,
            provider=provider,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            # Cache de préfixe : calculer ne suffit pas, il faut livrer
            # (leçon de #255, où la ventilation restait dans le nœud).
            cached_input_tokens=usage.get("cached_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_tokens", 0),
            conversation_id=conversation_id,
            skill_used=dominant_tool(usage["tools_called"]),
            channel=channel,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            architecture=architecture_label(
                toolset_profile=toolset_profile,
                automated_task=automated_task,
                domain=usage["domain"],
            ),
            context_breakdown=_last_context_breakdown(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_turn_usage (%s) échoué : %s", channel, exc)
