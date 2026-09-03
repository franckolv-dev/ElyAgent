# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_procedure_perimee_nest_pas_reecrite.py
# @brief      43 compétences périmées sur 98 : arrêter d'en fabriquer d'autres.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le motif qui a déjà tué une procédure n'en mérite pas une seconde (02/09).

LA MESURE, cinq mois de production : 98 compétences apprises, dont 43
PÉRIMÉES et 13 archivées. Le curateur fait passer ``active → stale →
archived`` ce qui ne sert pas — mais rien n'empêchait le rédacteur de
réécrire, pour le MÊME ``pattern_hash``, une procédure jumelle de celle qui
venait de mourir sans avoir servi une seule fois.

C'est la boucle qui produit le stock : un motif d'échec se reproduit, un
nouveau ``failure_case`` est consigné, le lot nocturne le regroupe, une
procédure de plus est rédigée puis périmée. Le rédacteur payait du tier-S à
chaque tour de roue.

⚠️ CE QUE CE GARDE NE FAIT PAS
--------------------------------
Il ne supprime RIEN. Les 43 procédures périmées appartiennent à
l'utilisateur ; ``skill_curator`` les archive, jamais ne les efface, et ce
lot ne change pas cela. Le garde porte uniquement sur la FABRICATION de
nouvelles.

Il ne bloque pas non plus une procédure qui a SERVI : ``use_count > 0``
signifie qu'elle a été rendue au moins une fois, donc que le motif est
couvrable par un document. Périmée après usage, elle mérite d'être réécrite.

Run with:  cd backend && python -m pytest tests/test_une_procedure_perimee_nest_pas_reecrite.py -v
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from tests._user_cleanup import purge_user

_MOTIF = "hh" * 8


@pytest_asyncio.fixture
async def _utilisateur():
    from app.database import async_session, init_db
    from app.models.user import User

    await init_db()
    uid = f"per-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"per_{uid}", email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()
    yield uid
    await purge_user(uid)


async def _procedure(uid: str, *, statut: str, usages: int,
                     nom: str = "classer-les-devis") -> str:
    from app.database import async_session
    from app.models.learned_skill import LearnedSkill, SkillSource

    sid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(LearnedSkill(
            id=sid, user_id=uid, name=nom,
            description="d", content="# procédure",
            status=statut, source=SkillSource.AUTO_GENERATED,
            use_count=usages,
        ))
        await db.commit()
    return sid


async def _cas(uid: str, *, traite: bool, skill_id: str | None = None,
               famille: str | None = None) -> int:
    """Un `failure_case`. Famille par défaut : celle de « Capacités manquantes ».

    ⚠️ 02/09/2026 — le helper écrivait ``signal_table="tool_absent_acknowledged"``.
    C'est le ``signal_kind`` du PAYLOAD, pas la valeur de la colonne : la vraie
    constante est ``SIGNAL_TOOL_ABSENT = "tool_absent"``. Les lignes fabriquées
    ici n'auraient donc JAMAIS paru dans la vue que ces tests prétendent juger.
    """
    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.services.learning.failure_capture import SIGNAL_TOOL_ABSENT

    async with async_session() as db:
        fc = FailureCase(
            user_id=uid, signal_table=famille or SIGNAL_TOOL_ABSENT, signal_id=1,
            replay_payload=json.dumps({"capability": "classer les devis"}),
            pattern_hash=_MOTIF,
            processed_at=datetime.now(timezone.utc) if traite else None,
            learned_skill_id=skill_id,
        )
        db.add(fc)
        await db.commit()
        return fc.id


async def _est_traite(case_id: int) -> bool:
    from app.database import async_session
    from app.models.failure_case import FailureCase

    async with async_session() as db:
        return (await db.get(FailureCase, case_id)).processed_at is not None


