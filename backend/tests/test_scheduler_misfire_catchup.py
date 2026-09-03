# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_scheduler_misfire_catchup.py
# @brief      V0-1 — une occurrence manquée ne doit plus disparaître en silence :
#             rattrapage borné au redémarrage + garde-fous APScheduler explicites.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du rattrapage d'occurrence manquée (audit Opus 5 §4.6).

Le symptôme mesuré : « une tâche "chaque matin à 6 h" peut ne jamais tourner
sans qu'aucune trace ne l'indique ». Trois causes cumulées :

1. ``misfire_grace_time`` implicite à **1 seconde** — un simple hoquet de
   boucle d'événements suffit à faire sauter l'occurrence.
2. Aucun ``coalesce`` / ``max_instances`` explicites.
3. Surtout : **aucun rattrapage au redémarrage**. Le conteneur redémarre à
   9 h, l'occurrence de 6 h est simplement perdue.

⚠️ Pourquoi PAS le jobstore SQLAlchemy que préconisait l'audit : vérifié sur
APScheduler 3.11.2, ``BaseScheduler._real_add_job`` recalcule
``next_run_time`` depuis *maintenant* quand le job n'en porte pas, puis
``store.update_job()`` écrase la ligne persistée. Or ``load_and_schedule_tasks``
ré-enregistre CHAQUE tâche avec ``replace_existing=True`` à chaque boot — le
``next_run_time`` passé serait donc écrasé à tous les démarrages, et le
rattrapage n'aurait jamais lieu. La source de vérité utilisable est
``ScheduledTask.last_run_at``, déjà persistée.

Run with:  cd backend && python -m pytest tests/test_scheduler_misfire_catchup.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from app.models.scheduled_task import ScheduledTask
from app.models.user import User

PARIS = ZoneInfo("Europe/Paris")


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


# ---------------------------------------------------------------- unit: calcul

def test_missed_daily_occurrence_is_detected():
    """Tâche « tous les jours à 6 h », dernière exécution hier, il est 9 h :
    l'occurrence de 6 h ce matin a été manquée et doit être rattrapée."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 9, 0, tzinfo=PARIS)
    last_run = datetime(2026, 7, 24, 6, 0, tzinfo=PARIS)

    missed = compute_catchup_run("0 6 * * *", last_run, now=now)

    assert missed == datetime(2026, 7, 25, 6, 0, tzinfo=PARIS)


def test_no_catchup_when_occurrence_already_ran():
    """L'occurrence de 6 h a bien tourné : rien à rattraper."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 9, 0, tzinfo=PARIS)
    last_run = datetime(2026, 7, 25, 6, 0, tzinfo=PARIS)

    assert compute_catchup_run("0 6 * * *", last_run, now=now) is None


def test_no_catchup_when_next_occurrence_is_still_ahead():
    """Il est 5 h, l'occurrence de 6 h n'est pas encore due."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 5, 0, tzinfo=PARIS)
    last_run = datetime(2026, 7, 24, 6, 0, tzinfo=PARIS)

    assert compute_catchup_run("0 6 * * *", last_run, now=now) is None


def test_several_missed_occurrences_coalesce_into_one():
    """Conteneur éteint 3 jours → UNE seule exécution de rattrapage (la plus
    récente), jamais trois. C'est le `coalesce` appliqué au redémarrage."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 9, 0, tzinfo=PARIS)
    last_run = datetime(2026, 7, 22, 6, 0, tzinfo=PARIS)

    missed = compute_catchup_run(
        "0 6 * * *", last_run, now=now, max_age=timedelta(days=7)
    )

    assert missed == datetime(2026, 7, 25, 6, 0, tzinfo=PARIS)


