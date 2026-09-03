# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_spec.py
# @brief      Sprint 4c J1 — format de mission structurée V2 : parser,
#             validation exhaustive, colonne spec_yaml, API de création.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Sprint 4c J1 — pins du contrat de spec structurée."""
from __future__ import annotations

import textwrap
import uuid

import pytest

# Le cas canonique du backlog (prospection LinkedIn de Franck) — si CE
# document ne parse pas, le sprint rate sa cible.
_CANONICAL = textwrap.dedent("""
    version: 1
    steps:
      - id: read_companies
        do: "Lis les noms d'entreprises du Google Sheet « Prospection »."

      - id: enrich_company
        foreach: "{{ read_companies.output }}"
        do: |
          Trouve le dirigeant de {{ item }} sur LinkedIn et récupère
          nom + email professionnel.
        on_ambiguous: ask_user("Plusieurs résultats pour {{ item }} — lequel ?")
        on_not_found: skip_with_note("Entreprise introuvable")
        on_in_liquidation: ask_user("{{ item }} est en redressement — continuer ?")
        on_error: resume_next
""").strip()


# ─────────────────────────────────────────────────────────────────────────
# Parser — chemin nominal
# ─────────────────────────────────────────────────────────────────────────


def test_canonical_spec_parses() -> None:
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(_CANONICAL)

    assert spec.version == 1
    assert spec.step_ids() == ["read_companies", "enrich_company"]

    enrich = spec.steps[1]
    assert enrich.foreach_ref == "read_companies"
    assert enrich.handlers["ambiguous"].action == "ask_user"
    assert "lequel" in enrich.handlers["ambiguous"].message
    assert enrich.handlers["not_found"].action == "skip_with_note"
    # Edge-case métier LIBRE — le vocabulaire des cas n'est pas fermé,
    # seules les ACTIONS le sont.
    assert enrich.handlers["in_liquidation"].action == "ask_user"
    assert enrich.handlers["error"].action == "resume_next"
    assert enrich.handlers["error"].message is None


def test_handler_mapping_form_equivalent_to_sugar() -> None:
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(textwrap.dedent("""
        version: 1
        steps:
          - id: s1
            do: "fais un truc"
            on_ambiguous:
              action: ask_user
              message: "lequel ?"
    """))
    call = spec.steps[0].handlers["ambiguous"]
    assert call.action == "ask_user" and call.message == "lequel ?"


def test_foreach_free_text_is_allowed() -> None:
    """La forme texte libre (« chaque ligne du Sheet ») est légitime — le
    LLM l'interprète à l'exécution. Seule la forme {{ ref }} est validée
    structurellement."""
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(textwrap.dedent("""
        version: 1
        steps:
          - id: s1
            foreach: "chaque ligne du fichier clients.csv"
            do: "traite {{ item }}"
    """))
    assert spec.steps[0].foreach_ref is None
    assert spec.steps[0].foreach.startswith("chaque ligne")


# ─────────────────────────────────────────────────────────────────────────
# Parser — erreurs (exhaustives, en une passe, en français)
# ─────────────────────────────────────────────────────────────────────────


def test_all_errors_collected_in_one_pass() -> None:
    """Le cycle de douleur du backlog = corriger, relancer, re-planter sur
    l'erreur SUIVANTE. Le parser doit tout dire d'un coup."""
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    bad = textwrap.dedent("""
        version: 7
        steps:
          - id: Bad-Id
            do: ""
            on_ambiguous: explode("boom")
          - id: s2
            do: "ok"
            foreach: "{{ nope.output }}"
            on_not_found: ask_user()
    """)
    with pytest.raises(MissionSpecError) as exc_info:
        parse_mission_spec(bad)

    errors = "\n".join(exc_info.value.errors)
    assert "version" in errors                      # version inconnue
    assert "snake_case" in errors                   # Bad-Id
    assert "'do' requis" in errors                  # do vide
    assert "action inconnue 'explode'" in errors    # action hors vocabulaire
    assert "ask_user exige un message" in errors
    assert "nope" in errors                         # foreach vers step inexistant
    assert len(exc_info.value.errors) >= 5