@pytest.mark.asyncio
async def test_le_lot_ne_reecrit_pas_une_procedure_morte_sans_avoir_servi(
    _utilisateur, monkeypatch,
):
    """LE test du garde : même motif, procédure archivée à zéro usage → on ne
    paie pas un second tier-S pour refabriquer ce qui vient de périmer.

    Famille `mission_critiques` : le classement du lot nocturne ne vaut QUE
    hors « Capacités manquantes » (02/09/2026). Un `tool_absent` classé sans
    procédure quitterait la vue où l'utilisateur garde la main — c'est le
    défaut que pinne `test_le_lot_nocturne_ne_classe_pas_un_manque`.
    """
    from app.models.learned_skill import SkillStatus
    from app.services.learning import skill_creator
    from app.services.learning.failure_capture import SIGNAL_MISSION_CRITIQUE

    ancienne = await _procedure(_utilisateur, statut=SkillStatus.ARCHIVED, usages=0)
    await _cas(_utilisateur, traite=True, skill_id=ancienne,
               famille=SIGNAL_MISSION_CRITIQUE)
    nouveau = await _cas(_utilisateur, traite=False, famille=SIGNAL_MISSION_CRITIQUE)

    redactions: list = []

    async def _redige(cluster, user_id):
        redactions.append(cluster)
        raise AssertionError("le rédacteur n'aurait pas dû être appelé")

    monkeypatch.setattr(skill_creator, "_draft_skill_for_cluster", _redige)

    resume = await skill_creator.run_skill_creator_batch(user_id=_utilisateur)

    assert redactions == [], "une procédure jumelle a été rédigée pour un motif périmé"
    assert resume["skills_created"] == 0
    assert await _est_traite(nouveau), (
        "le cas reste non traité : le lot le représentera à chaque tick et "
        "occupera la place d'un motif jamais vu"
    )


@pytest.mark.asyncio
async def test_un_motif_dont_la_procedure_a_servi_est_toujours_redige(
    _utilisateur, monkeypatch,
):
    """Le pendant : une procédure périmée APRÈS avoir servi prouve que le motif
    se couvre par un document. Le garde ne doit pas la condamner."""
    from app.models.learned_skill import SkillStatus
    from app.services.learning import skill_creator

    ancienne = await _procedure(_utilisateur, statut=SkillStatus.STALE, usages=4)
    await _cas(_utilisateur, traite=True, skill_id=ancienne)
    await _cas(_utilisateur, traite=False)

    redactions: list = []

    async def _redige(cluster, user_id):
        redactions.append(cluster)
        return None, {"status": "no_provider", "case_ids": [c.id for c in cluster]}

    monkeypatch.setattr(skill_creator, "_draft_skill_for_cluster", _redige)

    await skill_creator.run_skill_creator_batch(user_id=_utilisateur)

    assert len(redactions) == 1, "le garde bloque un motif dont la procédure servait"


@pytest.mark.asyncio
async def test_le_manque_consigne_ne_refabrique_pas_non_plus(_utilisateur, monkeypatch):
    """Le chemin du manque (``draft_playbook_for_gap``) partage le garde.

    C'est celui que la fabrique gelée emprunte désormais à chaque capacité
    absente : sans garde, geler la fabrique multiplierait les procédures au
    lieu de les remplacer.

    ⚠️ Ce test exigeait aussi que le cas soit CLASSÉ (02/09/2026, relecture) —
    c'était l'erreur : le manque quittait alors la vue par défaut des
    « Capacités manquantes » sans qu'aucune procédure ne le comble. Le partage
    du garde s'arrête à la non-réécriture ; le sort du cas est pinné par
    ``test_le_manque_reste_dans_les_capacites_manquantes``.
    """
    from app.models.learned_skill import SkillStatus
    from app.services.learning import skill_creator

    ancienne = await _procedure(_utilisateur, statut=SkillStatus.ARCHIVED, usages=0)
    await _cas(_utilisateur, traite=True, skill_id=ancienne)
    nouveau = await _cas(_utilisateur, traite=False)

    async def _redige(cluster, user_id):
        raise AssertionError("le rédacteur n'aurait pas dû être appelé")

    monkeypatch.setattr(skill_creator, "_draft_skill_for_cluster", _redige)

    resultat = await skill_creator.draft_playbook_for_gap(nouveau, _utilisateur)

    assert resultat["status"] == "deja_perimee", resultat


# ─────────────────────────────────────────────────────────────────────
# Correctifs de relecture (02/09/2026)
# ─────────────────────────────────────────────────────────────────────


