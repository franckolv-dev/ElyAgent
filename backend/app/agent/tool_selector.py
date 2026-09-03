# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_selector.py
# @brief      Un petit modèle local LIT les descriptions et choisit les outils
#             pertinents, au lieu d'envoyer les 85 à chaque tour.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Le premier poste du contexte — mesuré le 29/07/2026.

Sur un tour de conversation ordinaire :

    15 567 tool_defs +   427 conversation +   910 mcp + 1 033 système
    = 17 937 tokens  →  **87 % du contexte, ce sont les descriptions d'outils**

Les 85 outils du profil partent à chaque tour, quelle que soit la demande. Et
comme la boucle d'outils renvoie tout le contexte à chaque itération, ces
15 567 tokens sont **repayés à chaque tour de boucle** — même mécanisme
quadratique que les retours navigateur non bornés (#301).

Pourquoi pas le filtre par mots-clés qui existait déjà
--------------------------------------------------------
``tool_filter.filter_tools_by_query`` coupe bien (85 → 8-30), mais mesuré sur
les vraies demandes de Franck :

- il **coupe ``find_tool`` dans 5 cas sur 6** — or c'est l'annuaire, le seul
  moyen de retrouver un outil coupé à tort. Sans lui : « je n'ai pas l'outil » ;
- il ne comprend pas les demandes naturelles : « cale un déjeuner avec Gert »
  ne matche ni ``calendar`` ni ``agenda`` → 85/85 gardés, aucun gain.

C'est le mécanisme qui a produit le bug de #287. On ne le rebranche pas.

Ce qu'on fait à la place — un modèle qui LIT
----------------------------------------------
Mesuré sur ``gemma-4-E4B`` (local, coût nul), 4/4 :

    « cale un déjeuner avec Gert »  → calendar_quick_add · …   1,1 s
    « convertis ce PDF en Word »    → pdf_to_docx · …          1,0 s
    « nettoie ma boîte mail »       → gmail_search_for_cleanup 1,2 s
    « dépose ce fichier sur Drive » → drive_upload_local_file  1,1 s

⚠️ Le choix du modèle compte : ``qwen3.5-9b`` donne la même qualité en **8,9 s**
— huit fois plus lent, ce qui rendait l'échange défavorable. C'est la vitesse
du sélecteur qui rend ce lot rentable, pas sa seule qualité.

⚠️ Échouer OUVERT
------------------
Sélecteur absent, en panne, réponse illisible, ou aucun nom reconnu → **on rend
la liste complète**, c'est-à-dire le comportement d'avant ce lot. Un tour un peu
plus lourd vaut infiniment mieux qu'un agent désarmé qui répond « je n'ai pas
l'outil ».
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# Ce qui reste branché quoi qu'il arrive.
#
# ``find_tool`` d'abord : c'est le filet. Si le sélecteur coupe le bon outil,
# c'est le seul moyen de le retrouver — et c'est exactement ce que le filtre
# par mots-clés supprimait, ce qui le rendait dangereux.
CORE_TOOLS: frozenset[str] = frozenset({
    "find_tool",
    "memory_recall",
    "search_past_conversations_tool",
})

# Une ligne de description suffit à reconnaître un outil. Envoyer les
# descriptions complètes au sélecteur reviendrait à payer ce qu'on économise.
_DIRECTORY_LINE_CHARS: int = 95

# Assez pour une demande composée (« convertis ce PDF ET dépose-le sur Drive »),
# trop peu pour annuler le gain.
_MAX_SELECTED: int = 12

_NAME = re.compile(r"[a-z][a-z0-9_]{2,}", re.IGNORECASE)

_PROMPT = """\
Voici les outils disponibles d'une assistante personnelle :

{annuaire}

DEMANDE DE L'UTILISATEUR : {demande}

Donne les noms des outils nécessaires pour répondre à cette demande, du plus au
moins pertinent, un par ligne, sans rien d'autre. Au maximum {maxi}.
N'utilise QUE des noms présents dans la liste ci-dessus, sans les inventer.
"""


def build_directory(tools) -> str:
    """L'annuaire compact : un outil par ligne, sa première ligne de description.

    Mesuré sur les 207 outils réels : 16 738 caractères, ~4 184 tokens. C'est le
    prix d'entrée du sélecteur, et il doit rester très inférieur aux 15 567
    tokens qu'il fait économiser.
    """
    lignes = []
    for t in tools:
        desc = (getattr(t, "description", "") or "").strip()
        premiere = desc.splitlines()[0][:_DIRECTORY_LINE_CHARS] if desc else ""
        lignes.append(f"{getattr(t, 'name', '?')}: {premiere}")
    return "\n".join(sorted(lignes))


def _selector_llm():
    """Le modèle qui choisit — local, petit, rapide.

    ``TOOL_SELECTOR_MODEL`` (fragment de nom, insensible à la casse) permet de
    le désigner ; sinon on prend la première instance locale dont le nom
    contient un des fragments préférés, du plus rapide au plus lent.

    ⚠️ On ne code PAS un modèle en dur : ce serait la classe de défaut que
    ``config_reality`` traque — une valeur qui a l'air de marcher et qui ne
    correspond à rien de configuré. Sans instance locale, on rend ``None`` et
    la sélection est simplement sautée.
    """
    prefere = os.getenv("TOOL_SELECTOR_MODEL", "").strip().lower()
    fragments = [prefere] if prefere else ["e4b", "gemma-4-12b", "qwen3.5"]
    try:
        from app.services.llm_provider import _instance_cache, _make_llm_for_instance

        for frag in fragments:
            for iid, inst in _instance_cache.items():
                if inst.get("provider") not in ("lm_studio", "ollama"):
                    continue
                if frag in (inst.get("model") or "").lower():
                    # Un tri de noms ne se tire pas au sort : à 0,7 (le défaut
                    # de la fabrique) Ministral 3B rendait `pdf_to_docx` une
                    # fois sur deux pour « convertir un PDF en Word » ; à zéro
                    # le résultat est le même à chaque passe (banc 03/09/2026).
                    # Douze noms tiennent en 256 tokens : un modèle qui
                    # déraille s'arrête en moins d'une seconde.
                    return _make_llm_for_instance(iid, max_tokens=256, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 — un sélecteur absent n'est pas fatal
        logger.debug("sélecteur d'outils : instance introuvable (%s)", exc)
    return None


async def select_tools(user_query: str, tools, *, include_core: bool = True):
    """Les outils pertinents pour cette demande, noyau compris.

    Args:
        include_core: ajouter le noyau (``CORE_TOOLS``) au résultat. Vrai pour
            BRANCHER un tour — il faut garder ``find_tool`` sous la main. Faux
            pour répondre à une question d'annuaire : proposer ``find_tool``
            comme réponse à « quel outil pour X » est une boucle.

    Returns:
        La liste filtrée, ou **la liste complète** dès qu'un doute existe :
        pas de demande, pas de sélecteur, appel en erreur, réponse illisible,
        aucun nom reconnu. Échouer OUVERT — un contexte plus lourd vaut mieux
        qu'un « je n'ai pas l'outil ».
    """
    tous = list(tools)
    if not (user_query or "").strip() or not tous:
        return tous

    llm = _selector_llm()
    if llm is None:
        logger.debug("sélecteur d'outils : aucun modèle local — liste complète")
        return tous

    prompt = _PROMPT.format(
        annuaire=build_directory(tous), demande=user_query.strip()[:1000],
        maxi=_MAX_SELECTED,
    )
    try:
        # ``config={"callbacks": []}`` : ce choix se fait PENDANT un tour actif.
        # Sans cette coupure, les tokens du sélecteur s'affichent dans la
        # réponse de l'utilisateur (bug réel du 19/07).
        from langchain_core.messages import HumanMessage

        from app.services.llm_deadline import ainvoke_with_deadline

        response = await ainvoke_with_deadline(
            llm, [HumanMessage(content=prompt)],
            tier="simple", surface="tool-selector", config={"callbacks": []},
        )
    except Exception as exc:  # noqa: BLE001 — échouer OUVERT
        logger.warning("sélecteur d'outils : indisponible (%s) — liste complète", exc)
        return tous

    from app.agent.helpers.message_content import content_to_text

    verdict = content_to_text(getattr(response, "content", response))
    connus = {getattr(t, "name", ""): t for t in tous}
    # Un modèle local invente parfois un nom plausible : on ne garde que ce qui
    # existe réellement, sinon le binding casse ou l'agent croit avoir un outil
    # qui n'est nulle part.
    choisis = []
    for mot in _NAME.findall(verdict):
        if mot in connus and mot not in choisis:
            choisis.append(mot)
        if len(choisis) >= _MAX_SELECTED:
            break

    if not choisis:
        logger.info(
            "sélecteur d'outils : aucun nom reconnu dans %.60r — liste complète",
            verdict.strip(),
        )
        return tous

    garde = set(choisis)
    if include_core:
        garde |= CORE_TOOLS & set(connus)
    retenus = [t for t in tous if getattr(t, "name", "") in garde]
    logger.info(
        "sélecteur d'outils : %d → %d outils pour %.50r",
        len(tous), len(retenus), user_query.strip(),
    )
    return retenus


__all__ = ["CORE_TOOLS", "build_directory", "select_tools"]
