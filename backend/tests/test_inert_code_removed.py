# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_inert_code_removed.py
# @brief      V0-5 — ce qui n'a aucun consommateur disparaît, et ce qui promet
#             une capacité inexistante cesse de la promettre.
# @license    MIT
# =============================================================================
"""Pins de la suppression du code inerte (audit Opus 5 §6.3).

Trois cibles, et une correction de l'audit.

**Supprimé** :

- ``learning/ab_testing.py`` (381 l.) — ``select_variant`` /
  ``register_variant`` n'ont **aucun appelant de production** ; seuls deux
  endpoints admin lisaient un registre qui n'a jamais contenu qu'une variante,
  et le frontend ne les appelle nulle part.
- ``supervisor.create_specialist_node`` + ``should_continue_specialist`` —
  code mort, et le premier contient un ``NameError`` latent.
- ``memory/procedural_store.py`` — stub intégral : une méthode qui rend ``[]``,
  et **aucune voie d'écriture dans tout le dépôt**.

**⚠️ Correction de l'audit** : ``learning/prompt_version.py`` n'est PAS inerte.
Cinq modules de production en dépendent (``signals``, ``mission_critic``,
``user_state``, ``diagnostician``, ``patch_service``) pour estampiller la
version et l'empreinte du prompt sur les signaux d'apprentissage. L'audit
comptait « ab_testing + prompt_version = 452 lignes inertes » : l'addition est
juste (381 + 71), la conclusion ne l'est pas. Ce fichier reste.

**Le plus important n'est pas la suppression, c'est le mensonge qu'elle
retire** : ``memory_recall`` annonçait au modèle un type ``procedural``
(« reusable how-to recipes ») qui répondait toujours « aucun souvenir trouvé…
on n'en a peut-être jamais parlé ». Le modèle pouvait en conclure qu'il
n'existe pas de procédure — alors qu'il n'existe pas de *magasin*. C'est
exactement la façade que la boucle d'auto-diagnostic est censée détecter.

**Suite, 02/08.** ``procedural`` est redevenu annonçable — non pas en
rouvrant le magasin, mais en lui donnant la seule source qui existait déjà :
le **registre d'outils**, relu par la voie de ``find_tool``. Le stub reste
supprimé (les trois premiers tests ci-dessous le vérifient toujours), et la
règle qui comptait est désormais épinglée telle quelle : *ne jamais annoncer
un type qu'on ne sait pas lire*. Un catalogue muet répond « aucun outil ne
couvre ça », jamais « aucun souvenir » — la formulation d'origine renvoyait
le modèle vers la mauvaise conclusion.

Run with:  cd backend && python -m pytest tests/test_inert_code_removed.py -v
"""
from __future__ import annotations

import pytest


# ------------------------------------------------------------- ab_testing

def test_ab_testing_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import app.services.learning.ab_testing  # noqa: F401


def test_ab_testing_symbols_are_no_longer_re_exported():
    import app.services.learning as learning

    for name in ("select_variant", "register_variant", "list_variants",
                 "list_prompt_keys", "score_variants"):
        assert not hasattr(learning, name), f"{name} encore exporté"
        assert name not in getattr(learning, "__all__", ()), f"{name} encore dans __all__"


def test_admin_ab_endpoints_are_gone():
    from app.routers.admin import router

    paths = {r.path for r in router.routes}
    assert not any("/ab/" in p for p in paths), f"endpoints A/B encore montés : {paths}"


# ------------------------------------------------- prompt_version : IL RESTE

def test_prompt_version_is_still_live():
    """Garde-fou contre une relecture trop rapide de l'audit : ce module est
    load-bearing pour cinq modules d'apprentissage."""
    from app.services.learning.prompt_version import (
        current_system_prompt_version,
        prompt_hash,
    )

    assert callable(prompt_hash)
    assert callable(current_system_prompt_version)


@pytest.mark.parametrize("module_name", [
    "app.services.learning.signals",
    "app.services.learning.mission_critic",
    "app.services.learning.user_state",
    "app.services.learning.diagnostician",
    "app.services.learning.patch_service",
])
def test_prompt_version_consumers_still_import(module_name):
    __import__(module_name)


# ------------------------------------------------------ specialist dead code

def test_the_whole_supervisor_is_gone_since_v1_temps_2():
    """Ce lot (#246) n'avait retiré que `create_specialist_node` et
    `should_continue_specialist`, en gardant le graphe. V1 temps 2 (26/07) a
    supprimé le module entier — voir `test_v1_runtime_unified.py`."""
    from pathlib import Path

    assert not Path("app/agent/supervisor.py").exists()


# ----------------------------------------------------------- procedural store

def test_procedural_store_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import app.services.memory.procedural_store  # noqa: F401


def test_procedural_store_is_no_longer_exported():
    import app.services.memory as memory

    assert not hasattr(memory, "ProceduralStore")
    assert not hasattr(memory, "get_procedural_store")


def test_memory_manager_still_builds_without_the_stub():
    from app.services.memory_manager import get_memory_manager

    mgr = get_memory_manager()
    assert not hasattr(mgr, "procedural")


# ------------------------------- le mensonge retiré au modèle (le vrai gain)

def test_memory_recall_never_offers_a_type_it_cannot_read():
    """L'invariant, pas la liste — révisé le 02/08.

    Version d'origine : « ni `procedural` ni `error` ne sont proposés ». Elle
    figeait un CONSTAT (aucun des deux n'avait de lecture) là où la leçon est
    une RÈGLE : ne jamais annoncer au modèle un type qu'on ne sait pas lire.
    `procedural` a désormais une lecture — le registre d'outils — donc
    l'annoncer n'est plus un mensonge. `error` reste en écriture seule.

    Dérivé de `_UNREADABLE_TYPES` : la règle se vérifie toute seule au
    prochain changement, au lieu de rougir sur une liste à remettre à jour.
    """
    from app.agent.tools.memory_recall_tool import _VALID_TYPES_TEXT, memory_recall
    from app.services.memory.recall_service import _UNREADABLE_TYPES

    offerts = {t.strip() for t in _VALID_TYPES_TEXT.split("|")}
    illisibles = {t.value for t in _UNREADABLE_TYPES}

    assert not (offerts & illisibles), (
        f"types annoncés alors qu'ils ne se lisent pas : {offerts & illisibles}"
    )
    assert "episodic" in offerts and "auto" in offerts
    # Le gain du 02/08 : celui-ci est passé d'illisible à annonçable.
    assert "procedural" in offerts

    described = f"{memory_recall.description}".lower()
    assert "not readable" in described or "pas consultable" in described, (
        "l'outil doit dire explicitement qu'un type ne se lit pas"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("memory_type", ["error"])
async def test_memory_recall_on_an_unreadable_type_says_so_plainly(memory_type):
    """Si le modèle demande quand même ces types, la réponse doit être « ce
    n'est pas consultable », pas « aucun souvenir trouvé » — la seconde
    formulation est une affirmation sur le monde que rien ne justifie."""
    from app.database import init_db
    from app.agent.tools.memory_recall_tool import memory_recall

    await init_db()
    out = await memory_recall.ainvoke({
        "query": "comment je fais un catalogue",
        "memory_type": memory_type,
        "user_id": "u-test-recall",
    })

    low = f"{out}".lower()
    assert "aucun souvenir trouvé" not in low, (
        "réponse trompeuse : une mémoire non lisible présentée comme vide"
    )
    assert "pas consultable" in low
    assert "ne conclus pas" in low
