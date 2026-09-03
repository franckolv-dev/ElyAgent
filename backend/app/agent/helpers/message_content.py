# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/helpers/message_content.py
# @brief      content_to_text() — aplatit le ``content`` d'un message LangChain
#             (str | list[str|dict] | dict) en texte plat.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Normalise le ``content`` d'un ``AIMessage`` LangChain en string plate.

LangChain type ce champ ``Union[str, List[Union[str, Dict]]]`` : la plupart
des providers renvoient une string, mais certains renvoient une LISTE de
blocs typés ``[{"type": "text", "text": "..."}, ...]`` (voire un dict seul) :

  - LM Studio (Ministral 3B, audit 2026-05-15) ;
  - Anthropic en reasoning étendu ; Gemini multimodal ;
  - **OpenAI Responses API / openai-codex** avec ``output_version="v0"``
    (juin 2026) → ``[{"type": "text", "text": "...", "index": 0}]``.

Tout code qui suppose une string casse alors de deux façons :
  - ``content.strip()`` / ``json.loads(content)`` → ``'list' object has
    no attribute 'strip'`` (parse échoué → fallback dégradé) ;
  - ``content[:2000]`` persisté en colonne SQL String → la *liste tronquée*
    arrive au driver → ``Error binding parameter N: type 'list' is not
    supported`` (crash dur — révélé par les missions sur tier codex, juin
    2026).

Ce helper est la source de vérité partagée ; ``session_search`` y délègue.
(Le seul autre aplatisseur du dépôt, ``arena_service._extract_text``, est parti
avec l'Arena le 02/09/2026 — archive/arena.)
"""
from __future__ import annotations

from typing import Any


def content_to_text(content: Any) -> str:
    """Aplatit ``content`` (str | list | dict | None) en string plate.

    Jointure SANS séparateur : on reconstitue du JSON ou du texte fragmenté
    en blocs sans injecter de ``\\n`` parasite (les espaces utiles vivent
    déjà dans les blocs). Un dict sans champ texte exploitable → ``""``
    (déclenche proprement le fallback du parseur appelant plutôt que de
    fuiter un ``repr()`` Python dans le JSON).
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # Formes courantes : {"type": "text", "text": "..."} ou
                # {"content": "..."} — on prend le champ texte le plus
                # probable, on ignore les blocs sans texte (reasoning, etc.).
                txt = item.get("text") or item.get("content") or ""
                if isinstance(txt, str):
                    parts.append(txt)
        return "".join(parts)
    if isinstance(content, dict):
        txt = content.get("text") or content.get("content") or ""
        return txt if isinstance(txt, str) else str(content)
    return str(content)
