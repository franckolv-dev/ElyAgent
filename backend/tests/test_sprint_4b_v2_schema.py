# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_sprint_4b_v2_schema.py
# @brief      Sprint 4b V2 J1 — pin the schema additions for @tool Python
#             generation: LearnedSkill.content_format + validation_report_json.
# @license    Elastic License 2.0
# =============================================================================
"""Schema pin for Sprint 4b V2 Jalon 1 (design note J0 §4).

V2 extends the existing ``learned_skills`` table with two columns:
  - ``content_format``         markdown_playbook (V1) | python_tool (V2)
  - ``validation_report_json`` the 5-stage pipeline report

The hard lesson from the v1.11.2 ``critic_run_at`` incident: a new column
must live in BOTH places or it breaks silently —
  1. on the ORM model     → else runtime ``AttributeError`` / can't read it
  2. in ``database.py`` ``_safe_columns`` → else existing prod DBs never
     get the column and every query raises ``OperationalError``.

So this test asserts both, AND does a live ORM round-trip against the
configured (file) SQLite to prove the defaults actually populate — not
just a source grep.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillStatus,
)


# ── 1. Columns exist on the model ────────────────────────────────────────────


_V2_COLUMNS = {"content_format", "validation_report_json"}


def test_model_has_v2_columns() -> None:
    actual = {c.name for c in LearnedSkill.__table__.columns}
    missing = _V2_COLUMNS - actual
    assert not missing, (
        f"LearnedSkill is missing V2 columns the J0 design note §4 requires: "
        f"{sorted(missing)}"
    )


def test_content_format_is_varchar_20() -> None:
    col = LearnedSkill.__table__.columns["content_format"]
    assert col.type.length == 20, (
        "content_format should be VARCHAR(20) — fits 'markdown_playbook' "
        "(16) + headroom for future formats."
    )


def test_content_format_defaults_to_markdown_playbook() -> None:
    """The Python-side default must keep every newly-created row a V1
    playbook unless explicitly set to python_tool."""
    col = LearnedSkill.__table__.columns["content_format"]
    assert col.default is not None, "content_format needs a default"
    assert col.default.arg == SkillContentFormat.MARKDOWN_PLAYBOOK


def test_validation_report_defaults_to_empty_object() -> None:
    col = LearnedSkill.__table__.columns["validation_report_json"]
    assert col.default is not None, "validation_report_json needs a default"
    assert col.default.arg == "{}"


# ── 2. Content-format enum contract ──────────────────────────────────────────


def test_content_format_enum_values() -> None:
    assert SkillContentFormat.MARKDOWN_PLAYBOOK == "markdown_playbook"
    assert SkillContentFormat.PYTHON_TOOL == "python_tool"
    assert SkillContentFormat.ALL == {"markdown_playbook", "python_tool"}


# ── 3. _safe_columns declares both new columns (existing-DB migration) ───────


def test_database_module_declares_v2_safe_columns() -> None:
    """Les deux colonnes V2 sont au schéma, et une skill sans format déclaré
    reste un playbook.

    ⚠️ Ce test grepait `_safe_columns` dans `app/database.py`. Cette liste a
    été retirée le 29/07 (ménage lot 2), mesurée sans effet : les colonnes
    sont dans les modèles ET dans la base de production, où l'`ALTER` les
    avait déjà posées et remplies.

    On épingle donc la **propriété** au lieu du **mécanisme** : les colonnes
    existent au schéma, et le défaut qui garantissait le rattrapage des lignes
    V1 vit maintenant sur le modèle. Le round-trip live plus bas couvre le
    runtime.
    """
    from app.database import Base
    import app.models  # noqa: F401 — enregistre toutes les tables

    cols = Base.metadata.tables["learned_skills"].columns
    assert "content_format" in cols, (
        "learned_skills.content_format manquante — bug de classe critic_run_at."
    )
    assert "validation_report_json" in cols, (
        "learned_skills.validation_report_json manquante."
    )

    # Le défaut qui empêchait les lignes V1 de rester NULL : une skill créée
    # sans format déclaré doit rester un playbook markdown.
    default = cols["content_format"].default
    assert default is not None and default.arg == SkillContentFormat.MARKDOWN_PLAYBOOK, (
        "content_format doit défaulter à 'markdown_playbook' — sinon les "
        "skills V1 existantes cessent d'être lues comme des playbooks."
    )


# ── 4. Live ORM round-trip — defaults actually populate ──────────────────────


@pytest.mark.asyncio
async def test_v2_columns_roundtrip_with_defaults() -> None:
    """Create a LearnedSkill WITHOUT touching the V2 fields and read it
    back: content_format must be 'markdown_playbook', validation_report
    must be '{}'. This exercises the model column + the DB at once."""
    await init_db()

    from app.models.user import User

    uid = f"v2sch-{uuid.uuid4().hex[:8]}"
    sid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"v2_schema_{uid}",
            email=f"{uid}@test.local",
            hashed_password="x",
        ))
        await db.commit()

        db.add(LearnedSkill(
            id=sid,
            user_id=uid,
            name="v2-schema-probe",
            description="round-trip probe for J1 schema",
            content="# playbook body",
            status=SkillStatus.CANDIDATE,
        ))
        await db.commit()

    try:
        async with async_session() as db:
            row = (await db.execute(
                select(LearnedSkill).where(LearnedSkill.id == sid)
            )).scalar_one()
            assert row.content_format == SkillContentFormat.MARKDOWN_PLAYBOOK
            assert row.validation_report_json == "{}"
    finally:
        async with async_session() as db:
            await db.execute(delete(LearnedSkill).where(LearnedSkill.id == sid))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
