# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_mission_reste_sur_complex_et_le_pool_se_voit.py
# @brief      Une mission n'est jamais routée par mots-clés vers le tier
#             image ; le pool SQLite est dimensionné comme celui de Postgres
#             et se laisse observer.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission libre « test2 » du 03/09/2026, 96 actions :

    TIMING[general.infer] 195.60s — tier=image  (gemma-4-26b local)
    TIMING[general.infer] 226.91s — tier=image
    TIMING[general.infer]   6.80s — tier=complex (gpt-5.6)

Le nœud agent route chaque tour par ``classify_complexity(user_query)`` — un
regex de mots-clés (« image », « photo », « visualise »…) qui envoie au tier
IMAGE. Sur un tour de mission, ``user_query`` est la consigne reconstruite,
qui cite les pages lues : un mot suffit, et le tour part sur la tête du tier
image — ce jour-là un modèle local, 30 000 tokens de préfill, quatre minutes
par appel. #369 avait posé la règle pour l'ancien moteur (« une mission
tourne sur COMPLEX ») ; la boucle du chat ne l'avait pas.

Et pendant ces minutes, à 20:19 :

    sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached

Toute l'API en 500 pendant cinq minutes, base SQLite libre. Le pool par
défaut (5 + 10) était celui que la revue de juin avait déjà jugé « premier
goulot invisible » — mais seulement pour Postgres.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest


# ── La mission épingle COMPLEX ───────────────────────────────────────────────

def test_la_boucle_des_missions_epingle_le_tier_complex():
    from app.agent.missions import chat_loop

    src = inspect.getsource(chat_loop.run_mission_chat_passage)
    assert '"tier_pin": "complex"' in src


def test_le_noeud_agent_honore_l_epingle_avant_de_classer():
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    assert 'state.get("tier_pin")' in src
    assert src.index('state.get("tier_pin")') < src.index("classify_complexity(user_query)")


def test_l_etat_du_graphe_declare_l_epingle():
    from app.agent.state import AgentState

    assert "tier_pin" in AgentState.__annotations__


def test_l_epingle_ne_touche_pas_un_tour_de_chat():
    """Sans épingle, ``classify_complexity`` garde la main : un vrai
    utilisateur qui demande une image doit toujours atteindre le tier image."""
    from app.services.llm_provider import ComplexityTier, classify_complexity

    assert classify_complexity("génère une image d'un chat roux") is ComplexityTier.IMAGE


# ── Le pool SQLite se dimensionne et se lit ──────────────────────────────────

def test_le_pool_sqlite_est_dimensionne_comme_postgres():
    from app import database

    src = inspect.getsource(database._make_engine)
    sqlite_branch = src[src.index('startswith("sqlite")'):src.index("# PostgreSQL")]
    assert '"pool_size": 20' in sqlite_branch
    assert '"max_overflow": 30' in sqlite_branch
    assert '"pool_timeout": 30' in sqlite_branch
    # Une base en mémoire (tests) vit sur un StaticPool sans taille.
    assert ":memory:" in sqlite_branch


def test_le_pool_se_lit():
    from app.database import pool_status

    statut = pool_status()
    for cle in ("size", "max_overflow", "checked_out", "checked_in", "overflow"):
        assert cle in statut, cle
        assert isinstance(statut[cle], int), cle


# ── La sonde nomme les tâches quand le pool sature ───────────────────────────

def test_la_saturation_se_juge_sur_la_capacite_totale():
    from app.services.pool_watch import est_sature

    assert est_sature({"size": 20, "max_overflow": 30, "checked_out": 45}) is True
    assert est_sature({"size": 20, "max_overflow": 30, "checked_out": 30}) is False
    assert est_sature({"size": 0, "max_overflow": 0, "checked_out": 0}) is False


@pytest.mark.asyncio
async def test_le_cliche_nomme_les_taches_et_leur_pile():
    from app.services.pool_watch import cliche_des_taches

    async def _attend_longtemps():
        await asyncio.sleep(10)

    t = asyncio.create_task(_attend_longtemps(), name="passage-mission-test")
    await asyncio.sleep(0)
    try:
        texte = cliche_des_taches([t])
    finally:
        t.cancel()
    assert "passage-mission-test" in texte
    assert "_attend_longtemps" in texte
    assert texte.startswith("1 tâche(s) en vol, 1 avec une pile")


def test_le_serveur_lance_la_sonde_au_demarrage():
    from app import main

    src = inspect.getsource(main.lifespan)
    assert "surveiller_le_pool(" in src


def test_les_metriques_admin_exposent_le_pool():
    from app.routers import admin

    src = inspect.getsource(admin)
    assert '"db_pool"' in src and "pool_status()" in src
