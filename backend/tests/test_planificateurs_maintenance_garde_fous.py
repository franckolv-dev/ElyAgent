# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_planificateurs_maintenance_garde_fous.py
# @brief      Les crons de maintenance de main.py portent les mêmes garde-fous
#             que le planificateur de tâches (audit 02/09).
# @license    Elastic License 2.0
# =============================================================================
"""Pins des deux planificateurs de maintenance.

Le défaut corrigé (audit 02/09). ``services/scheduler._job_defaults()``
affirme poser ses garde-fous « pour couvrir AUSSI les jobs enregistrés
ailleurs ». C'est faux : un ``job_defaults`` appartient à SON instance de
planificateur. Or ``main.py`` construisait deux ``AsyncIOScheduler()`` nus
— celui du vault et celui de la mémoire — soit vingt crons qui héritaient
du ``misfire_grace_time = 1 s`` d'APScheduler.

Le mécanisme, vérifié plutôt que supposé. Les deux planificateurs tournent
sur le ``MemoryJobStore`` par défaut : après un redémarrage du conteneur,
les jobs sont ré-ajoutés à neuf et leur ``next_run_time`` repart de
maintenant — un redémarrage ne peut donc PAS créer d'occurrence manquée.
Ce qui en crée une, c'est une boucle événementielle réveillée en retard
(processus gelé, machine suspendue, boucle saturée). Passé une seconde de
retard, l'occurrence était abandonnée : le sauvetage SQLite de 02:30 ne
repassait qu'au lendemain. Et elle laissait bien une trace — APScheduler
journalise « Run time of job … was missed by … » en WARNING sur
``apscheduler.executors.default``. Ce qui manquait n'était pas le log,
c'était le RATTRAPAGE.

⚠️ Nuance mesurée en écrivant ce test : les deux autres garde-fous
(``coalesce``, ``max_instances = 1``) valaient déjà ça par défaut chez
APScheduler 3.11. Le seul vrai trou était le rattrapage. On épingle
quand même les trois : ce sont les défauts d'une bibliothèque tierce, pas
un contrat.

Run with:  cd backend && python -m pytest tests/test_planificateurs_maintenance_garde_fous.py -v
"""
from __future__ import annotations

import pytest

FABRIQUES = ["_build_vault_scheduler", "_build_memory_scheduler"]

# Les crons attendus, fabrique par fabrique. Ce recensement vaut filet pour
# le déplacement de ces enregistrements hors du `lifespan` : un cron perdu
# en route ne se voit sinon qu'en production, des mois plus tard.
CRONS_ATTENDUS = {
    "_build_vault_scheduler": {
        "vault_auto_lock",
        "oauth_state_cleanup",
        "credential_store_eviction",
        "watched_folders_autoindex",
    },
    "_build_memory_scheduler": {
        # 02/09/2026 — l'extraction de faits est passée du fil du chat à une
        # passe quotidienne (02:45, avant la consolidation de 03:00).
        "memory_extraction_daily",
        "memory_consolidation_night",
        "memory_consolidation_afternoon",
        "qdrant_backup",
        "sqlite_backup",
        "uploads_purge",
        "signals_retention",
        "reversible_journal_purge",
        "browser_idle_cleanup",
        "mission_critic_loop",
        "execution_diagnostician_loop",
        "purge_revoked_tokens",
        "learned_skills_curator",
        "anticipation_cycle",
        "model_metadata_refresh",
        "learned_skills_autocreate",
        "mission_heartbeat",
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("fabrique", FABRIQUES)
async def test_chaque_cron_de_maintenance_herite_du_rattrapage(fabrique):
    """Tout job des deux planificateurs porte les garde-fous du dépôt."""
    import app.main as main
    from app.config import get_settings

    scheduler = getattr(main, fabrique)()
    # `start(paused=True)` matérialise les jobs en attente sans armer le
    # moindre réveil : c'est le seul moment où APScheduler recopie
    # `job_defaults` sur les jobs. Un job « pending » n'a même pas encore
    # l'attribut `misfire_grace_time`.
    scheduler.start(paused=True)
    try:
        jobs = scheduler.get_jobs()
        assert jobs, f"{fabrique} n'enregistre aucun job"

        grace_attendue = get_settings().scheduler_misfire_grace_seconds
        for job in jobs:
            assert job.misfire_grace_time == grace_attendue, (
                f"{job.id} garde le misfire_grace_time d'APScheduler "
                f"({job.misfire_grace_time} s) : une occurrence manquée de "
                f"plus d'une seconde serait abandonnée sans rattrapage"
            )
            assert job.coalesce is True, (
                f"{job.id} rejouerait toutes les occurrences en retard"
            )
            assert job.max_instances == 1, (
                f"{job.id} peut se superposer à lui-même"
            )
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.parametrize("fabrique", FABRIQUES)
def test_les_garde_fous_viennent_du_helper_partage(fabrique):
    """Une évolution de ``_job_defaults`` doit atteindre ces planificateurs.

    Recopier les trois valeurs à la main passerait le test précédent tout
    en laissant les crons de maintenance diverger au prochain réglage.
    """
    import app.main as main
    from app.services.scheduler import _job_defaults

    scheduler = getattr(main, fabrique)()
    assert scheduler._job_defaults == _job_defaults()


@pytest.mark.parametrize("fabrique", FABRIQUES)
def test_aucun_cron_perdu_en_sortant_du_lifespan(fabrique):
    import app.main as main

    scheduler = getattr(main, fabrique)()
    assert {job.id for job in scheduler.get_jobs()} == CRONS_ATTENDUS[fabrique]