async def _gaps_ouverts(uid: str) -> list[int]:
    """Ce que rend la vue par défaut de « Capacités manquantes ».

    Même filtre que ``GET /admin/learning/tool-gaps`` (``status=open``, la
    valeur par défaut du routeur ET de la page front) : un cas marqué traité
    disparaît de l'écran où l'utilisateur garde la main.
    """
    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase

    from app.services.learning.failure_capture import SIGNAL_TOOL_ABSENT

    async with async_session() as db:
        return list((await db.execute(
            select(FailureCase.id).where(
                FailureCase.user_id == uid,
                # ⚠️ 02/09/2026 — ce filtre manquait. Le routeur ne montre que
                # la famille `tool_absent` ; sans lui, ce helper affirmait
                # rejouer une vue qu'il ne rejouait pas.
                FailureCase.signal_table == SIGNAL_TOOL_ABSENT,
                FailureCase.processed_at.is_(None),
            )
        )).scalars().all())


@pytest.mark.asyncio
async def test_le_manque_reste_dans_les_capacites_manquantes(
    _utilisateur, monkeypatch,
):
    """⚠️ LE GARDE FAISAIT DISPARAÎTRE LE MANQUE DE L'ÉCRAN.

    Sur le chemin du MANQUE, classer le cas le sortait de la vue par défaut
    (``processed_at IS NULL``) sans rien écrire en échange : ni procédure, ni
    ``learned_skill_id``, ni motif. `find_tool` venait de répondre « une
    procédure est en cours de rédaction », et le manque s'évaporait — alors
    que c'est le chemin que la fabrique gelée emprunte à CHAQUE capacité
    absente. Le garde était en plus définitif : un motif dont la première
    procédure est morte à zéro usage ne serait plus jamais rédigé ni montré,
    même en se représentant cinquante fois.

    Le lot nocturne, lui, garde son classement : il sert à ne pas re-occuper
    une des N places du lot. Ici rien n'est à protéger — la dédup de
    ``record_tool_absent`` (sur les cas NON traités) et ``_attempted_cases``
    bornent déjà les reprises.
    """
    from app.models.learned_skill import SkillStatus
    from app.services.learning import skill_creator

    ancienne = await _procedure(_utilisateur, statut=SkillStatus.ARCHIVED, usages=0)
    await _cas(_utilisateur, traite=True, skill_id=ancienne)
    nouveau = await _cas(_utilisateur, traite=False)

    async def _redige(cluster, user_id):
        raise AssertionError("le rédacteur n'aurait pas dû être appelé")

    monkeypatch.setattr(skill_creator, "_draft_skill_for_cluster", _redige)

    resultat = await skill_creator.draft_playbook_for_gap(nouveau, _utilisateur)

    assert resultat["status"] == "deja_perimee", resultat
    assert nouveau in await _gaps_ouverts(_utilisateur), (
        "le manque a quitté la vue par défaut des « Capacités manquantes » "
        "sans qu'aucune procédure ne le comble : l'utilisateur n'a plus la main"
    )

    # ⚠️ L'INVARIANT NE TENAIT QUE 30 MINUTES (02/09/2026, 3e relecture).
    #
    # Épingler l'état juste après le draft ne prouvait rien : le cron
    # `learned_skills_autocreate` (main.py, 30 min) ramassait le MÊME cas —
    # `_fetch_unprocessed_cases` n'avait aucun filtre de famille —, retrouvait
    # le même motif et le classait par le chemin nocturne. Le manque quittait
    # la vue exactement comme avant, avec un simple délai.
    await skill_creator.run_skill_creator_batch(user_id=_utilisateur)

    assert nouveau in await _gaps_ouverts(_utilisateur), (
        "le lot nocturne a classé le manque au tick suivant : l'invariant ne "
        "tenait que jusqu'au prochain cron"
    )


