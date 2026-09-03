# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/background_llm.py
# @brief      Appel LLM des tâches de fond — robustesse uniforme (content en
#             blocs, bloc <think>, isolation du stream).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Appel LLM des corvées de fond (extraction, résumé, consolidation, titre).

Ces chemins tournent hors du regard de l'utilisateur : quand ils échouent,
ils échouent en silence. Ce module leur donne trois garanties qu'aucun
n'avait, et que chacun aurait dû recopier.

**1. Le `content` en blocs ne fait plus planter le parse.** Le tier codex
(gpt-5.6, Responses API) renvoie ``content`` sous forme de LISTE de blocs.
Les chemins de fond faisaient ``getattr(response, "content", "")`` puis
``raw.strip()`` → ``AttributeError: 'list' object has no attribute 'strip'``,
avalé par le ``try/except`` best-effort. L'immunisation ``content_to_text``
a été posée sur les missions et les canaux (#205) — **elle manquait ici**.
Basculer le tier MAINTENANCE sur un modèle codex aurait cassé l'extraction
de faits sur chaque appel, sans une ligne de log exploitable.

**2. Un bloc `<think>` ne fait plus échouer le JSON.** Si un modèle raisonne
en clair, ``json.loads`` lève et la tâche ne produit rien — silencieusement.

**3. L'isolation du stream est uniforme.** ``config={"callbacks": []}`` coupe
le contexte de callbacks LangGraph propagé par contextvars. Sans lui, les
tokens de la tâche de fond fuient dans le stream d'un autre tour (bug vécu le
19/07). Deux chemins l'avaient, la génération de titre — qui tourne PENDANT
un tour de chat actif — ne l'avait pas.

⚠️ **Correction d'une hypothèse que j'avais faite, et qui était fausse.**
Ce module a d'abord été écrit pour supprimer des tokens de raisonnement :
``usage_logs`` montrait 2 101 tokens de sortie par extraction, contre 151
pour un modèle sans raisonnement. **La mesure a démenti la conclusion.** Ce
chiffre agrégeait toute l'histoire, et il était dominé par l'essai
d'`ornith-1.0-9b` des 16-17/07 — un modèle qui ignorait
``enable_thinking:false``, abandonné depuis. Sur les sept derniers jours,
l'extraction tourne à **102 tokens de sortie** : elle est déjà sobre.

De plus ``/no_think`` **n'a aucun effet sur Qwen 3.5** — ``llm_provider.py``
le dit explicitement, et une mesure au chrono dans le conteneur l'a confirmé
(7,5 s avec, 8,9 s sans : indiscernable). Le raisonnement est déjà coupé au
niveau du fournisseur par ``chat_template_kwargs.enable_thinking=False``,
injecté inconditionnellement pour LM Studio.

``inject_no_think`` est conservé parce qu'il reste correct pour les modèles
Qwen 3 servis en local, et qu'il est inerte ailleurs — mais **il ne faut
attendre aucun gain de tokens de ce module**. Sa valeur est la robustesse.

**Ce module ne décide pas à la place de l'appelant** : un juge
(``mission_critic``, ``diagnostician``) peut vouloir raisonner et passe
``reasoning=True``.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ainvoke_background(
    llm: Any,
    messages: list,
    *,
    reasoning: bool = False,
) -> str:
    """Invoque ``llm`` pour une tâche de fond et rend le texte de la réponse.

    Trois garanties :

    1. **Le texte est toujours du texte** — un ``content`` en liste de blocs
       (tier codex) est aplati par ``content_to_text`` au lieu de faire
       lever ``.strip()`` chez l'appelant.
    2. **Isolation du stream** — ``config={"callbacks": []}`` coupe le
       contexte de callbacks LangGraph propagé par contextvars. Sans lui, les
       tokens de la tâche de fond fuient dans le stream d'un autre tour (bug
       vécu le 19/07 : le code du générateur tier-S entrelacé caractère par
       caractère avec la réponse d'Ely).
    3. **Pas de bloc de pensée dans la sortie** — si un modèle raisonne en
       clair, ``<think>…</think>`` est retiré avant que l'appelant ne parse
       du JSON. Sans ça, ``json.loads`` échoue et la tâche ne produit rien,
       en silence.

    ``reasoning=False`` (défaut) injecte aussi ``/no_think`` sur un local
    Qwen. **N'en attends aucun gain sur Qwen 3.5** : c'est inerte, le
    raisonnement est coupé au niveau du fournisseur. Conservé pour Qwen 3.

    **Ne masque jamais une panne** : l'exception remonte. Les appelants ont
    déjà leur propre ``try/except`` best-effort, et un échec avalé deux fois
    devient invisible.
    """
    payload = messages
    if not reasoning:
        try:
            from app.services.qwen_no_think import inject_no_think, is_local_openai_llm
            if is_local_openai_llm(llm):
                payload = inject_no_think(messages)
        except Exception as exc:  # noqa: BLE001 — l'optimisation ne casse rien
            logger.debug("no_think non appliqué: %s", exc)

    response = await llm.ainvoke(payload, config={"callbacks": []})

    content = getattr(response, "content", "") or ""
    if not isinstance(content, str):
        # Tier codex (Responses API) : `content` arrive en liste de blocs.
        try:
            from app.agent.helpers.message_content import content_to_text
            content = content_to_text(content)
        except Exception:  # noqa: BLE001
            content = str(content)
    try:
        from app.services.qwen_no_think import strip_think_block
        content = strip_think_block(content)
    except Exception as exc:  # noqa: BLE001
        logger.debug("strip_think_block non appliqué: %s", exc)
    return content


async def ainvoke_background_with_usage(
    llm: Any,
    messages: list,
    *,
    reasoning: bool = False,
) -> tuple[str, Any]:
    """Variante rendant ``(texte, réponse brute)``.

    Les appelants qui journalisent la consommation ont besoin de l'objet
    réponse pour son ``usage_metadata`` — sans quoi le poste de coût
    disparaîtrait des mesures au moment même où on l'optimise.
    """
    payload = messages
    if not reasoning:
        try:
            from app.services.qwen_no_think import inject_no_think, is_local_openai_llm
            if is_local_openai_llm(llm):
                payload = inject_no_think(messages)
        except Exception as exc:  # noqa: BLE001
            logger.debug("no_think non appliqué: %s", exc)

    response = await llm.ainvoke(payload, config={"callbacks": []})

    content = getattr(response, "content", "") or ""
    if not isinstance(content, str):
        try:
            from app.agent.helpers.message_content import content_to_text
            content = content_to_text(content)
        except Exception:  # noqa: BLE001
            content = str(content)
    try:
        from app.services.qwen_no_think import strip_think_block
        content = strip_think_block(content)
    except Exception as exc:  # noqa: BLE001
        logger.debug("strip_think_block non appliqué: %s", exc)
    return content, response
