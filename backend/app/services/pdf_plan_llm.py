# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/pdf_plan_llm.py
# @brief      Ely DONNE la structure à décider au modèle cloud, et relit sa
#             réponse — elle ne décide plus seule.
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
"""Le chemin qui manquait entre la demande de Franck et le travail.

    « Elle est là pour donner aux bons modèles, avec les bonnes instructions
      et pour contrôler le travail fait. »   — Franck, 28/07/2026

Ce que ce module change
------------------------
``pdf_to_docx(source, output_name)`` n'avait aucun argument capable de porter
une exigence. « Respecte les sauts de page » mourait dans le chat : le modèle
appelait l'outil avec un chemin et un nom de fichier, puis rapportait ce que
l'outil avait bien voulu faire. **Il n'a jamais vu ces PDF.** C'est ici que
ça change — les exigences de l'utilisateur descendent dans le prompt, avec la
géométrie réelle du document.

Ce qu'on demande au modèle, et ce qu'on ne lui demande pas
-----------------------------------------------------------
On lui demande **le jugement** : cette page est-elle voulue ou est-ce un
débordement de texte, ce bloc est-il un titre, ce « 12 » isolé en bas de page
est-il du texte ou un folio. C'est précisément ce qu'un seuil statistique fait
mal, et ce pour quoi on paie un modèle frontière.

On ne lui demande **pas** le texte. Le balisage ne porte que des identifiants ;
Ely réinjecte le contenu depuis sa propre extraction. Un modèle qui recopie
800 000 caractères en perdrait, et coûterait cent fois plus cher.

Et on ne lui demande pas de statuer sur tout : le corps courant est le défaut.
Une ligne de balisage par tête de page, par titre et par artefact suffit — le
reste est mécanique, donc à Ely.

Les trois règles héritées de la boucle de conformité (#288/#289)
-----------------------------------------------------------------
1. **Échouer OUVERT.** Modèle absent, quota épuisé, réponse illisible → plan
   vide → la conversion d'hier. Une délégation cassée ne doit jamais rendre un
   document pire que celui d'avant le lot.
2. **Une tranche perdue n'emporte pas les autres.** Sur 27 tranches, une
   coupure passagère coûte 15 pages au défaut, pas le manuscrit entier.
3. **Rien n'est tronqué en silence.** Au-delà du plafond de tranches, le
   rapport le DIT.
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage

from app.agent.helpers.message_content import content_to_text
from app.services.llm_deadline import ainvoke_with_deadline
from app.services.pdf_layout import (
    ConversionPlan,
    DocumentLayout,
    build_layout_digest,
    parse_conversion_plan,
)

logger = logging.getLogger(__name__)

# Mesuré sur le manuscrit de Franck (395 pages, 5 049 blocs, 12,8 par page) :
# 15 pages ≈ 3 450 tokens de digest en entrée et ~1 900 en sortie. Au-delà, la
# sortie approche `max_output_tokens=4096` et le balisage se fait couper au
# milieu — on perdrait la fin de chaque tranche sans le savoir.
PAGES_PER_WINDOW: int = 15

# Les tranches sont indépendantes : les enchaîner en série ferait 27 allers-
# retours pour ce manuscrit. Borné, parce qu'un provider n'aime pas 27 requêtes
# simultanées et que le tour de l'utilisateur n'est pas seul sur la machine.
MAX_CONCURRENT_WINDOWS: int = 4

# Garde-fou d'emballement, pas un régulateur : 40 tranches = 600 pages. Au-delà
# on le DIT (cf. règle 3) au lieu de rogner le document en douce.
MAX_WINDOWS: int = 40

# Une tranche qui revient SANS AUCUNE décision est redemandée. Mesuré après
# #294 sur des appels réels : à document et prompt identiques, le modèle rend
# tantôt 26-28 décisions, tantôt du vide. Une seule reprise — au-delà, on
# paierait des appels sans raison de mieux réussir (leçon de #289).
WINDOW_RETRIES: int = 1

_PROMPT = """\
Tu décides de la STRUCTURE d'un document Word reconstruit depuis un PDF.

{exigences}

Ce que tu reçois : la géométrie mesurée du PDF, bloc par bloc. Chaque ligne est
un bloc, avec son identifiant, sa position verticale, son corps en points, des
drapeaux (GRAS, GRAND, PETIT, CENTRE, COURT — « COURT » = la ligne ne va pas au
bout de la justification) et un EXTRAIT de son texte.

Tu ne réécris rien. Le texte reste tel quel : tu ne rends que des identifiants.

