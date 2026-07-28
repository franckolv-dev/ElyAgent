# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/escalation.py
# @brief      Quand ça n'avance plus, demander à plusieurs modèles au lieu
#             d'abandonner.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""La chaîne de repli devient un panel — lot 2 du plan de marche, 28/07/2026.

Ce que Franck a demandé
------------------------
    « On a utilisé les fallback au cas où un modèle n'est plus disponible, il
      faut modifier cette approche et les utiliser également si les résultats
      ne sont pas convenables […] demander à 2 ou 3 modèles simultanément,
      prendre le meilleur retour et me le proposer. »

Mesuré : les huit déclencheurs de ``FailoverReason`` sont **tous techniques** —
``rate_limit``, ``timeout``, ``billing``, ``unavailable``, ``auth``… Aucun ne
regarde la qualité. Un modèle qui répond vite et mal ne déclenche rien.

Le déclencheur : le PROGRÈS
----------------------------
Franck avait d'abord proposé « après 3 tentatives ». On a mesuré en #289 que le
compteur fixe était mauvais et on l'a remplacé par le progrès. Le panel se
branche donc là où #289 constate que ça n'avance plus : la boucle ABANDONNAIT
en rédigeant un constat d'échec, elle ESCALADE désormais. Mieux qu'un compteur
dans les deux sens — plus tôt quand c'est bloqué, jamais quand ça progresse.

⚠️ Ce que le panel peut, et ce qu'il ne peut PAS
-------------------------------------------------
Les modèles du panel répondent **sans outils**. Ils améliorent donc une
RÉPONSE, jamais le RÉSULTAT d'un outil : sur « la conversion a aplati les
pages », aucun d'eux ne peut reconvertir le PDF.

