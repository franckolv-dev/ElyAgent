# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_the_runtime_follows_the_screen.py
# @brief      La base dit gemma, l'écran dit gemma, LM Studio charge nemotron.
# @license    Elastic License 2.0
# =============================================================================
"""Le 23/08, changer le modèle du tier A n'a rien changé.

    Franck : « J'ai voulu remplacer nemotron par gemma-4-E4B. J'ai enregistré,
               testé avec la même question, et dans LM Studio c'est toujours
               nemotron qui se lance et répond. Je suis retourné voir dans les
               paramètres : c'est bien gemma-4-E4B qui est en tier A. Précision,
               nemotron n'est pas présent dans le .env. »

Il avait raison sur toute la ligne, y compris sur le `.env`. Le nom n'était
nulle part : ni en base, ni dans l'environnement, ni à l'écran. **Il ne vivait
plus que dans un objet Python** — le client construit au démarrage et gardé
dans la fermeture de `create_agent_node`.

LE MÉCANISME
-------------
Un tier peut désigner une **instance nommée** par son UUID. C'est l'instance
qui porte le nom du modèle (`inst["model"]`, lu par `_make_llm_for_instance`).
Éditer une instance change donc quel modèle sert un tier — exactement comme
réécrire la chaîne du tier.

Mais seule la seconde incrémentait `_tier_config_version` :

    set_tier_config()            → compteur +1  → les caches reconstruisent
    register_instance_cache()    → compteur     → les caches gardent l'ancien
    unregister_instance_cache()  → compteur     → idem

Or `nodes.py` n'a que ce compteur pour décider. `_slm_with_tools` et
`_tier_llm_cache` gardaient donc un client construit sur `nvidia/
nemotron-3-nano-4b`, et chaque tour redemandait ce modèle à LM Studio, qui le
rechargeait docilement.

⚠️ POURQUOI C'EST LA CLASSE DE DÉFAUT LA PLUS CHÈRE DU DÉPÔT
--------------------------------------------------------------
Les trois surfaces d'observation sont JUSTES : la base a la bonne valeur,
l'API la rend, l'écran l'affiche. Seul le comportement ment. Il n'existe aucun
endroit où regarder pour s'en apercevoir — Franck a fait la seule chose
possible, revérifier l'écran, et l'écran lui a confirmé qu'il avait raison.

⚠️ ET C'EST LA TROISIÈME FOIS, PAR UNE TROISIÈME PORTE :

    #272   fenêtre de contexte et tarifs saisis, jamais relus → troncature à
           8 192 tokens et tarif générique jusqu'au redémarrage.
    #336   modèle du tier A changé dans l'onglet Routage, sans effet côté SLM.
    23/08  modèle d'une instance changé, sans effet nulle part.

Trois incidents, un seul motif : **une écriture qui atteint la base sans
atteindre le runtime.** D'où le pin structurel plus bas — il n'énumère pas les
trois portes connues, il vérifie que celles qui existent incrémentent toutes.

Run with:  cd backend && python -m pytest tests/test_the_runtime_follows_the_screen.py -v
"""
from __future__ import annotations

import inspect

import pytest


@pytest.fixture
def lp():
    """Le module, avec son cache d'instances restauré après chaque test."""
    from app.services import llm_provider

    avant = dict(llm_provider._instance_cache)
    try:
        yield llm_provider
    finally:
        llm_provider._instance_cache.clear()
        llm_provider._instance_cache.update(avant)


# ─────────────────────────────────────────────────────────────────────
# 1 — Les trois portes incrémentent
# ─────────────────────────────────────────────────────────────────────

def test_editing_an_instance_model_invalidates_the_caches(lp):
    """LE pin de l'incident.

    Éditer l'instance, c'est réécrire `inst["model"]` — donc changer le modèle
    que `_make_llm_for_instance` demandera. Sans incrément, la fermeture de
    `create_agent_node` garde son client et redemande l'ancien modèle à chaque
    tour.
    """
    avant = lp.get_tier_config_version()
    lp.register_instance_cache("inst-tier-a", "lm_studio", "nvidia/nemotron-3-nano-4b", None)
    apres_creation = lp.get_tier_config_version()
    assert apres_creation > avant, "créer une instance n'invalide rien"

    # Le geste exact de Franck : même instance, autre modèle.
    lp.register_instance_cache("inst-tier-a", "lm_studio", "google/gemma-4-E4B-it-MLX-4bit", None)
    assert lp.get_tier_config_version() > apres_creation, (
        "changer le modèle d'une instance n'invalide pas les caches — les "
        "tours suivants continueront de demander l'ancien modèle, alors que "
        "la base, l'API et l'écran affichent tous le nouveau"
    )
    assert lp._instance_cache["inst-tier-a"]["model"].endswith("gemma-4-E4B-it-MLX-4bit")