RÉPONDS PAR UN BALISAGE, une ligne par bloc sur lequel tu statues. L'identifiant
NU, puis le rôle, puis les attributs, séparés par des espaces. Exactement ainsi —
sans chevrons, sans crochets, sans puce, sans guillemets :

    p1b0 TITRE1 SAUT CENTRE
    p1b4 ARTEFACT
    p8b0 CORPS SUITE

RÔLES : TITRE1 (chapitre, partie) · TITRE2 (sous-titre) · CORPS · CITATION
        · ARTEFACT (à SUPPRIMER du document : folio, en-tête courant)
ATTRIBUTS : SAUT (ce bloc commence une nouvelle page)
            SUITE (ce bloc continue le paragraphe précédent — ne pas couper)
            CENTRE (bloc centré)

Ne statue que sur ce qui demande un jugement :
- le PREMIER bloc de chaque page — c'est là qu'est la décision qui compte :
  soit la page est VOULUE (page de titre, dédicace, exergue, nouveau chapitre)
  et tu mets SAUT, soit le texte de la page précédente déborde simplement et tu
  mets SUITE. Tranche pour CHAQUE page de la tranche ci-dessous ;
- les titres ;
- les artefacts — un numéro de page seul en bas de page en est un, sur toutes
  les pages où il apparaît.

Le reste est du corps courant, tu n'as pas à l'écrire.

N'invente aucun identifiant : n'utilise que ceux de la liste.
Réponds UNIQUEMENT par les lignes de balisage, sans commentaire.

{contexte}
GÉOMÉTRIE DU DOCUMENT (pages {first} à {last} sur {total}) :

{digest}
"""

_NO_REQUIREMENTS = (
    "L'utilisateur n'a pas formulé d'exigence particulière : vise un document "
    "fidèle à la structure du PDF source."
)

_WITH_REQUIREMENTS = """\
EXIGENCES DE L'UTILISATEUR — elles priment sur tout le reste :