@pytest.mark.asyncio
async def test_un_saut_delibere_nest_pas_compte_comme_une_erreur(monkeypatch):
    """La télémétrie du lot nocturne mentait sur le nouveau garde.

    Les entrées ``deja_perimee`` tombaient dans la branche « rien à évaluer »
    et incrémentaient ``errored`` : un saut VOULU se lisait comme une panne,
    et le garde aurait été jugé sur un compteur d'erreurs qui grimpe.
    """
    from app.services.learning import skill_orchestrator

    async def _lot(*, user_id, batch_size):
        return {
            "drafts": [
                {"status": "deja_perimee", "pattern_hash": _MOTIF},
                {"status": "parse_failed"},
            ],
            "skills_created": 0,
        }

    monkeypatch.setattr(skill_orchestrator, "run_skill_creator_batch", _lot)

    out = await skill_orchestrator.run_full_loop(user_id="u-tele", batch_size=3)

    assert out["totals"]["skipped"] == 1, (
        "le saut délibéré n'est compté nulle part — la télémétrie ne montre "
        "pas ce que fait le garde"
    )
    assert out["totals"]["errored"] == 1, (
        "un saut délibéré est compté comme une panne (seul `parse_failed` en "
        "est une)"
    )


@pytest.mark.asyncio
async def test_le_lot_nocturne_ne_classe_pas_un_manque(_utilisateur, monkeypatch):
    """Le chemin nocturne applique la règle du chemin du manque.

    Une ligne `tool_absent` EST une ligne de « Capacités manquantes ». La
    classer sans rien écrire en échange la sort de la vue par défaut ; le lot
    doit donc la sauter SANS la marquer, et l'exclure à la source pour qu'elle
    n'occupe pas non plus une des N places du lot.
    """
    from app.models.learned_skill import SkillStatus
    from app.services.learning import skill_creator

    ancienne = await _procedure(_utilisateur, statut=SkillStatus.ARCHIVED, usages=0)
    await _cas(_utilisateur, traite=True, skill_id=ancienne)
    nouveau = await _cas(_utilisateur, traite=False)

    async def _redige(cluster, user_id):
        raise AssertionError("le rédacteur n'aurait pas dû être appelé")

    monkeypatch.setattr(skill_creator, "_draft_skill_for_cluster", _redige)

    resume = await skill_creator.run_skill_creator_batch(user_id=_utilisateur)

    assert resume["skills_created"] == 0
    assert not await _est_traite(nouveau), (
        "le lot nocturne a classé un manque sans écrire de procédure : il "
        "quitte « Capacités manquantes » et personne ne le comble"
    )
    assert resume["clusters_processed"] == 0, (
        "le motif occupe encore une des N places du lot alors qu'aucune "
        "procédure ne peut en sortir"
    )


@pytest.mark.asyncio
async def test_une_candidate_non_tranchee_bloque_une_seconde_procedure(
    _utilisateur, monkeypatch,
):
    """⚠️ LA THÈSE DU LOT, RESTÉE OUVERTE.

    Le garde ne regardait que `stale` et `archived`, et `skill_curator` ne
    fait transiter que `active → stale → archived` : une CANDIDATE jamais
    validée ne devient donc JAMAIS périmée. Or la fabrique gelée écrit une
    candidate à chaque manque et pose `processed_at` — à la récurrence
    suivante, `record_tool_absent` (qui ne dédoublonne que sur les cas NON
    traités) crée un cas neuf, et une seconde procédure part pour le même
    motif sans que le garde ne la voie. Tant que l'humain ne tranche pas,
    geler la fabrique MULTIPLIAIT les procédures.
    """
    from app.models.learned_skill import SkillStatus
    from app.services.learning import skill_creator

    en_attente = await _procedure(
        _utilisateur, statut=SkillStatus.CANDIDATE, usages=0,
        nom="classer-les-devis-v1",
    )
    await _cas(_utilisateur, traite=True, skill_id=en_attente)
    recidive = await _cas(_utilisateur, traite=False)

    async def _redige(cluster, user_id):
        raise AssertionError("une seconde procédure a été rédigée pour le même motif")

    monkeypatch.setattr(skill_creator, "_draft_skill_for_cluster", _redige)

    resultat = await skill_creator.draft_playbook_for_gap(recidive, _utilisateur)

    assert resultat["status"] == "candidate_en_attente", resultat
    assert resultat["procedure_en_attente"] == "classer-les-devis-v1"
    assert recidive in await _gaps_ouverts(_utilisateur), (
        "le manque quitte la vue alors que la candidate attend encore une "
        "décision humaine"
    )

    await skill_creator.run_skill_creator_batch(user_id=_utilisateur)

    assert recidive in await _gaps_ouverts(_utilisateur), (
        "le lot nocturne a classé le manque au tick suivant"
    )


