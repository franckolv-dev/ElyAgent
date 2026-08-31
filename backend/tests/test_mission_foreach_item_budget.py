# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_foreach_item_budget.py
# @brief      Le budget d'avancee appartient a l'ITEM, pas au step foreach :
#             sinon la premiere societe mange la ration des suivantes.
# @license    Elastic License 2.0
# =============================================================================
"""Une société servie, les autres affamées (31/08/2026).

L'INCIDENT
----------
Mission « Prospection STE Print ». Trois sociétés trouvées, toutes trois
avec des contacts qualifiés visibles dans les onglets LinkedIn restés
ouverts. Le tableur livré ne contient que les 5 lignes d'**Océalia**.

La trace des tours le dit exactement :

    it10-16  Océalia            open_tab, wait_loaded, read_text, append_rows
                                → 3 avancées puis RÉUSSI
    it18-28  Négoce Drouillet   open_tab, wait_loaded, read_text, ×2
                                → 6 avancées puis « n'a toujours pas abouti »
    it30     Groupe Dubreuil    open_tab
                                → 1 avancée puis « n'a toujours pas abouti »

Trois, six, une. Le compte est bon : 3 + 6 = 9, et la borne est à 8. Le
troisième item n'a eu droit qu'à un seul appel avant d'être condamné.

LA CAUSE
--------
``_mark_step_progress`` écrit ``progress_ticks`` sur le STEP du plan. Or un
step `foreach` est UN step, quel que soit son nombre d'items. Le compteur
était donc partagé par toutes les sociétés, et rien ne le remettait à zéro —
ni le changement d'item, ni la réussite du précédent.

Plus la liste est longue, plus c'est violent : avec les 5 sociétés que la
spec demande, la première en sert une, la deuxième meurt en chemin, et les
trois dernières ne voient jamais le jour.

LA RÈGLE
--------
Le budget d'avancée appartient à l'item. Chaque société repart de zéro.
"""
from __future__ import annotations

import pytest


def _plan_foreach(ticks: dict | int | None = None) -> dict:
    etape = {
        "id": "contacts",
        "description": "Pour {{ item }}, relève les contacts",
        "foreach": "{{ societes.output }}",
    }
    if ticks is not None:
        etape["progress_ticks"] = ticks
    return {"from_spec": True, "steps": [etape]}


def test_chaque_item_a_son_propre_budget() -> None:
    """L'item 1 ne doit rien devoir aux avancées de l'item 0."""
    import app.agent.missions.nodes as mn

    plan = _plan_foreach()
    # L'item 0 consomme tout son budget.
    for _ in range(mn.MAX_STEP_PROGRESS_TICKS):
        plan, epuise = mn._mark_step_progress(plan, "contacts", 0)
    assert not epuise

    # L'item 1 commence : il doit repartir de zéro.
    plan, epuise = mn._mark_step_progress(plan, "contacts", 1)
    assert not epuise, (
        "la première société mangeait la ration des suivantes — trois "
        "sociétés trouvées, une seule livrée"
    )


def test_un_item_qui_pietine_est_toujours_borne() -> None:
    """Le budget par item ne supprime pas la borne, il la localise."""
    import app.agent.missions.nodes as mn

    plan = _plan_foreach()
    epuise = False
    for _ in range(mn.MAX_STEP_PROGRESS_TICKS + 1):
        plan, epuise = mn._mark_step_progress(plan, "contacts", 3)
    assert epuise


def test_un_step_sans_item_garde_son_budget() -> None:
    """Une étape ordinaire (index 0 implicite) fonctionne comme avant."""
    import app.agent.missions.nodes as mn

    plan = {"steps": [{"id": "memoire", "description": "Consigne"}]}
    epuise = False
    for _ in range(mn.MAX_STEP_PROGRESS_TICKS + 1):
        plan, epuise = mn._mark_step_progress(plan, "memoire", None)
    assert epuise


def test_un_compteur_hérité_de_l_ancien_format_ne_casse_pas() -> None:
    """Les missions en cours portent un `progress_ticks` entier dans leur
    checkpoint. Il ne doit ni planter, ni condamner tous les items."""
    import app.agent.missions.nodes as mn

    plan, epuise = mn._mark_step_progress(_plan_foreach(ticks=7), "contacts", 2)
    assert not epuise
