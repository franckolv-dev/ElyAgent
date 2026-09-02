# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_usage_logs_user_timestamp_index.py
# @brief      L'index composite (user_id, timestamp) que les six agrégations
#             d'usage réclamaient depuis toujours.
# @license    Elastic License 2.0
# =============================================================================
"""Pin de l'index composite de ``usage_logs`` (audit 02/09/2026).

Le modèle indexait ``user_id`` et ``timestamp`` SÉPARÉMENT. Or les six
requêtes qui lisent cette table filtrent sur les DEUX à la fois :

    where user_id = ? and timestamp >= ?

cinq agrégations de ``services/analytics_service.py`` (résumé, usage
quotidien, usage par skill, stats HITL, ventilation par fournisseur) et le
garde-budget (``services/budget_guard.py``, appelé à chaque tour). SQLite ne
retient qu'un seul index par table et par requête : il balayait donc toutes
les lignes d'un utilisateur pour n'en garder que la fenêtre de dates. 11 280
lignes en prod, et la table ne fait que grossir.

Deux chemins doivent porter l'index, pas un :
- l'installation NEUVE, créée par ``create_all`` depuis le modèle ;
- l'installation EXISTANTE, migrée par Alembic (0035).

Run with:  cd backend && python -m pytest tests/test_usage_logs_user_timestamp_index.py -v
"""
from __future__ import annotations

import sqlite3
import types

import pytest

_INDEX = "ix_usage_logs_user_timestamp"


def _seed(path):
    """Une base « legacy » minimale : usage_logs sans l'index composite."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE usage_logs (
            id TEXT PRIMARY KEY, user_id TEXT, timestamp TEXT, model TEXT,
            provider TEXT, input_tokens INTEGER, output_tokens INTEGER,
            total_tokens INTEGER, cost_usd REAL
        )""")
    conn.commit()
    conn.close()


async def _upgrade(db_path, monkeypatch):
    import app.config as app_config
    from app.services import alembic_runner as ar

    monkeypatch.setattr(
        app_config, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{db_path}"),
    )
    return await ar.ensure_migrations()


def _index_columns(db_path, index_name):
    """Colonnes de l'index, dans l'ordre. Liste vide si l'index n'existe pas."""
    conn = sqlite3.connect(db_path)
    try:
        names = {r[1] for r in conn.execute("PRAGMA index_list('usage_logs')")}
        if index_name not in names:
            return []
        return [r[2] for r in conn.execute(f"PRAGMA index_info('{index_name}')")]
    finally:
        conn.close()


def test_le_modele_declare_l_index_composite():
    """Installation neuve : ``create_all`` lit le modèle, pas les migrations."""
    from app.models.usage_log import UsageLog

    declared = {idx.name: [c.name for c in idx.columns] for idx in UsageLog.__table__.indexes}

    assert _INDEX in declared, f"index composite absent du modèle : {sorted(declared)}"
    assert declared[_INDEX] == ["user_id", "timestamp"], (
        "l'ordre compte : user_id (égalité) AVANT timestamp (intervalle)"
    )


@pytest.mark.asyncio
async def test_la_migration_pose_l_index_sur_une_base_existante(tmp_path, monkeypatch):
    """Base déjà en service : seule la migration peut ajouter l'index."""
    db = tmp_path / "legacy.db"
    _seed(db)
    assert _index_columns(db, _INDEX) == []

    await _upgrade(db, monkeypatch)

    assert _index_columns(db, _INDEX) == ["user_id", "timestamp"]


@pytest.mark.asyncio
async def test_la_migration_ne_bronche_pas_si_l_index_est_deja_la(tmp_path, monkeypatch):
    """Idempotence : une base créée par ``create_all`` porte DÉJÀ l'index du
    modèle quand la migration passe. Elle doit se taire, pas échouer.

    Ce que ce test regarde est la SORTIE de ``ensure_migrations``, pas la
    présence de l'index : l'index, c'est le seed qui vient de le poser, il
    serait là même si toute la chaîne de révisions avait échoué. Or l'échec
    est muet — ``ensure_migrations`` avale l'exception, la logue en CRITICAL
    et rend ``"skipped"``. Sans la garde défensive de 0035,
    ``op.create_index`` lèverait « index already exists », plus AUCUNE
    révision ne serait appliquée, et un test qui ne constate que l'index
    passerait quand même."""
    db = tmp_path / "already.db"
    _seed(db)
    conn = sqlite3.connect(db)
    conn.execute(f"CREATE INDEX {_INDEX} ON usage_logs (user_id, timestamp)")
    conn.commit()
    conn.close()

    outcome = await _upgrade(db, monkeypatch)

    assert outcome != "skipped", (
        "la chaîne de migrations a échoué en silence (voir le log CRITICAL) : "
        "0035 a buté sur l'index déjà présent"
    )
    assert _index_columns(db, _INDEX) == ["user_id", "timestamp"]