def test_deleting_an_instance_invalidates_the_caches(lp):
    """Un tier qui pointait sur l'instance supprimée doit reconstruire.

    Sinon il sert un modèle que l'administrateur croit avoir débranché — et
    sur un fournisseur payant, ça se lit sur la facture avant de se lire
    ailleurs.
    """
    lp.register_instance_cache("inst-a-jeter", "lm_studio", "un-modele", None)
    avant = lp.get_tier_config_version()
    lp.unregister_instance_cache("inst-a-jeter")
    assert lp.get_tier_config_version() > avant, (
        "supprimer une instance n'invalide rien"
    )


def test_rewriting_the_tier_chain_still_invalidates(lp):
    """La porte qui marchait déjà (#336). Elle doit continuer."""
    avant = lp.get_tier_config_version()
    lp.set_tier_config({"simple": {"providers": ["ollama"], "fallback_enabled": True}})
    assert lp.get_tier_config_version() > avant


def test_the_counter_only_ever_grows(lp):
    """Les caches comparent par inégalité. Un compteur qui redescend leur
    ferait manquer un changement — ou reconstruire sans raison."""
    vus = [lp.get_tier_config_version()]
    lp.register_instance_cache("inst-mono", "lm_studio", "m1", None)
    vus.append(lp.get_tier_config_version())
    lp.register_instance_cache("inst-mono", "lm_studio", "m2", None)
    vus.append(lp.get_tier_config_version())
    lp.unregister_instance_cache("inst-mono")
    vus.append(lp.get_tier_config_version())

    assert vus == sorted(vus) and len(set(vus)) == len(vus), (
        f"le compteur n'est pas strictement croissant : {vus}"
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — Le pin structurel : la QUATRIÈME porte
# ─────────────────────────────────────────────────────────────────────

def test_every_writer_of_the_instance_cache_bumps_the_counter():
    """⚠️ CELUI QUI EMPÊCHE LA QUATRIÈME OCCURRENCE.

    Les trois pins du dessus couvrent les portes CONNUES. Celui-ci couvre
    celles qui n'existent pas encore : toute fonction du module qui écrit dans
    `_instance_cache` doit incrémenter `_tier_config_version`.

    C'est un contrôle textuel, et c'est assumé — l'alternative serait de
    deviner à l'exécution quelles fonctions mutent un dict, ce qui coûterait
    plus de mécanique que ça n'en garantit. Ici la question posée est simple et
    la réponse est lisible : qui écrit, et qui incrémente ?

    ⚠️ `_instance_cache.get(...)` et les itérations ne comptent pas : lire ne
    change pas quel modèle sert un tier.
    """
    from app.services import llm_provider

    src = inspect.getsource(llm_provider)
    ecrivains: list[str] = []
    for bloc in src.split("\ndef ")[1:]:
        nom = bloc.split("(", 1)[0].strip()
        corps = bloc
        mute = (
            "_instance_cache[" in corps
            or "_instance_cache.pop(" in corps
            or "_instance_cache.clear(" in corps
            or "_instance_cache.update(" in corps
        )
        if mute and "_tier_config_version += 1" not in corps:
            ecrivains.append(nom)

    assert not ecrivains, (
        f"{ecrivains} écrivent dans `_instance_cache` sans incrémenter "
        f"`_tier_config_version`. Les caches de `nodes.py` n'ont que ce "
        f"compteur pour savoir qu'un modèle a changé : sans lui, la base et "
        f"l'écran diront la vérité et Ely servira l'ancien modèle."
    )


def test_the_agent_node_still_reads_the_counter():
    """L'autre bout du fil.

    Incrémenter ne sert à rien si personne ne relit. Deux caches en dépendent
    dans `nodes.py` — celui des tiers et celui du SLM — et le second n'a été
    branché qu'en #336.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    assert src.count("get_tier_config_version()") >= 1, (
        "le nœud ne lit plus le compteur — changer un modèle n'aura plus "
        "d'effet avant redémarrage"
    )
    assert "_slm_cfg_version" in src, (
        "la voie SLM ne suit plus la configuration (régression de #336)"
    )
