# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_incidents_always_have_an_exit.py
# @brief      Un incident qu'aucune action ne peut fermer pollue la liste à vie.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Les incidents orphelins du 21/08.

Franck : « J'ai régulièrement ces erreurs quand je veux proposer un correctif
ou générer un outil. Le problème est qu'ensuite les incidents restent ouverts
et viennent polluer la liste. »

Deux impasses distinctes, même conséquence.

1. LA CIBLE A DISPARU
----------------------
`propose_patch` levait ``PatchError("tâche planifiée introuvable (supprimée ?)")``
et s'arrêtait là. L'incident restait ``open``, et TOUTE action rejouait la même
erreur : il n'existait aucun chemin pour le faire sortir de la liste.

Le rejeter à la main aurait été faux. « Rejeté » veut dire « l'hypothèse est
mauvaise » ; ici l'hypothèse était peut-être excellente, sa cible a simplement
été supprimée. D'où ``obsolete``, posé par le service au moment où il constate
la disparition — jamais par l'humain, comme ``merged``.

2. « exists » N'EST PAS UN ÉCHEC
---------------------------------
Le backend refuse de dépenser un appel tier-S quand un outil couvre déjà la
capacité, et il le NOMME. L'incident disait « l'outil existe mais n'a pas été
lié à ce tour » : la réponse lui donne raison. L'écran affichait
« Génération échouée (status: exists) » et laissait l'incident ouvert.

⚠️ Il se résout en ``validated``, pas en ``actioned`` : l'hypothèse est
confirmée, mais le trou de liaison reste entier. « Traité » ferait croire à un
correctif qui n'existe pas — exactement la fausse déclaration que l'invariant 5
du dépôt interdit.

Run with:  cd backend && python -m pytest tests/test_incidents_always_have_an_exit.py -v
"""
from __future__ import annotations

import inspect

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1 — Le vocabulaire des statuts
# ─────────────────────────────────────────────────────────────────────

def test_a_moot_incident_has_a_status_of_its_own():
    """Sans lui, la seule sortie était un mensonge : « rejeté »."""
    from app.models.execution_diagnosis import DIAGNOSIS_STATUSES

    assert "obsolete" in DIAGNOSIS_STATUSES


def test_a_human_cannot_post_the_two_machine_statuses():
    """`merged` et `obsolete` constatent un fait, ils n'arbitrent rien.

    Les laisser passer par l'endpoint humain permettrait de classer « sans
    objet » un incident dont la cible existe encore — c'est-à-dire de le faire
    disparaître sans le traiter.
    """
    from app.routers import learning_skills

    src = inspect.getsource(learning_skills.resolve_incident)
    assert '"merged"' in src and '"obsolete"' in src, (
        "les deux statuts posés par la machine doivent être refusés à l'humain"
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — La cible disparue ferme l'incident
# ─────────────────────────────────────────────────────────────────────

def test_a_deleted_task_closes_its_incident_before_raising():
    """LE pin de l'incident — et il est STRUCTUREL, sans faire semblant.

    Le monter en test réel demanderait une base, un `ExecutionOutcome`, un
    `ExecutionDiagnosis` et une `ScheduledTask` supprimée entre-temps. Le coût
    dépasse ce qu'il protège ; l'ordre des deux instructions, lui, se lit.

    L'ordre EST l'invariant : lever d'abord laisserait l'incident ouvert,
    puisque le classement ne serait jamais atteint. C'est précisément ce que
    faisait le code d'avant — il ne faisait QUE lever.
    """
    from app.services.learning import patch_service

    for fn in (patch_service.propose_patch, patch_service.apply_patch):
        src = inspect.getsource(fn)
        pos_classement = src.find("_classer_obsolete(")
        pos_levee = src.find("raise PatchTargetGone(")
        assert pos_classement != -1, (
            f"{fn.__name__} : une cible disparue ne classe pas l'incident, il "
            f"restera « open » sans aucun moyen d'en sortir"
        )
        assert pos_levee != -1, f"{fn.__name__} : la cible disparue ne se signale pas"
        assert pos_classement < pos_levee, (
            f"{fn.__name__} : l'incident doit être classé AVANT que l'erreur "
            f"ne remonte"
        )


def test_the_gone_target_error_is_distinguishable():
    """Un texte d'erreur ne se teste pas côté interface : il change, il se
    traduit. Le TYPE, lui, tient — et c'est lui que le routeur mappe en 410."""
    from app.services.learning.patch_service import PatchError, PatchTargetGone

    assert issubclass(PatchTargetGone, PatchError), (
        "elle doit rester rattrapable par les appelants qui ne distinguent pas"
    )


def test_the_router_maps_a_gone_target_to_410():
    """410 et pas 422 : la demande était valide, c'est la cible qui n'est plus.

    C'est ce code que l'interface lit pour retirer la carte — un 422 générique
    serait indiscernable d'une panne, et la carte resterait.
    """
    from app.routers import learning_skills

    for fn in (learning_skills.propose_incident_patch,
               learning_skills.apply_incident_patch):
        src = inspect.getsource(fn)
        assert "PatchTargetGone" in src and "410" in src, (
            f"{fn.__name__} ne distingue pas une cible disparue"
        )
        # L'ordre des `except` compte : PatchTargetGone hérite de PatchError,
        # donc un `except PatchError` placé avant l'attraperait le premier et
        # rendrait 422. Le pin le vérifie, parce que rien d'autre ne le ferait.
        assert src.find("except PatchTargetGone") < src.find("except PatchError"), (
            f"{fn.__name__} : la sous-classe doit être attrapée EN PREMIER, "
            f"sinon le 410 n'est jamais atteint"
        )


@pytest.mark.asyncio
async def test_closing_an_incident_never_breaks_the_caller(monkeypatch):
    """Le classement est un rangement. S'il échoue, il ne doit pas masquer
    l'erreur qu'il accompagne — l'utilisateur perdrait la cause."""
    from app.services.learning import patch_service

    def _base_cassee(*_a, **_k):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(patch_service, "async_session", _base_cassee)
    # Ne lève pas : l'exception est absorbée et journalisée.
    await patch_service._classer_obsolete(1, "motif")


# ─────────────────────────────────────────────────────────────────────
# 3 — « exists » est une conclusion
# ─────────────────────────────────────────────────────────────────────

def test_an_existing_tool_is_reported_with_its_name():
    """Le CONTRAT dont l'interface dépend maintenant.

    ⚠️ Ce test passe déjà sur le code d'avant : le backend nommait l'outil
    depuis toujours. Le défaut était côté écran, qui jetait cette information
    dans un « Génération échouée (status: exists) ». Le pin ne l'attrape donc
    pas — il empêche qu'on retire le nom en croyant simplifier une réponse
    d'erreur, ce qui re-casserait la résolution qu'on vient de brancher.
    """
    from app.routers import learning_skills

    src = inspect.getsource(learning_skills)
    bloc = src[src.find('"status": "exists"'):]
    assert "tool_name" in bloc[:400], (
        "la réponse « exists » doit porter le nom de l'outil couvrant"
    )