C'est délibéré. Trois agents outillés en parallèle enverraient trois mails et
écriraient trois fichiers — le panel est en lecture seule **par construction**,
et c'est ce qui le rend sûr. Le cas « l'outil a mal produit » se traite en
amont, en donnant à l'outil de quoi recevoir l'exigence (cf. #294).

Budget — décision de Franck
----------------------------
    « Si le modèle est de type forfait (GPT 5.6), pas de plafond et si c'est
      via API, on établira un plafond par demande et qu'Ely me le dise. »
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from app.agent.helpers.message_content import content_to_text
from app.services.llm_deadline import ainvoke_with_deadline

logger = logging.getLogger(__name__)

# Au-delà, on paierait la diversité au prix fort sans preuve qu'elle rapporte :
# Franck a dit « 2 ou 3 modèles ».
MAX_PANEL_SIZE: int = 3

# Plafond par demande pour les modèles FACTURÉS. Les modèles au forfait n'y
# sont pas soumis (décision de Franck). Volontairement bas : une escalade est
# un cas rare, pas un régime de croisière.
METERED_BUDGET_USD: float = 0.50

_PANEL_PROMPT = """\
Un premier essai n'a pas satisfait la demande, et une reprise n'a rien amélioré.
C'est ton tour.

DEMANDE DE L'UTILISATEUR :
{demande}

CE QUI A DÉJÀ ÉTÉ PRODUIT :
{produit}

CE QUI NE VA PAS — les exigences non satisfaites :
{ecarts}

Réponds directement à l'utilisateur, en visant précisément ces exigences.

Tu n'as aucun outil : tu ne peux ni créer de fichier, ni envoyer quoi que ce
soit. Si ce qui manque exige un outil, dis-le franchement et explique ce qu'il
faudrait — n'invente aucun résultat et ne promets aucune action future.
"""

_JUDGE_PROMPT = """\
Plusieurs modèles ont répondu à la même demande. Choisis la meilleure réponse.

DEMANDE :
{demande}

EXIGENCES NON SATISFAITES par l'essai précédent :
{ecarts}

RÉPONSES :
{propositions}

Le seul critère : laquelle satisfait le mieux les exigences ci-dessus. Une
réponse qui reconnaît honnêtement une limite vaut mieux qu'une qui invente un
résultat.

Réponds UNIQUEMENT par le numéro de la meilleure réponse, rien d'autre.
"""


@dataclass
class PanelResult:
    """Ce que l'escalade a produit — et ce qu'elle a coûté."""

    answer: str
    model: str
    models_asked: int
    cost_usd: float
    skipped_for_budget: list[str]


def should_escalate(*, new_count: int, previous_count: int) -> bool:
    """Faut-il convoquer le panel ?

    Exactement l'inverse d'``is_making_progress`` (#289) : on escalade quand la
    reprise n'a rien fait reculer. ``previous_count == 0`` signifie « pas encore
    de tour de référence » — la première vérification a droit à sa reprise
    normale avant qu'on paie un panel.

    C'est le garde-fou de la facture : un tour qui progresse (6 écarts → 2 → 1)
    se règle tout seul, et convoquer le panel à chaque reprise multiplierait le
    coût de toutes les demandes qui allaient très bien.
    """
    if previous_count <= 0:
        return False
    return new_count >= previous_count


def is_flat_rate(model: str) -> bool:
    """Ce modèle est-il au forfait (ou local) ?

    Le tarif ``(0.0, 0.0)`` d'``analytics_service._PRICING`` l'encode déjà :
    ``gpt-5.6-terra`` est consommé via l'abonnement ChatGPT, les modèles
    LM Studio ne sont pas facturés à l'appel.

    ⚠️ Un modèle inconnu est supposé **facturé**. Se tromper dans l'autre sens
    ferait payer sans plafond — la prudence va du côté de l'argent.
    """
    try:
        from app.services.analytics_service import _PRICING

        price = _PRICING.get(model)
    except Exception as exc:  # noqa: BLE001 — sans table, on suppose facturé
        logger.debug("escalade : tarifs illisibles (%s)", exc)
        return False
    return price is not None and price[0] == 0.0 and price[1] == 0.0


def _panel_members(size: int = MAX_PANEL_SIZE) -> list[tuple[str, object]]:
    """Les modèles distincts du tier COMPLEX, prêts à répondre.

    La chaîne de repli est déjà une liste de modèles ORDONNÉE par préférence :
    on la relit comme un panel au lieu d'une cascade. Aucune configuration
    nouvelle — c'est le même réglage admin, lu autrement.
    """
    from app.services.llm_provider import _make_llm_for_instance, get_tier_config

    try:
        providers = list((get_tier_config().get("complex") or {}).get("providers") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("escalade : chaîne du tier complex illisible (%s)", exc)
        return []

    members: list[tuple[str, object]] = []
    for instance_id in providers:
        if len(members) >= size:
            break
        try:
            llm = _make_llm_for_instance(instance_id)
        except Exception as exc:  # noqa: BLE001 — un modèle absent n'arrête pas le panel
            logger.debug("escalade : instance %s indisponible (%s)", instance_id, exc)
            continue
        if llm is not None:
            members.append((instance_id, llm))
    return members


def _model_name(llm: object, fallback: str) -> str:
    """Le NOM DU MODÈLE, pas la description complète.

    ⚠️ ``describe_llm`` rend un tuple ``(provider, model)``, pas une chaîne. La
    première version rendait donc le tuple tel quel : ``is_flat_rate`` le
    passait à ``_PRICING.get``, qui répondait ``None``, et **tous les modèles
    au forfait passaient pour facturés**. Le plafond de budget les aurait
    écartés, donc aucun panel n'aurait jamais eu lieu en production.

    Aucun test stubbé ne pouvait le voir — les pins remplaçaient ``describe_llm``
    par une lambda qui rendait une chaîne. C'est la leçon de #288 : quand un
    test stubbe une fonction partagée, en doubler un qui appelle la VRAIE.
    """
    from app.services.llm_provider import describe_llm

    try:
        described = describe_llm(llm)
    except Exception:  # noqa: BLE001 — un nom de confort ne fait pas tomber le tour
        return fallback
    if isinstance(described, tuple):
        # (provider, model) — c'est le modèle qui porte le tarif.
        model = described[1] if len(described) > 1 else ""
        return str(model) if model and model != "?" else fallback
    return str(described) if described else fallback


async def _ask(llm: object, prompt: str) -> str:
    """``config={"callbacks": []}`` : cet appel tourne PENDANT un tour actif.
    Sans cette coupure, LangChain propage l'arbre de callbacks par contextvars
    et les tokens du panel s'affichent dans la réponse (bug réel du 19/07)."""
    response = await ainvoke_with_deadline(
        llm, [HumanMessage(content=prompt)],
        tier="complex", surface="escalation", config={"callbacks": []},
    )
    return content_to_text(getattr(response, "content", response)).strip()


async def escalate_to_panel(
    *, demande: str, produit: str, ecarts: str,
    user_id: str = "", conversation_id: str = "",
) -> PanelResult | None:
    """Interroge plusieurs modèles sur la même demande et rend la meilleure.

    Returns:
        ``None`` si l'escalade n'a rien à offrir — panel indisponible, un seul
        modèle, toutes les réponses vides. L'appelant rend alors ce qu'il avait
        déjà : **échouer OUVERT**, comme la boucle de conformité. Une
        amélioration qui tombe ne doit jamais coûter le résultat obtenu.
    """
    members = _panel_members()
    if len(members) < 2:
        # Un seul modèle, c'est ce que la reprise vient de faire. Le refaire
        # coûterait un appel pour rien.
        logger.info("escalade : %d modèle(s) disponible(s) — pas de panel", len(members))
        return None

    retenus, ecartes, cout = [], [], 0.0
    for instance_id, llm in members:
        name = _model_name(llm, instance_id)
        if is_flat_rate(name):
            retenus.append((name, llm))
            continue
        # Modèle facturé : il n'entre que si le plafond de la demande le permet.
        estime = _estimate_call_usd(name, demande, produit, ecarts)
        if cout + estime > METERED_BUDGET_USD:
            ecartes.append(name)
            continue
        cout += estime
        retenus.append((name, llm))

    if len(retenus) < 2:
        logger.info(
            "escalade : plafond de %.2f $ atteint — %d modèle(s) retenu(s), pas de panel",
            METERED_BUDGET_USD, len(retenus),
        )
        return None

    prompt = _PANEL_PROMPT.format(
        demande=demande[:3000], produit=produit[:5000], ecarts=ecarts[:2000],
    )
    reponses = await asyncio.gather(
        *(_ask(llm, prompt) for _, llm in retenus), return_exceptions=True,
    )

    propositions = [
        (name, txt) for (name, _), txt in zip(retenus, reponses)
        if isinstance(txt, str) and txt.strip()
    ]
    if not propositions:
        logger.warning("escalade : aucune réponse exploitable — tour laissé tel quel")
        return None

    gagnant = await _pick_best(retenus[0][1], demande, ecarts, propositions)
    name, answer = propositions[gagnant]
    logger.info(
        "escalade : %d modèle(s) interrogé(s), %r retenu, %.4f $ (%d écarté(s) pour budget)",
        len(propositions), name, cout, len(ecartes),
    )
    return PanelResult(
        answer=answer, model=name, models_asked=len(propositions),
        cost_usd=cout, skipped_for_budget=ecartes,
    )


async def _pick_best(judge: object, demande: str, ecarts: str,
                     propositions: list[tuple[str, str]]) -> int:
    """Quel numéro de réponse satisfait le mieux les exigences ?

    Échoue sur la PREMIÈRE proposition : la chaîne du tier est ordonnée par
    préférence, donc le premier modèle est déjà le choix par défaut d'Ely. Un
    juge en panne ne doit pas transformer l'escalade en échec.
    """
    if len(propositions) == 1:
        return 0
    listing = "\n\n".join(
        f"--- Réponse {i + 1} ---\n{txt[:2500]}"
        for i, (_, txt) in enumerate(propositions)
    )
    try:
        verdict = await _ask(judge, _JUDGE_PROMPT.format(
            demande=demande[:2000], ecarts=ecarts[:1500], propositions=listing,
        ))
    except Exception as exc:  # noqa: BLE001 — échouer sur le premier
        logger.warning("escalade : juge indisponible (%s) — 1re réponse retenue", exc)
        return 0

    import re

    m = re.search(r"\d+", verdict)
    if not m:
        logger.info("escalade : verdict illisible (%.60s) — 1re réponse retenue", verdict)
        return 0
    idx = int(m.group()) - 1
    return idx if 0 <= idx < len(propositions) else 0


def _estimate_call_usd(model: str, *parts: str) -> float:
    """Coût estimé d'UN appel du panel, en dollars.

    Approximation assumée : 4 caractères par token en entrée, et une sortie
    supposée du quart de l'entrée. On ne cherche pas la facture exacte — on
    cherche à ne pas dépasser un plafond sans le voir.
    """
    try:
        from app.services.analytics_service import _PRICING

        price_in, price_out = _PRICING.get(model, (1.0, 3.0))
    except Exception:  # noqa: BLE001
        price_in, price_out = 1.0, 3.0
    tokens_in = sum(len(p) for p in parts) / 4.0
    tokens_out = tokens_in / 4.0
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000.0


__all__ = [
    "MAX_PANEL_SIZE",
    "METERED_BUDGET_USD",
    "PanelResult",
    "escalate_to_panel",
    "is_flat_rate",
    "should_escalate",
]
