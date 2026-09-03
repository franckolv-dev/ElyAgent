# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/slm_warmup.py
# @brief      SLM warm-up — charge le modèle local en RAM, SANS retenir le boot
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    2.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Chauffe le petit modèle local pour que la première question ne paie pas le
chargement en RAM.

L'INCIDENT DU 08/08 — un confort qui a coûté le service
--------------------------------------------------------
Franck pose ``SLM_ENABLED=true``. Au redémarrage suivant, **Ely ne démarre
plus** : ``dependency backend failed to start``, conteneur *unhealthy* après
82 s.

Trois défauts empilés, tous dans ce fichier :

1. **Le warm-up était ATTENDU dans le lifespan** (``await warmup_slm()``).
2. **Son backoff totalisait 62 s** (2+4+8+16+32) sur cinq tentatives.
3. **Il ne pouvait pas réussir** — voir ci-dessous.

Le healthcheck du compose abandonne à ``15s + 3 × 30s``. Ely finissait bien
par démarrer — « Application startup complete » apparaît dans les logs — mais
Docker avait déjà déclaré le conteneur mort. Un modèle **optionnel** et
**injoignable** empêchait donc le service entier de tourner.

LE TROISIÈME DÉFAUT, LE PLUS SOURNOIS
--------------------------------------
L'ancien code appelait ``{ollama_base_url}/api/generate`` avec
``settings.slm_model``. Or ``get_slm()`` ne lit ni l'un ni l'autre : il rend
``get_llm_for_tier(ComplexityTier.SIMPLE)``, donc le tier A tel que
l'utilisateur l'a configuré — LM Studio chez Franck. Le warm-up interrogeait
un serveur Ollama qui n'existe pas, pour un nom de modèle qui n'est pas le
bon. **Il ne pouvait pas aboutir**, et ses cinq échecs étaient la seule chose
qu'il produisait.

C'est le même défaut que #327 corrigeait sur l'étiquette et la fenêtre de
contexte — l'identité du SLM lue dans des réglages statiques périmés au lieu
du tier résolu. Ce fichier était le troisième site, et il avait été manqué.

CE QUI TIENT MAINTENANT
------------------------
- On chauffe **l'objet LLM réel**, via ``ainvoke`` : ça marche quel que soit
  le fournisseur, sans reconstruire d'appel HTTP à la main.
- On ne chauffe **que du local**. Un tier A branché sur un modèle facturé
  paierait un appel à chaque démarrage pour un gain nul : un fournisseur cloud
  n'a pas de modèle à charger en RAM.
- Le tout part **en tâche de fond**. Le premier tour paiera son démarrage à
  froid si le modèle n'est pas prêt — c'est précisément ce que le warm-up
  cherchait à éviter, et c'est un prix acceptable. L'inverse ne l'est pas.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# Fournisseurs qui chargent un modèle en RAM. Chauffer un cloud coûterait un
# appel facturé par démarrage pour rien — il n'a rien à précharger.
_LOCAUX = ("ollama", "lm_studio")

# Trois tentatives, pauses courtes. L'ancien backoff montait à 32 s : un
# serveur LOCAL qui ne répond pas au bout de quelques secondes ne répondra pas
# davantage à la 62ᵉ — il n'est pas lancé, ou il n'écoute pas sur une adresse
# joignable depuis le conteneur. Attendre plus longtemps ne fait qu'allonger
# la fenêtre pendant laquelle on croit qu'il va venir.
_TENTATIVES = 3
_PAUSES = (2, 5)          # entre les tentatives — 7 s au total, pas 62
_TIMEOUT_APPEL = 30.0     # un chargement en RAM, pas une génération


def _provider_declare() -> str:
    """Le fournisseur du rang 1 du tier A, tel que l'utilisateur l'a DÉCLARÉ.

    Le corps vit dans `llm_provider.declared_provider_for_tier` depuis le
    21/08 : le chemin d'étiquetage en a eu besoin à son tour, et deux copies
    de cette lecture auraient dérivé. Cette fonction reste ici comme point
    d'entrée nommé du warm-up — les pins de #328 s'y accrochent, et c'est le
    tier A que la chauffe concerne, pas un tier quelconque.
    """
    from app.services.llm_provider import declared_provider_for_tier

    return declared_provider_for_tier("simple")


async def _warmup() -> None:
    """La chauffe elle-même. Ne lève jamais : c'est un confort, pas un service."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.slm_enabled:
        return

    try:
        from app.services.llm_provider import describe_llm, get_slm

        llm = get_slm()
        provider, model = describe_llm(llm)
        # Le fournisseur DÉCLARÉ prime sur celui qu'on devine. `describe_llm`
        # se fonde sur le `base_url` — sa docstring l'assume, « le seul
        # désambiguïsateur fiable » — parce qu'une même classe LangChain sert
        # dix backends. Mais l'utilisateur, lui, a CHOISI « ollama » ou
        # « lm_studio » en créant son instance : deviner ce qui est déclaré,
        # c'est se donner une chance de tomber à côté sans raison. (Remarque
        # de Franck, 08/08.)
        declare = _provider_declare()
        if declare:
            provider = declare
    except Exception as exc:  # noqa: BLE001
        logger.warning("SLM warm-up : tier A illisible (%s) — chauffe annulée", exc)
        return

    if provider not in _LOCAUX:
        logger.info(
            "SLM warm-up ignoré : le tier A sert « %s » via %s, un fournisseur "
            "distant n'a rien à charger en RAM", model, provider,
        )
        return

    from langchain_core.messages import HumanMessage

    for tentative in range(1, _TENTATIVES + 1):
        try:
            await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content="hi")]),
                timeout=_TIMEOUT_APPEL,
            )
            logger.info(
                "SLM warm-up terminé (tentative %d) : %s/%s chargé en RAM",
                tentative, provider, model,
            )
            return
        except Exception as exc:  # noqa: BLE001 — inclut le TimeoutError
            logger.warning(
                "SLM warm-up tentative %d/%d échouée (%s/%s) : %s",
                tentative, _TENTATIVES, provider, model, exc,
            )
        if tentative <= len(_PAUSES):
            await asyncio.sleep(_PAUSES[tentative - 1])

    # Le message NOMME la cause la plus fréquente. « All connection attempts
    # failed » ne dit pas à l'utilisateur que son serveur local n'écoute
    # peut-être que sur 127.0.0.1, invisible depuis un conteneur.
    logger.warning(
        "SLM warm-up abandonné après %d tentatives (%s/%s) — la première "
        "question paiera un démarrage à froid. Si le serveur tourne bien, "
        "vérifie qu'il écoute sur 0.0.0.0 et non sur 127.0.0.1 : depuis le "
        "conteneur, `localhost` désigne le conteneur.",
        _TENTATIVES, provider, model,
    )


async def warmup_slm() -> None:
    """Lance la chauffe EN TÂCHE DE FOND et rend la main immédiatement.

    ⚠️ Cette fonction ne doit jamais devenir bloquante, quelle que soit la
    bonne raison qu'on croira avoir. C'est ce qui a mis Ely à terre le 08/08 :
    un modèle optionnel injoignable retenait le démarrage au-delà du
    healthcheck du compose, et le conteneur était déclaré mort alors que
    l'application avait fini par démarrer.
    """
    from app.services.background_tasks import spawn

    spawn(_warmup(), label="slm-warmup")
