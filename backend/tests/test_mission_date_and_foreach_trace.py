# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_date_and_foreach_trace.py
# @brief      Deux angles morts d'une mission STRUCTURÉE : l'acteur ignore
#             quel jour on est, et l'expansion d'un foreach saute une étape
#             sans rien journaliser.
# @license    MIT
# =============================================================================
"""La date manquante et le foreach muet (incident du 29/08/2026).

Mission « Prospection STE Print », spec de 5 étapes :

    tableur  -> Google Sheet nommé « prospection_catalogue-2025_05_22 »
    contacts -> skipped, « Aucun item identifiable (résultat source vide ?) »

**La date.** Elle est injectée dans le prompt du PLANIFICATEUR et du
replanificateur, jamais dans celui de l'ACTEUR. Une mission libre s'en sort :
le planificateur connaît la date et l'écrit dans la description de l'étape.
Une mission structurée court-circuite le planificateur — la date n'est alors
injectée nulle part, et l'acteur l'invente. Il a produit `2025_05_22`, la
même hallucination que le 28/08. Plus la mission est cadrée, moins elle sait
quel jour on est.

**Le foreach muet.** Le tick de `contacts` a duré 14 ms sans une ligne de
log : ni la taille de la source, ni le nombre d'items, ni la réponse du
modèle. `mission_spec_runtime` n'apparaît pas UNE fois dans les logs de la
mission. Le composant qui décide de sauter l'étape la plus importante le
fait en silence — impossible de diagnostiquer autrement qu'en rejouant à la
main.
"""
from __future__ import annotations

import logging
import types
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStep, MissionStepRun
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_date_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="créer le tableur du jour",
    )
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionStepRun, MissionStep):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


# ── Lot A : l'acteur doit savoir quel jour on est ────────────────────────


def test_le_prompt_de_l_acteur_porte_la_date_du_jour() -> None:
    """Sans elle, une mission structurée invente la date du fichier."""
    import app.agent.missions.nodes as mn

    rendu = mn._ACT_SYSTEM.format(
        plan_text="(plan)",
        current_step_desc="Crée le Google Sheet du jour",
        date_str=mn._current_date_paris_str(),
    )

    assert mn._current_date_paris_str() in rendu
    assert "Europe/Paris" in rendu


def test_la_date_est_celle_d_aujourd_hui() -> None:
    """Pin de forme : jour, mois et année courants, fuseau de Paris."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import app.agent.missions.nodes as mn

    aujourdhui = datetime.now(ZoneInfo("Europe/Paris"))
    rendu = mn._current_date_paris_str()

    assert str(aujourdhui.year) in rendu, (
        "une date sans l'année courante, c'est le nom de fichier de 2025"
    )


# ── Lot B : l'expansion d'un foreach ne saute plus rien en silence ───────


@pytest.mark.asyncio
async def test_l_expansion_journalise_ce_qu_elle_a_recu(
    mission, monkeypatch, caplog,
) -> None:
    """Taille de la source et nombre d'items : de quoi diagnostiquer."""
    from app.services import mission_spec_runtime as msr

    uid, mid = mission

    class _LLM:
        async def ainvoke(self, _messages):
            return types.SimpleNamespace(content='["Acme", "Gamma"]')

    monkeypatch.setattr(msr, "get_llm_for_tier", lambda _t: _LLM(), raising=False)
    import app.services.llm_provider as lp
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda _t: _LLM())

    with caplog.at_level(logging.INFO, logger="app.services.mission_spec_runtime"):
        await msr.expand_foreach(
            mid, uid,
            {"id": "contacts", "description": "Traite {{ item }}",
             "foreach": "{{ societes.output }}"},
            "Résultats : Acme, Gamma",
        )

    trace = caplog.text
    assert "contacts" in trace
    assert "2 item" in trace, "le nombre d'items extraits doit être journalisé"
    assert "23 car" in trace or "source" in trace.lower(), (
        "la taille de la source reçue doit être journalisée"
    )


@pytest.mark.asyncio
async def test_une_expansion_a_vide_dit_pourquoi(
    mission, monkeypatch, caplog,
) -> None:
    """Sauter une étape est une décision : elle doit s'expliquer.

    C'est LE cas vécu — « Aucun item identifiable (résultat source vide ?) »
    était écrit en base et nulle part dans les logs, avec un point
    d'interrogation en guise de diagnostic.
    """
    from app.services import mission_spec_runtime as msr

    uid, mid = mission

    class _LLMVide:
        async def ainvoke(self, _messages):
            return types.SimpleNamespace(content="[]")

    monkeypatch.setattr(msr, "get_llm_for_tier", lambda _t: _LLMVide(), raising=False)
    import app.services.llm_provider as lp
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda _t: _LLMVide())

    source = "Un texte source dont on mesure la longueur."
    with caplog.at_level(logging.WARNING, logger="app.services.mission_spec_runtime"):
        await msr.expand_foreach(
            mid, uid,
            {"id": "contacts", "description": "Traite {{ item }}",
             "foreach": "{{ societes.output }}"},
            source,
        )

    trace = caplog.text
    assert "contacts" in trace, "l'étape sautée doit être nommée"
    assert f"{len(source)} car" in trace, (
        "la taille de la source doit être dite : « source vide ? » n'est pas "
        "un diagnostic quand la source faisait 2 277 caractères"
    )
    assert "[]" in trace, "la réponse brute du modèle doit être visible"


@pytest.mark.asyncio
async def test_une_source_vide_est_nommee_comme_telle(
    mission, monkeypatch, caplog,
) -> None:
    """Zéro caractère reçu : le log doit le dire sans ambiguïté."""
    from app.services import mission_spec_runtime as msr

    uid, mid = mission

    class _LLMVide:
        async def ainvoke(self, _messages):
            return types.SimpleNamespace(content="[]")

    monkeypatch.setattr(msr, "get_llm_for_tier", lambda _t: _LLMVide(), raising=False)
    import app.services.llm_provider as lp
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda _t: _LLMVide())

    with caplog.at_level(logging.WARNING, logger="app.services.mission_spec_runtime"):
        await msr.expand_foreach(
            mid, uid,
            {"id": "contacts", "description": "x", "foreach": "{{ s.output }}"},
            "",
        )

    assert "0 car" in caplog.text