def test_catchup_is_bounded_by_max_age():
    """Une occurrence manquée il y a 5 jours ne se réveille pas toute seule
    au retour de vacances : au-delà de l'horizon, on n'exécute pas."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 9, 0, tzinfo=PARIS)
    last_run = datetime(2026, 7, 1, 6, 0, tzinfo=PARIS)

    missed = compute_catchup_run(
        "0 6 * * *", last_run, now=now, max_age=timedelta(hours=24)
    )

    # La dernière occurrence due (25/07 06:00) est dans l'horizon de 24 h.
    assert missed == datetime(2026, 7, 25, 6, 0, tzinfo=PARIS)

    # ... mais si l'horizon est plus court que le retard, on ne rattrape pas.
    assert compute_catchup_run(
        "0 6 * * *", last_run, now=now, max_age=timedelta(hours=2)
    ) is None


def test_missed_oneshot_never_run_is_detected():
    """« Rappelle-moi jeudi 10 h » pendant que le conteneur était éteint :
    le one-shot est rattrapé (il n'a jamais tourné)."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 9, 0, tzinfo=PARIS)

    missed = compute_catchup_run(
        "@once 2026-07-25T07:30", None, now=now, created_at=datetime(2026, 7, 24, 8, 0, tzinfo=PARIS)
    )

    assert missed == datetime(2026, 7, 25, 7, 30, tzinfo=PARIS)


def test_never_run_task_uses_created_at_as_floor():
    """Une tâche jamais exécutée ne rattrape pas les occurrences ANTÉRIEURES
    à sa création."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 9, 0, tzinfo=PARIS)
    created = datetime(2026, 7, 25, 7, 0, tzinfo=PARIS)  # créée APRÈS 6 h

    assert compute_catchup_run(
        "0 6 * * *", None, now=now, created_at=created
    ) is None


def test_invalid_cron_never_raises():
    """Une expression invalide ne doit pas casser le démarrage."""
    from app.services.scheduler import compute_catchup_run

    now = datetime(2026, 7, 25, 9, 0, tzinfo=PARIS)
    assert compute_catchup_run("n importe quoi", None, now=now) is None


# --------------------------------------------------- intégration : add_job

@pytest.mark.asyncio
async def test_jobs_are_registered_with_explicit_misfire_guards():
    """Les garde-fous ne sont plus implicites : grâce explicite, coalesce,
    une seule instance concurrente. (Le défaut APScheduler était 1 seconde.)"""
    from app.config import get_settings
    from app.services import scheduler as sched

    task = ScheduledTask(
        id=str(uuid.uuid4()), user_id="u1", name="Briefing",
        prompt="briefing", cron_expression="0 6 * * *", channel="web",
    )
    sched._scheduler = None
    scheduler = sched.get_scheduler()
    scheduler.start()  # sinon les jobs restent « pending » et get_job rend None
    try:
        assert sched.schedule_task(task) is True
        job = scheduler.get_job(f"task_{task.id}")
        assert job is not None
        assert job.misfire_grace_time == get_settings().scheduler_misfire_grace_seconds
        assert job.misfire_grace_time > 1, "le défaut APScheduler (1 s) perd les occurrences"
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        scheduler.shutdown(wait=False)
        sched._scheduler = None


@pytest.mark.asyncio
async def test_restart_schedules_a_catchup_job_for_a_missed_occurrence():
    """LE test du lot : au redémarrage, une occurrence manquée produit un job
    de rattrapage — au lieu de disparaître en silence."""
    from app.database import async_session
    from app.services import scheduler as sched

    async with async_session() as db:
        user = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(user)
        await db.flush()
        task = ScheduledTask(
            id=str(uuid.uuid4()), user_id=user.id, name="Briefing du matin",
            prompt="briefing", cron_expression="0 6 * * *", channel="web",
            enabled=True,
            # A tourné il y a 3 jours → les occurrences suivantes ont été manquées.
            # (colonne DateTime naïve : la base stocke de l'UTC sans tzinfo)
            last_run_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3),
        )
        db.add(task)
        await db.commit()

    sched._scheduler = None
    try:
        await sched.load_and_schedule_tasks()
        scheduler = sched.get_scheduler()
        assert scheduler.get_job(f"task_{task.id}") is not None, "cron normal absent"
        catchup = scheduler.get_job(f"catchup_{task.id}")
        assert catchup is not None, "aucun job de rattrapage pour l'occurrence manquée"
        # Le job porte MAINTENANT l'occurrence manquée en second argument.
        # Sans elle, `_execute_task` rejouait le prompt à l'identique et la
        # tâche croyait être à l'heure : c'est ce qui a fait rendre [SILENT] à
        # « Propositions LinkedIn » un jeudi soir pour une consigne qui
        # commençait par « Nous sommes un mercredi matin » (06/08).
        args = list(catchup.args)
        assert args[0] == task.id
        assert len(args) == 2, (
            "le rattrapage doit transmettre l'occurrence manquée, sinon il se "
            "fait passer pour une exécution à l'heure"
        )
        assert args[1] and args[1].startswith("20"), (
            f"second argument attendu : un ISO de date, vu {args[1]!r}"
        )
    finally:
        if sched._scheduler is not None and sched._scheduler.running:
            sched._scheduler.shutdown(wait=False)
        sched._scheduler = None


@pytest.mark.asyncio
async def test_restart_does_not_catch_up_a_task_that_just_ran():
    """Pas de rattrapage intempestif : une tâche qui vient de tourner ne
    redémarre pas au boot."""
    from app.database import async_session
    from app.services import scheduler as sched

    async with async_session() as db:
        user = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(user)
        await db.flush()
        task = ScheduledTask(
            id=str(uuid.uuid4()), user_id=user.id, name="Briefing frais",
            prompt="briefing", cron_expression="0 6 * * *", channel="web",
            enabled=True,
            last_run_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
        )
        db.add(task)
        await db.commit()

    sched._scheduler = None
    try:
        await sched.load_and_schedule_tasks()
        assert sched.get_scheduler().get_job(f"catchup_{task.id}") is None
    finally:
        if sched._scheduler is not None and sched._scheduler.running:
            sched._scheduler.shutdown(wait=False)
        sched._scheduler = None