@pytest.mark.asyncio
async def test_une_candidate_tranchee_ne_bloque_plus(_utilisateur, monkeypatch):
    """Le pendant : le garde porte sur l'attente d'une décision, pas sur
    l'existence d'une procédure. Rejetée, la candidate ne bloque plus — sinon
    un motif refusé une fois ne serait plus jamais traité."""
    from app.models.learned_skill import SkillStatus
    from app.services.learning import skill_creator

    rejetee = await _procedure(_utilisateur, statut=SkillStatus.REJECTED, usages=0)
    await _cas(_utilisateur, traite=True, skill_id=rejetee)
    recidive = await _cas(_utilisateur, traite=False)

    redactions: list = []

    async def _redige(cluster, user_id):
        redactions.append(cluster)
        return None, {"status": "no_provider", "case_ids": [c.id for c in cluster]}

    monkeypatch.setattr(skill_creator, "_draft_skill_for_cluster", _redige)

    await skill_creator.draft_playbook_for_gap(recidive, _utilisateur)

    assert len(redactions) == 1, (
        "une candidate REJETÉE bloque encore : le motif n'aurait plus jamais "
        "de procédure"
    )


@pytest.mark.asyncio
async def test_une_candidate_en_attente_nest_pas_comptee_comme_une_panne(monkeypatch):
    """Même télémétrie que `deja_perimee` : un saut voulu n'est pas une erreur."""
    from app.services.learning import skill_orchestrator

    async def _lot(*, user_id, batch_size):
        return {
            "drafts": [{"status": "candidate_en_attente", "pattern_hash": _MOTIF}],
            "skills_created": 0,
        }

    monkeypatch.setattr(skill_orchestrator, "run_skill_creator_batch", _lot)

    out = await skill_orchestrator.run_full_loop(user_id="u-tele2", batch_size=3)

    assert out["totals"]["skipped"] == 1, (
        "attendre une décision humaine se lit comme une panne dans la télémétrie"
    )
    assert out["totals"]["errored"] == 0


@pytest.mark.asyncio
async def test_le_classement_nocturne_epargne_un_manque_dans_une_grappe_mixte(
    _utilisateur,
):
    """⚠️ LA SECONDE MOITIÉ DU GARDE N'ÉTAIT ÉPINGLÉE PAR RIEN (02/09/2026).

    Le lot tient deux gardes pour le même invariant : `_fetch_unprocessed_cases`
    écarte les `tool_absent` déjà pourvus à la SOURCE, et `_classer_sans_rediger`
    refuse de les CLASSER. Mesuré par mutation : retirer le filtre du classeur
    seul laissait la suite VERTE — le filtre de la source masquait le trou, et
    l'inverse aussi. Chacun était donc libre de disparaître sans qu'un test le
    dise.

    On exerce ici le classeur DIRECTEMENT, sur une grappe mixte : un
    `mission_critiques` (classable — il ne paraît pas dans « Capacités
    manquantes ») et un `tool_absent` (jamais classable sans procédure écrite
    en échange). Le second doit survivre au passage.
    """
    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.services.learning import skill_creator
    from app.services.learning.failure_capture import SIGNAL_MISSION_CRITIQUE

    critique = await _cas(_utilisateur, traite=False, famille=SIGNAL_MISSION_CRITIQUE)
    manque = await _cas(_utilisateur, traite=False)

    async with async_session() as db:
        grappe = list((await db.execute(
            select(FailureCase).where(FailureCase.id.in_([critique, manque]))
        )).scalars().all())

    classes = await skill_creator._classer_sans_rediger(grappe, "classer-les-devis")

    assert classes == [critique], (
        "le classeur a marqué un `tool_absent` traité : le manque quitte "
        "« Capacités manquantes » sans qu'aucune procédure ne le comble"
    )
    assert await _est_traite(critique), (
        "le classeur n'a plus classé le cas qu'il DOIT classer — le lot "
        "représentera ce motif à chaque tick"
    )
    assert manque in await _gaps_ouverts(_utilisateur)
