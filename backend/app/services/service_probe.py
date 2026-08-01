# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/service_probe.py
# @brief      Exerce RÉELLEMENT chaque tête de chaîne — LLM et recherche — pour
#             attraper les services qui se construisent sans jamais répondre.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Sonde des têtes de chaîne.

**Le trou qu'elle bouche.** ``config_reality`` vérifie qu'un service est
**constructible** : modèle connu des tables de fenêtre et de tarif, déclaré par
une instance, outils existants. Il ne vérifie **jamais qu'il répond**.

Deux pannes en une journée sont passées par ce trou, contrôle vert :

```
30/07  kimi-k3      se construit parfaitement, rend 400 au premier appel.
                    Tête du tier C depuis le 28/07, jamais servi depuis le
                    6 mai, 17 bascules silencieuses en 3 jours.
31/07  searchcans   répond « 200 OK » avec « API key has no balance ».
                    Toute la chaîne de recherche devenait muette.
```

**Ce qu'elle fait.** Un appel réel par tête de chaîne, LLM *et* recherche, et
un ``Finding`` pour chacune qui ne répond pas — avec la CAUSE, pas seulement
« ne répond pas ». Un constat qui énonce sa conséquence se remarque ; un nom de
service seul se noie, c'est la leçon de l'avertissement « Unknown model » que
personne n'a lu pendant des mois.

**Ce qu'elle NE fait pas, volontairement.**

- Elle sonde les **têtes**, pas les 11 instances de toutes les chaînes. Une
  tête morte est une panne immédiate et visible ; un repli mort dégrade
  proprement. Sonder Kimi (25 s par appel) ou DeepSeek pro (facturé) pour
  surveiller une position de secours coûterait plus que ça ne rapporte.
- Elle **ne corrige rien**. Échouer au démarrage ne veut pas dire échouer
  toujours ; réordonner une chaîne ou écarter un fournisseur est une décision
  de politique, pas un diagnostic. Elle constate, Franck décide.
- Elle **ne bloque pas le démarrage** et ne lève jamais : elle tourne sur des
  services réseau, où le timeout est un mode de fonctionnement normal.

