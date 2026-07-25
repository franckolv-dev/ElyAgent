# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_inert_code_removed.py
# @brief      V0-5 — ce qui n'a aucun consommateur disparaît, et ce qui promet
#             une capacité inexistante cesse de la promettre.
# @license    Elastic License 2.0
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

def test_supervisor_specialist_helpers_are_gone():
    import app.agent.supervisor as sup

    assert not hasattr(sup, "create_specialist_node")
    assert not hasattr(sup, "should_continue_specialist")


def test_supervisor_still_builds_its_graph():
    """Non-régression : les 5 canaux qui passent par le superviseur ne doivent
    rien perdre. (V1 tranchera son sort — pas ce lot.)"""
    from app.agent.supervisor import build_supervisor_graph

    assert build_supervisor_graph() is not None


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

def test_memory_recall_no_longer_offers_unreadable_types():
    """Les deux types sans lecture ne sont plus proposés comme valeurs
    acceptées. (La docstring peut les MENTIONNER pour dire qu'ils ne sont pas
    consultables — c'est justement le but.)"""
    from app.agent.tools.memory_recall_tool import _VALID_TYPES_TEXT, memory_recall

    assert "procedural" not in _VALID_TYPES_TEXT
    assert "error" not in _VALID_TYPES_TEXT
    assert "episodic" in _VALID_TYPES_TEXT and "auto" in _VALID_TYPES_TEXT

    described = f"{memory_recall.description}".lower()
    assert "pas consultable" in described or "ne sont pas consultables" in described, (
        "l'outil doit dire explicitement que ces types ne se lisent pas"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("memory_type", ["procedural", "error"])
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