{requirements}
"""


def _window_bounds(page_count: int) -> list[tuple[int, int]]:
    """Découpe le document en tranches de pages, 1-based et inclusives."""
    windows = [
        (start, min(start + PAGES_PER_WINDOW - 1, page_count))
        for start in range(1, page_count + 1, PAGES_PER_WINDOW)
    ]
    if len(windows) > MAX_WINDOWS:
        logger.warning(
            "plan de conversion : %d tranches demandées, plafonné à %d "
            "(pages %d à %d non soumises au modèle)",
            len(windows), MAX_WINDOWS,
            windows[MAX_WINDOWS][0], page_count,
        )
        windows = windows[:MAX_WINDOWS]
    return windows


def _boundary_context(layout: DocumentLayout, first: int) -> str:
    """Ce sur quoi s'arrêtait la page précédente.

    Sans ça, le premier bloc d'une tranche est indécidable : rien ne dit si le
    paragraphe d'avant se terminait ou débordait. Le modèle le lit, mais ne
    statue pas dessus — il n'est pas dans sa tranche.
    """
    if first <= 1:
        return ""
    previous = layout.pages[first - 2]
    if not previous.blocks:
        return ""
    last = previous.blocks[-1]
    fin = "va jusqu'au bout de la ligne" if last.fills_line else "s'arrête avant la marge"
    return (
        f"CONTEXTE (page {previous.number}, hors de ta tranche — ne statue pas "
        f"dessus) : elle se termine par « {last.text[-120:]} » et cette ligne "
        f"{fin}.\n\n"
    )


async def _ask_once(llm, prompt: str) -> ConversionPlan:
    """Un aller-retour. Ne lève jamais : une panne rend un plan vide."""
    # ``config={"callbacks": []}`` : cet appel tourne PENDANT un tour actif.
    # Sans cette coupure, LangChain propage l'arbre de callbacks par
    # contextvars et le balisage s'affiche caractère par caractère dans la
    # réponse de l'utilisateur (bug réel du 19/07/2026).
    response = await ainvoke_with_deadline(
        llm, [HumanMessage(content=prompt)],
        tier="complex", surface="pdf-plan", config={"callbacks": []},
    )
    return parse_conversion_plan(
        content_to_text(getattr(response, "content", response))
    )


async def _plan_one_window(llm, layout: DocumentLayout, first: int,
                           last: int, requirements: str) -> ConversionPlan:
    """Une tranche, avec une reprise si elle revient sans aucune décision.

    Mesuré après #294 : sur le MÊME document et le MÊME prompt, GPT-5.6 Terra
    rend tantôt 26-28 décisions, tantôt **une réponse vide** — sans erreur, sans
    ``finish_reason``, en quelques secondes (l'échéance est à 240 s). Rien ne
    permet de distinguer les deux cas avant de lire la réponse.

    Une tranche vide est un signal NET, pas une décision discutable : on
    redemande. C'est le geste de la boucle de conformité (#288/#289) appliqué
    ici. **Une seule fois** — un modèle muet deux fois ne le sera pas moins la
    troisième, et insister coûterait des appels sans raison de mieux réussir.
    """
    prompt = _PROMPT.format(
        exigences=(
            _WITH_REQUIREMENTS.format(requirements=requirements.strip()[:2000])
            if requirements.strip() else _NO_REQUIREMENTS
        ),
        contexte=_boundary_context(layout, first),
        first=first, last=last, total=layout.page_count,
        digest=build_layout_digest(layout, first_page=first, last_page=last),
    )

    for attempt in range(1 + WINDOW_RETRIES):
        try:
            plan = await _ask_once(llm, prompt)
        except Exception as exc:  # noqa: BLE001 — échouer OUVERT, tranche par tranche
            plan, raison = ConversionPlan(), str(exc)
        else:
            if not plan.is_empty:
                return plan
            raison = "réponse sans aucune décision exploitable"

        if attempt < WINDOW_RETRIES:
            logger.info(
                "plan de conversion : pages %d-%d, %s — on redemande",
                first, last, raison,
            )

    logger.warning(
        "plan de conversion : pages %d-%d non planifiées après %d tentative(s) "
        "(%s) — heuristiques locales pour ces pages",
        first, last, 1 + WINDOW_RETRIES, raison,
    )
    return ConversionPlan()


async def request_conversion_plan(
    layout: DocumentLayout,
    requirements: str = "",
    *,
    user_id: str = "",
    conversation_id: str = "",
) -> ConversionPlan:
    """Demande au modèle cloud de décider de la structure du document.

    Args:
        layout: la géométrie relevée par :func:`~app.services.pdf_layout.extract_layout`.
        requirements: les exigences de l'utilisateur, EN CLAIR. C'est le chemin
            qui n'existait pas : ce que Franck écrit descend jusqu'ici.
        user_id, conversation_id: pour journaliser le coût de la délégation —
            sans quoi on ne peut pas arbitrer si elle vaut ce qu'elle rapporte.

    Returns:
        Le plan fusionné de toutes les tranches. **Vide** si aucun modèle n'est
        disponible ou si tout a échoué — auquel cas la conversion retombe
        intégralement sur son comportement d'avant ce lot.
    """
    from app.services.llm_provider import ComplexityTier, get_llm_for_tier

    # Tier COMPLEX : c'est un travail de jugement sur un document réel, pas une
    # corvée de fond. Le routage par tier est une config admin héritée — on
    # demande un niveau, on ne choisit pas un modèle.
    llm = get_llm_for_tier(ComplexityTier.COMPLEX)
    if llm is None:
        logger.warning(
            "plan de conversion : aucun modèle disponible — conversion au défaut",
        )
        return ConversionPlan()

    windows = _window_bounds(layout.page_count)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_WINDOWS)

    async def _bounded(first: int, last: int) -> ConversionPlan:
        async with semaphore:
            return await _plan_one_window(llm, layout, first, last, requirements)

    parts = await asyncio.gather(*(_bounded(a, b) for a, b in windows))

    merged = ConversionPlan()
    for part in parts:
        merged.decisions.update(part.decisions)

    logger.info(
        "plan de conversion : %d page(s) en %d tranche(s) → %d décision(s), "
        "%d saut(s) de page, %d artefact(s)",
        layout.page_count, len(windows), len(merged.decisions),
        sum(1 for d in merged.decisions.values() if d.page_break),
        len(merged.dropped()),
    )

    await _log_usage(user_id, conversation_id)
    return merged


async def _log_usage(user_id: str, conversation_id: str) -> None:
    """Le coût de la délégation doit être visible au tableau de bord.

    Best-effort, comme ``memory_extraction`` et la boucle de conformité : une
    journalisation qui tombe ne doit pas emporter la conversion.
    """
    if not user_id:
        return
    try:
        from app.services.analytics_service import log_response_usage

        await log_response_usage(
            user_id, None, skill_used="pdf_conversion_plan",
            conversation_id=conversation_id or None,
        )
    except Exception as exc:  # noqa: BLE001 — la journalisation est un confort
        logger.debug("plan de conversion : usage non journalisé (%s)", exc)


__all__ = [
    "MAX_CONCURRENT_WINDOWS",
    "MAX_WINDOWS",
    "PAGES_PER_WINDOW",
    "WINDOW_RETRIES",
    "request_conversion_plan",
]