⚠️ **Module séparé de ``config_reality`` à dessein.** Greffer un contrôle sur
une fonction partagée avait cassé quatre pins existants en #296, dont le
contrat est « liste vide = rien à signaler ». On réutilise son ``Finding``,
pas sa fonction.
"""
from __future__ import annotations

import asyncio
import logging

from app.services.config_reality import Finding

logger = logging.getLogger(__name__)

# Assez court pour ne pas retarder le démarrage, assez long pour un modèle de
# raisonnement : kimi-k3 met ~25 s à répondre « OK ». Au-delà, l'absence de
# réponse EST le constat.
_TIMEOUT_S = 40.0

_PING = "Réponds exactement : OK"
_REQUETE_TEMOIN = "France"   # terme générique : zéro résultat = anomalie


def _chain_heads() -> dict[str, tuple[str, str]]:
    """{ tier: (id_instance, nom_modèle) } pour la TÊTE de chaque chaîne.

    Dédupliqué par instance : `gemma-4-E4B` est en tête de trois tiers, on ne
    l'appelle qu'une fois.
    """
    from app.services.llm_provider import get_tier_config

    vus: set[str] = set()
    tetes: dict[str, tuple[str, str]] = {}
    for tier, cfg in (get_tier_config() or {}).items():
        ids = (cfg or {}).get("providers") or []
        if not ids or ids[0] in vus:
            continue
        vus.add(ids[0])
        # Le nom lisible vient du client une fois construit (`model_name`) ;
        # ici on ne dispose que de l'identifiant, tronqué pour le journal. Il
        # ne sert que si l'instance ne se construit PAS — sinon le constat
        # porte le vrai nom du modèle.
        tetes[tier] = (ids[0], ids[0][:8])
    return tetes


def _build(instance_id: str):
    """Matérialise l'instance. `None` si elle n'est pas constructible."""
    from app.services.llm_provider import ComplexityTier, build_llm_for_provider

    return build_llm_for_provider(instance_id, ComplexityTier.COMPLEX)


def _search_providers() -> dict[str, object]:
    """{ nom: coroutine(query, count) } pour chaque fournisseur configuré.

    Les fournisseurs sans clé sont absents : ne pas les sonder n'est pas un
    constat, c'est leur état déclaré.
    """
    from app.agent.tools import search_tool as st
    from app.config import get_settings

    s = get_settings()
    sondes: dict[str, object] = {}

    if getattr(s, "serper_api_key", ""):
        cle = s.serper_api_key
        async def _serper(query: str, count: int):
            return await st._search_serper(query, count, cle)
        sondes["serper"] = _serper

    if getattr(s, "searchcans_api_key", ""):
        cle = s.searchcans_api_key
        async def _searchcans(query: str, count: int):
            return await st._search_searchcans(query, count, cle)
        sondes["searchcans"] = _searchcans

    if getattr(s, "tavily_api_key", ""):
        cle = s.tavily_api_key
        async def _tavily(query: str, count: int):
            return await st._search_tavily(query, count, cle)
        sondes["tavily"] = _tavily

    return sondes


async def _probe_model(tier: str, instance_id: str, nom: str) -> Finding | None:
    from langchain_core.messages import HumanMessage

    try:
        llm = _build(instance_id)
    except Exception as exc:  # noqa: BLE001
        return Finding("head_unbuildable", f"{nom} (tier {tier})",
                       f"ne se construit pas : {type(exc).__name__} — {exc}"[:200])
    if llm is None:
        return Finding("head_unbuildable", f"{nom} (tier {tier})",
                       "ne se construit pas (clé absente ?) — le tier repartira "
                       "sur son repli à chaque tour")

    modele = getattr(llm, "model_name", getattr(llm, "model", nom)) or nom
    try:
        await asyncio.wait_for(llm.ainvoke([HumanMessage(content=_PING)]),
                               timeout=_TIMEOUT_S)
    except asyncio.TimeoutError:
        return Finding("head_mute", f"{modele} (tier {tier})",
                       f"n'a pas répondu en {_TIMEOUT_S:.0f} s — chaque tour de "
                       f"ce tier attendra puis basculera sur le repli")
    except Exception as exc:  # noqa: BLE001
        return Finding("head_mute", f"{modele} (tier {tier})",
                       f"se construit mais REFUSE l'appel : {exc}"[:200])
    return None


async def _probe_search(nom: str, sonde) -> Finding | None:
    try:
        resultats = await asyncio.wait_for(sonde(_REQUETE_TEMOIN, 3),
                                           timeout=_TIMEOUT_S)
    except asyncio.TimeoutError:
        return Finding("search_mute", nom,
                       f"n'a pas répondu en {_TIMEOUT_S:.0f} s sur « "
                       f"{_REQUETE_TEMOIN} »")
    except Exception as exc:  # noqa: BLE001
        return Finding("search_mute", nom, f"a échoué : {exc}"[:200])

    # ⚠️ `None` et `[]` ne disent PAS la même chose, et la chaîne s'appuie sur
    # cette distinction : `None` = le fournisseur signale son échec, `[]` = il
    # a répondu sans rien trouver. Les confondre envoie chercher au mauvais
    # endroit — « pas de résultat » fait penser à un quota, « a échoué » fait
    # lire l'erreur. Constaté au premier démarrage : Serper, qui rendait un
    # 400, était annoncé comme « répond mais ne rend aucun résultat ».
    if resultats is None:
        return Finding(
            "search_failed", nom,
            f"a échoué sur « {_REQUETE_TEMOIN} » — voir le journal du "
            f"fournisseur juste au-dessus ; la chaîne le paiera d'un "
            f"aller-retour à chaque recherche",
        )
    if not resultats:
        return Finding(
            "search_mute", nom,
            f"répond mais ne rend AUCUN résultat sur « {_REQUETE_TEMOIN} » — "
            f"crédits épuisés ou réponse illisible ; la chaîne le paiera d'un "
            f"aller-retour à chaque recherche",
        )
    return None


async def probe_services() -> list[Finding]:
    """Exerce chaque tête et rend la liste des constats. Ne lève jamais."""
    taches: list[asyncio.Future] = []

    try:
        for tier, (instance_id, nom) in (_chain_heads() or {}).items():
            taches.append(asyncio.ensure_future(_probe_model(tier, instance_id, nom)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("sonde : têtes LLM illisibles (%s)", exc)

    try:
        for nom, sonde in (_search_providers() or {}).items():
            taches.append(asyncio.ensure_future(_probe_search(nom, sonde)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("sonde : fournisseurs de recherche illisibles (%s)", exc)

    if not taches:
        return []

    resultats = await asyncio.gather(*taches, return_exceptions=True)
    return [r for r in resultats if isinstance(r, Finding)]


async def log_service_probe() -> int:
    """Lance la sonde et journalise chaque constat. Retourne leur nombre.

    En ``warning`` comme ``config_reality`` : ce sont des services qui ne
    servent pas, et l'utilisateur le paiera en latence ou en silence.
    """
    constats = await probe_services()
    for c in constats:
        logger.warning("[sonde] %s", c)
    if not constats:
        logger.info("[sonde] toutes les têtes de chaîne répondent")
    return len(constats)
