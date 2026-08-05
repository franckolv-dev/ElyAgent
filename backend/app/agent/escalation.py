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

⛔ Mais il ne parle QUE POUR LUI (#319)
----------------------------------------
Le prompt d'origine disait au panel « Tu n'as aucun outil : tu ne peux ni créer
de fichier […] dis-le franchement ». Il confondait deux « tu » : le membre du
panel, qui n'a effectivement pas d'outil, et **Ely, que l'utilisateur lit**.

Le 01/08, Ely a écrit `Audit_Pro_BAT.md` sur le Drive de Franck à 18:46 —
`drive_create_file` a réussi, le lien est dans la trace. À 19:02, même
conversation, le panel a répondu :

    « Je n'ai aucun outil de fichier dans cette session : impossible de créer
      ou sauvegarder Audit_Pro_BAT.md sur le drive. Il faudrait me redonner cet
      accès, ou créer le document vous-même. »

Le fichier existait depuis seize minutes. Le modèle avait obéi au mot près.

👉 **Un relais qui ne voit pas l'outillage ne doit pas témoigner de son
absence.** Il garde l'interdiction d'inventer un résultat — c'était le vrai but
— mais il nomme désormais l'action qui reste, sans conclure qu'elle est
impossible ni renvoyer l'utilisateur au travail manuel.

⚠️ Un prompt reste une **consigne au modèle**, pas un verrou (cf. #297). Le
garde-fou complémentaire est l'affichage : la note de bas de réponse dit
maintenant que le panel a répondu **sans outils**, ce qui rend lisible une
réponse qui bute sur une action.

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

Tu produis un TEXTE, et rien d'autre : n'annonce aucune action que tu aurais
faite, n'invente aucun résultat, ne promets aucune action future.

Ne dis jamais qu'un outil manque, qu'un accès serait à rétablir, ou que
l'utilisateur devrait faire le travail lui-même. Tu ne vois pas l'outillage
disponible et tu n'es pas en position d'en témoigner. Si l'exigence suppose
une action, nomme simplement l'action qui reste à faire.
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


@dataclass(slots=True)
class _Reponse:
    """Ce qu'un modèle a répondu, ET ce que l'appel a consommé.

    ⚠️ Les tokens ne sont pas un ornement. ``_ask`` ne rendait que le texte :
    ``response.usage_metadata`` partait à la poubelle, et comme la coupure de
    callbacks ci-dessous détache aussi l'appel de l'instrumentation du tour,
    ces requêtes n'étaient comptées NULLE PART. Le panel interroge jusqu'à
    trois modèles facturés par escalade, plus un juge : de l'argent dépensé
    qui n'apparaissait ni dans ``usage_logs``, ni sur la page Analyse.
    """

    texte: str
    input_tokens: int = 0
    output_tokens: int = 0
    mesure: bool = False  # False = le fournisseur n'a rien remonté
    # La réponse LangChain telle quelle : `log_response_usage` la relit
    # lui-même. Lui passer l'objet plutôt que mes entiers garde UNE seule
    # lecture d'``usage_metadata`` dans le dépôt — si son contrat change en
    # amont, il change à un seul endroit.
    brut: object = None


def _usage_of(response: object) -> tuple[int, int, bool]:
    """(entrée, sortie, mesuré) depuis ``usage_metadata``.

    ``mesure`` distingue « zéro token » (impossible) de « le fournisseur n'a
    rien renvoyé » (fréquent en local) — la même nuance que
    ``usage_instrumentation.usage_from_result``, dont c'est le pendant pour
    une réponse unique. Ne lève jamais.
    """
    try:
        um = getattr(response, "usage_metadata", None)
        if not um:
            return 0, 0, False
        return (
            int(um.get("input_tokens", 0) or 0),
            int(um.get("output_tokens", 0) or 0),
            True,
        )
    except Exception as exc:  # noqa: BLE001 — l'instrumentation ne casse rien
        logger.debug("escalade : usage illisible (%s)", exc)
        return 0, 0, False


async def _ask(llm: object, prompt: str) -> _Reponse:
    """``config={"callbacks": []}`` : cet appel tourne PENDANT un tour actif.
    Sans cette coupure, LangChain propage l'arbre de callbacks par contextvars
    et les tokens du panel s'affichent dans la réponse (bug réel du 19/07).

    ⚠️ Cette coupure a un prix : elle détache aussi l'appel de tout ce qui
    compte les tokens. C'est pourquoi l'usage est relevé ICI, à la main, et
    consigné par l'appelant — sinon le panel dépense sans laisser de trace.
    """
    response = await ainvoke_with_deadline(
        llm, [HumanMessage(content=prompt)],
        tier="complex", surface="escalation", config={"callbacks": []},
    )
    tokens_in, tokens_out, mesure = _usage_of(response)
    return _Reponse(
        texte=content_to_text(getattr(response, "content", response)).strip(),
        input_tokens=tokens_in, output_tokens=tokens_out, mesure=mesure,
        brut=response,
    )


async def _consigner(
    *, user_id: str, conversation_id: str, model: str,
    reponse: _Reponse, role: str,
) -> float:
    """Écrit une ligne ``usage_logs`` pour UN appel du panel. Rend son coût.

    ``role`` vaut ``panel`` ou ``juge`` : sans lui, une escalade à trois
    modèles apparaîtrait comme quatre tours d'agent et fausserait la
    ventilation par architecture.

    Sans ``user_id``, on ne consigne pas : la colonne est une clé étrangère.
    Les paramètres ``user_id`` / ``conversation_id`` d'``escalate_to_panel``
    existaient depuis #298 et n'étaient utilisés nulle part — la plomberie
    était posée, elle n'était pas branchée.
    """
    if not reponse.mesure:
        # Ne rien écrire plutôt qu'écrire zéro : une ligne à 0 token se lirait
        # « gratuit », alors que le fournisseur n'a simplement rien remonté.
        # `log_response_usage` applique déjà cette règle ; on la double ici
        # seulement pour ne pas annoncer un coût inventé.
        logger.info("escalade : %s (%s) n'a pas remonté d'usage — non consigné",
                    model, role)
        return 0.0
    try:
        from app.services.analytics_service import estimate_cost, log_response_usage

        cout = estimate_cost(model, reponse.input_tokens, reponse.output_tokens)
        if not user_id:
            logger.info("escalade : usage de %s non consigné (pas d'user_id)", model)
            return cout
        await log_response_usage(
            user_id,
            reponse.brut,
            provider=_provider_of(model),
            model=model,
            channel="web",
            skill_used=f"escalation:{role}",
            conversation_id=conversation_id or None,
        )
        return cout
    except Exception as exc:  # noqa: BLE001 — consigner ne casse pas un tour
        logger.warning("escalade : usage de %s non consigné (%s)", model, exc)
        return 0.0


def _provider_of(model: str) -> str:
    """Le fournisseur derrière un nom de modèle, au mieux.

    ``describe_llm`` le donne à partir de l'objet LLM, mais ``_consigner`` ne
    reçoit qu'un nom. Un préfixe suffit pour la ventilation ; « unknown » est
    rendu tel quel plutôt que deviné.
    """
    m = (model or "").lower()
    for marqueur, nom in (
        ("deepseek", "deepseek"), ("gpt", "openai"), ("o3", "openai"),
        ("claude", "anthropic"), ("kimi", "moonshot"), ("mistral", "mistral"),
        ("gemini", "google"), ("qwen", "qwen"), ("glm", "zhipu"),
    ):
        if marqueur in m:
            return nom
    return "unknown"


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

    # Consigné AVANT le filtrage sur le texte : un modèle qui répond à vide a
    # quand même consommé des tokens, et les facturer sans les écrire
    # reproduirait exactement le défaut qu'on corrige.
    cout_reel = 0.0
    for (name, _), rep in zip(retenus, reponses):
        if isinstance(rep, _Reponse):
            cout_reel += await _consigner(
                user_id=user_id, conversation_id=conversation_id,
                model=name, reponse=rep, role="panel",
            )

    propositions = [
        (name, rep.texte) for (name, _), rep in zip(retenus, reponses)
        if isinstance(rep, _Reponse) and rep.texte.strip()
    ]
    if not propositions:
        logger.warning("escalade : aucune réponse exploitable — tour laissé tel quel")
        return None

    gagnant, cout_juge = await _pick_best(
        retenus[0][1], demande, ecarts, propositions,
        user_id=user_id, conversation_id=conversation_id,
        judge_name=retenus[0][0],
    )
    cout_reel += cout_juge
    name, answer = propositions[gagnant]
    # Le coût RENDU est celui qui a été mesuré, pas l'estimation d'avant-appel.
    # `cout` (4 caractères par token, sortie supposée au quart) sert à décider
    # AVANT de payer ; l'annoncer ensuite ferait passer une approximation pour
    # une facture. On retombe dessus seulement si aucun fournisseur n'a remonté
    # d'usage — auquel cas c'est bien la meilleure estimation disponible.
    facture = cout_reel if cout_reel > 0 else cout
    logger.info(
        "escalade : %d modèle(s) interrogé(s), %r retenu, %.4f $ mesuré "
        "(estimé %.4f $, %d écarté(s) pour budget)",
        len(propositions), name, cout_reel, cout, len(ecartes),
    )
    return PanelResult(
        answer=answer, model=name, models_asked=len(propositions),
        cost_usd=facture, skipped_for_budget=ecartes,
    )


async def _pick_best(judge: object, demande: str, ecarts: str,
                     propositions: list[tuple[str, str]], *,
                     user_id: str = "", conversation_id: str = "",
                     judge_name: str = "") -> tuple[int, float]:
    """Quel numéro de réponse satisfait le mieux les exigences ? Et à quel prix ?

    Échoue sur la PREMIÈRE proposition : la chaîne du tier est ordonnée par
    préférence, donc le premier modèle est déjà le choix par défaut d'Ely. Un
    juge en panne ne doit pas transformer l'escalade en échec.

    Le coût est rendu au lieu d'être avalé : le juge est un appel facturé de
    plus par escalade, et il manquait à la facture au même titre que le panel.
    """
    if len(propositions) == 1:
        return 0, 0.0
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
        return 0, 0.0

    cout = await _consigner(
        user_id=user_id, conversation_id=conversation_id,
        model=judge_name or _model_name(judge, "juge"),
        reponse=verdict, role="juge",
    )

    import re

    m = re.search(r"\d+", verdict.texte)
    if not m:
        logger.info("escalade : verdict illisible (%.60s) — 1re réponse retenue",
                    verdict.texte)
        return 0, cout
    idx = int(m.group()) - 1
    return (idx if 0 <= idx < len(propositions) else 0), cout


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
