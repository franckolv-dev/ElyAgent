# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_no_safe_columns_at_boot.py
# @brief      Ménage lot 2 — le boot ne rejoue plus 19 ALTER TABLE pour rien.
#             Alembic seul fait foi sur le schéma.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du retrait de `_safe_columns`.

**Pourquoi.** `init_db()` portait une liste de 19 `ALTER TABLE … ADD COLUMN`
rejoués à **chaque démarrage**, chacun échouant sur « duplicate column » —
l'état nominal. C'était la béquille d'avant Alembic : `create_all` ne sait pas
faire évoluer une table existante, donc on patchait à la main.

**Mesuré le 29/07 avant de retirer** :

- les **19** colonnes sont déclarées dans les modèles → `create_all` les crée
  sur une base neuve ;
- les **19** sont présentes dans la base de **production** → plus rien à
  rattraper sur l'existant ;
- soit 0 orpheline : la liste ne fait plus rien qu'échouer 19 fois par boot.

**Le piège que ces pins gardent.** Retirer la béquille n'est sûr que tant que
`create_all` couvre effectivement ces colonnes. Le second test le vérifie sur
une base **réellement créée**, pas sur la déclaration des modèles : si un jour
une colonne n'existe que dans `_safe_columns`, il devient rouge.

⚠️ La règle qui remplace la béquille : **toute nouvelle colonne passe par une
révision Alembic**. `_safe_columns` était un chemin parallèle qui laissait le
schéma diverger en silence — c'est ce drift qui avait produit le bug
`critic_run_at` (676 `AttributeError` en production).

Run with:  cd backend && python -m pytest tests/test_no_safe_columns_at_boot.py -v
"""
from __future__ import annotations

import pytest
from sqlalchemy import event, inspect

# Les 19 colonnes que `_safe_columns` ajoutait — figées ici pour que le pin
# survive à la suppression de la liste elle-même.
_FORMERLY_PATCHED: tuple[tuple[str, str], ...] = (
    ("users", "language"),
    ("users", "hitl_preferred_channel"),
    ("users", "onboarding_completed_at"),
    ("users", "onboarding_skipped_at"),
    ("users", "onboarding_step"),
    ("users", "onboarding_skip_count"),
    ("users", "tts_auto_enabled"),
    ("users", "sovereignty_strict"),
    ("conversations", "toolset_profile"),
    ("user_memory_logs", "recall_count"),
    ("user_memory_logs", "last_recalled_at"),
    ("feedback", "prompt_version"),
    ("mission_steps", "prompt_version"),
    ("error_log", "prompt_version"),
    ("missions", "critic_run_at"),
    ("learned_skills", "content_format"),
    ("learned_skills", "validation_report_json"),
    ("learned_skills", "tool_profile"),
    ("missions", "autonomous"),
)


@pytest.mark.asyncio
async def test_init_db_issues_no_alter_table() -> None:
    """Le démarrage n'émet plus un seul `ALTER TABLE … ADD COLUMN`.

    On écoute le SQL **réellement exécuté** plutôt que de relire le source :
    une liste laissée en place mais contournée passerait un grep, pas ceci.
    """
    from app.database import engine, init_db

    seen: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(_conn, _cursor, statement, *_args) -> None:
        seen.append(statement)

    try:
        await init_db()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    alters = [
        s for s in seen
        if "ALTER TABLE" in s.upper() and "ADD COLUMN" in s.upper()
    ]
    assert alters == [], (
        f"{len(alters)} ALTER TABLE encore émis au boot : {alters[:3]}"
    )


@pytest.mark.asyncio
async def test_created_schema_still_has_every_formerly_patched_column() -> None:
    """Une base créée par `init_db()` porte les 19 colonnes, sans la béquille.

    C'est le test qui rend la suppression sûre : il interroge le schéma
    **créé**, pas les modèles. Il doit rester vert avant comme après.
    """
    from app.database import engine, init_db

    await init_db()

    async with engine.begin() as conn:
        actual = await conn.run_sync(
            lambda sync_conn: {
                table: {c["name"] for c in inspect(sync_conn).get_columns(table)}
                for table in {t for t, _ in _FORMERLY_PATCHED}
            }
        )

    missing = [
        f"{table}.{column}"
        for table, column in _FORMERLY_PATCHED
        if column not in actual.get(table, set())
    ]
    assert missing == [], (
        "colonnes perdues avec _safe_columns — create_all ne les couvre pas : "
        f"{missing}"
    )
