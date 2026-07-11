# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_mandate.py
# @brief      Missions autonomes J1 — contrat du mandat : spec v2 `mandate:`,
#             gate flag, colonnes mandate_json/autonomy_state, migration 0018.
# @license    Elastic License 2.0
# =============================================================================
"""Missions autonomes J1 — pins du contrat de mandat.

Cadrage : docs_internes/cadrage_missions_autonomes.md (décisions D1→D6).
Principe : déplacer le HITL de l'action vers le mandat. J1 ne livre QUE le
contrat + le stockage — l'enforcement (J2), les disjoncteurs (J3), le
workspace (J4), le mode strict (J5) et l'UI (J6) suivent.
"""
from __future__ import annotations

import textwrap
import uuid

import pytest

# Le cas canonique du cadrage (chaîne YouTube) — si CE document ne parse
# pas, le jalon rate sa cible.
_CANONICAL_V2 = textwrap.dedent("""
    version: 2
    mandate:
      autonomy: autonomous
      tools_allow: [youtube, drive, files, web]
      on_unforeseen: escalate
      budgets:
        daily_tool_actions_notify: 500
        daily_llm_calls_notify: 100
    steps:
      - id: plan_contenu
        do: "Établis le planning éditorial de la semaine pour la chaîne."
      - id: produire
        foreach: "{{ plan_contenu.output }}"
        do: "Produis et publie la vidéo {{ item }}."
        on_error: resume_next
""").strip()

_V1_CANONICAL = textwrap.dedent("""
    version: 1
    steps:
      - id: lire
        do: "Lis le fichier clients.csv."
""").strip()


# ─────────────────────────────────────────────────────────────────────────
# Parser — chemin nominal v2
# ─────────────────────────────────────────────────────────────────────────


def test_canonical_v2_mandate_parses() -> None:
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(_CANONICAL_V2)

    assert spec.version == 2
    assert spec.mandate is not None
    assert spec.mandate.autonomy == "autonomous"
    assert spec.mandate.tools_allow == ("youtube", "drive", "files", "web")
    assert spec.mandate.on_unforeseen == "escalate"
    assert spec.mandate.llm_tier is None          # D3 : null ⇒ COMPLEX forcé (J2)
    assert spec.mandate.budgets.daily_tool_actions_notify == 500
    assert spec.mandate.budgets.daily_llm_calls_notify == 100
    assert spec.step_ids() == ["plan_contenu", "produire"]


def test_v2_mandate_defaults_applied() -> None:
    """Mandat minimal : seul tools_allow est requis, le reste a des défauts."""
    from app.services.mission_spec import parse_mission_spec

    spec = parse_mission_spec(textwrap.dedent("""
        version: 2
        mandate:
          tools_allow: [email]
        steps:
          - id: s1
            do: "x"
    """).strip())

    m = spec.mandate
    assert m is not None
    assert m.autonomy == "autonomous"
    assert m.on_unforeseen == "escalate"          # D2 : escalade par défaut
    assert m.llm_tier is None
    assert m.budgets.daily_tool_actions_notify == 500   # D4
    assert m.budgets.daily_llm_calls_notify == 100      # D4


def test_v2_without_mandate_is_valid_and_v1_intact() -> None:
    """v2 sans mandat = v1 + rien ; v1 strictement inchangée (rétrocompat)."""
    from app.services.mission_spec import parse_mission_spec

    v2 = parse_mission_spec("version: 2\nsteps:\n  - id: s1\n    do: x")
    assert v2.version == 2 and v2.mandate is None

    v1 = parse_mission_spec(_V1_CANONICAL)
    assert v1.version == 1 and v1.mandate is None


# ─────────────────────────────────────────────────────────────────────────
# Parser — refus exhaustifs (erreurs FR, une passe)
# ─────────────────────────────────────────────────────────────────────────


def test_mandate_requires_version_2() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 1
            mandate:
              tools_allow: [email]
            steps:
              - id: s1
                do: "x"
        """).strip())
    assert any("version: 2" in e for e in exc.value.errors)


def test_mandate_all_errors_collected_in_one_pass() -> None:
    """Le style maison : TOUTES les erreurs remontent d'un coup."""
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 2
            mandate:
              autonomy: yolo
              tools_allow: [ssh, chimère, email, email]
              on_unforeseen: improvise
              llm_tier: quantique
              budgets:
                daily_tool_actions_notify: -3
                inconnu: 1
            steps:
              - id: s1
                do: "x"
        """).strip())

    errs = "\n".join(exc.value.errors)
    assert "autonomy" in errs                 # valeur inconnue
    assert "INTERDITE" in errs                # ssh = noyau protégé (D1)
    assert "chimère" in errs                  # famille inconnue
    assert "double" in errs                   # email répété
    assert "on_unforeseen" in errs            # improvise ∉ {escalate, decide}
    assert "llm_tier" in errs                 # quantique ∉ {simple, medium, complex}
    assert "daily_tool_actions_notify" in errs  # entier ≥ 1 requis
    assert "inconnu" in errs                  # clé budgets inconnue


def test_mandate_tools_allow_required() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 2
            mandate:
              autonomy: autonomous
            steps:
              - id: s1
                do: "x"
        """).strip())
    assert any("tools_allow" in e for e in exc.value.errors)