def test_duplicate_ids_and_forward_foreach_rejected() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc_info:
        parse_mission_spec(textwrap.dedent("""
            version: 1
            steps:
              - id: s1
                foreach: "{{ s2.output }}"
                do: "itère sur un step FUTUR — interdit"
              - id: s1
                do: "id dupliqué"
        """))
    errors = "\n".join(exc_info.value.errors)
    assert "déjà utilisé" in errors
    assert "PRÉCÉDENT" in errors


def test_non_handler_unknown_key_rejected() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc_info:
        parse_mission_spec(textwrap.dedent("""
            version: 1
            steps:
              - id: s1
                do: "ok"
                retry_count: 3
        """))
    assert "on_" in "\n".join(exc_info.value.errors)


def test_invalid_yaml_and_empty_steps() -> None:
    from app.services.mission_spec import (
        MissionSpecError,
        parse_mission_spec,
        validate_mission_spec,
    )

    with pytest.raises(MissionSpecError):
        parse_mission_spec("steps: [unclosed")
    with pytest.raises(MissionSpecError):
        parse_mission_spec("version: 1\nsteps: []")
    # La variante non levante pour les endpoints
    assert validate_mission_spec(_CANONICAL) == []
    assert validate_mission_spec("version: 1\nsteps: []") != []


# ─────────────────────────────────────────────────────────────────────────
# Modèle + migration 0002
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mission_persists_spec_yaml(monkeypatch) -> None:
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.mission import Mission
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    # Même chemin que le boot prod : une base créée AVANT 4c n'a pas la
    # colonne — la révision 0002 l'ajoute (stamp baseline + upgrade).
    await ensure_migrations()
    uid = f"test_4c_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    try:
        m = await mission_service.create_mission(
            user_id=uid, title="Prospection", goal="prospecter",
            spec_yaml=_CANONICAL,
        )
        async with async_session() as db:
            row = (await db.execute(
                select(Mission).where(Mission.id == m.id)
            )).scalar_one()
        assert row.spec_yaml is not None and "read_companies" in row.spec_yaml

        # Défense en profondeur : le SERVICE refuse aussi une spec invalide
        # (les sources non-UI — Telegram, scheduler — passent par lui).
        with pytest.raises(ValueError):
            await mission_service.create_mission(
                user_id=uid, title="x", goal="y",
                spec_yaml="version: 1\nsteps: []",
            )

        # Rétrocompat : sans spec, mission legacy inchangée.
        legacy = await mission_service.create_mission(
            user_id=uid, title="Legacy", goal="prompt monolithe",
        )
        assert legacy.spec_yaml is None
    finally:
        async with async_session() as db:
            await db.execute(delete(Mission).where(Mission.user_id == uid))
            u = await db.get(User, uid)
            if u is not None:
                await db.delete(u)
            await db.commit()


@pytest.mark.asyncio
async def test_migration_0002_adds_column_to_legacy_db(tmp_path, monkeypatch) -> None:
    """Le piège d'adoption corrigé : une base EXISTANTE (table missions
    sans spec_yaml, jamais vue par Alembic) doit recevoir la colonne via
    stamp baseline + upgrade — pas être stampée head en sautant 0002."""
    import sqlite3
    import types

    import app.config as app_config
    from app.services import alembic_runner as ar

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY, goal TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        app_config, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{db_path}"),
    )

    assert await ar.ensure_migrations() == "stamped+upgraded"

    check = sqlite3.connect(db_path)
    cols = {r[1] for r in check.execute("PRAGMA table_info(missions)")}
    check.close()
    assert "spec_yaml" in cols, (
        "la révision 0002 n'a pas été appliquée à la base legacy — "
        "le stamp a probablement sauté à head"
    )