def test_mandate_unknown_keys_rejected() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec(textwrap.dedent("""
            version: 2
            mandate:
              tools_allow: [email]
              pouvoir_illimite: true
            steps:
              - id: s1
                do: "x"
        """).strip())
    assert any("pouvoir_illimite" in e for e in exc.value.errors)


def test_unknown_version_still_rejected() -> None:
    from app.services.mission_spec import MissionSpecError, parse_mission_spec

    with pytest.raises(MissionSpecError) as exc:
        parse_mission_spec("version: 3\nsteps:\n  - id: s1\n    do: x")
    assert any("version" in e for e in exc.value.errors)


# ─────────────────────────────────────────────────────────────────────────
# Gate flag — fail-closed par défaut
# ─────────────────────────────────────────────────────────────────────────


def test_flag_off_by_default_and_gate_message() -> None:
    from app.config import get_settings
    from app.services.mission_spec import validate_mission_spec

    assert get_settings().autonomous_missions_enabled is False

    # Défaut fail-closed du validateur (celui des endpoints)
    errs = validate_mission_spec(_CANONICAL_V2)
    assert errs and any("missions autonomes désactivées" in e for e in errs)

    # Flag ON simulé : le même document passe
    assert validate_mission_spec(_CANONICAL_V2, allow_mandate=True) == []

    # Une spec v1 n'est jamais affectée par le gate
    assert validate_mission_spec(_V1_CANONICAL) == []


# ─────────────────────────────────────────────────────────────────────────
# Modèle + persistance service + migration 0018
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mission_persists_mandate(monkeypatch) -> None:
    import json

    from sqlalchemy import delete, select

    from app.config import get_settings
    from app.database import async_session, init_db
    from app.models.mission import Mission
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_j1_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    try:
        # Flag OFF (défaut) : le SERVICE refuse aussi le mandat — défense en
        # profondeur, les sources non-UI (Telegram, scheduler) passent par lui.
        with pytest.raises(ValueError, match="missions autonomes désactivées"):
            await mission_service.create_mission(
                user_id=uid, title="x", goal="y", spec_yaml=_CANONICAL_V2,
            )

        # Flag ON : mandat normalisé persisté + état 'pending_validation'.
        monkeypatch.setattr(get_settings(), "autonomous_missions_enabled", True)
        m = await mission_service.create_mission(
            user_id=uid, title="Chaîne YouTube", goal="gérer la chaîne",
            spec_yaml=_CANONICAL_V2,
        )
        async with async_session() as db:
            row = (await db.execute(
                select(Mission).where(Mission.id == m.id)
            )).scalar_one()
        assert row.autonomy_state == "pending_validation"
        mandate = json.loads(row.mandate_json)
        assert mandate["tools_allow"] == ["youtube", "drive", "files", "web"]
        assert mandate["on_unforeseen"] == "escalate"
        assert mandate["budgets"]["daily_llm_calls_notify"] == 100

        # Rétrocompat : v1 et legacy ⇒ colonnes NULL, quel que soit le flag.
        v1 = await mission_service.create_mission(
            user_id=uid, title="V1", goal="g", spec_yaml=_V1_CANONICAL,
        )
        legacy = await mission_service.create_mission(
            user_id=uid, title="Legacy", goal="prompt monolithe",
        )
        assert v1.mandate_json is None and v1.autonomy_state is None
        assert legacy.mandate_json is None and legacy.autonomy_state is None
    finally:
        async with async_session() as db:
            await db.execute(delete(Mission).where(Mission.user_id == uid))
            u = await db.get(User, uid)
            if u is not None:
                await db.delete(u)
            await db.commit()


@pytest.mark.asyncio
async def test_migration_0018_adds_columns_to_legacy_db(tmp_path, monkeypatch) -> None:
    """Même piège d'adoption que 0002 : une base existante jamais vue par
    Alembic doit recevoir les 2 colonnes via stamp baseline + upgrade."""
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
    assert {"mandate_json", "autonomy_state"} <= cols, (
        "la révision 0018 n'a pas été appliquée à la base legacy"
    )
