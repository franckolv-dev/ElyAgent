# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_restore_opus_cost.py
# @brief      Rétablir le coût Claude Opus, effacé à tort par 0029.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pin du rétablissement du coût Claude Opus.

**Mon erreur.** La reprise 0029 neutralise les modèles dont plus aucune
instance n'existe. Franck avait pourtant nommé Anthropic parmi ses API payantes
— mais il n'a **plus d'instance Opus configurée**, ayant depuis basculé sur
Haiku. Mon critère automatique a donc effacé **7,58 USD réellement dépensés**,
contre ce qu'il m'avait explicitement dit.

Le critère « absent des instances » reste bon pour la masse ; il ne savait
simplement pas qu'un modèle peut être retiré de la configuration **après** avoir
coûté. C'est la limite de tout critère automatique face à une déclaration
humaine : quand les deux se contredisent, c'est l'humain qui a raison.

**Le montant n'est pas inventé** : 183 158 tokens d'entrée et 64 456 de sortie
au tarif publié d'Anthropic (15 / 75 USD par million) donnent 7,58 USD — soit
exactement la valeur stockée d'origine, avant que je l'écrase.

Run with:  cd backend && python -m pytest tests/test_restore_opus_cost.py -v
"""
from __future__ import annotations

import sqlite3
import types

import pytest


def _seed(path):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE usage_logs (
            id TEXT PRIMARY KEY, user_id TEXT, timestamp TEXT, model TEXT,
            provider TEXT, input_tokens INTEGER, output_tokens INTEGER,
            total_tokens INTEGER, cost_usd REAL
        )""")
    conn.execute("""
        CREATE TABLE llm_instances (
            id TEXT PRIMARY KEY, label TEXT, provider TEXT, model TEXT,
            api_key TEXT, created_at TEXT, context_window INTEGER,
            max_output_tokens INTEGER,
            input_price_per_million REAL, output_price_per_million REAL
        )""")
    conn.executemany(
        "INSERT INTO usage_logs (id,model,input_tokens,output_tokens,cost_usd) "
        "VALUES (?,?,?,?,?)",
        [
            ("o1", "claude-opus-4-5-20251101", 1_000_000, 1_000_000, 4.0),
            ("o2", "claude-opus-4-5-20251101+tools", 0, 1_000_000, 4.0),
            ("x1", "mlx-community/ornith-1.0-9b", 1_000_000, 0, 1.0),
        ],
    )
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


def _cost(db_path, row_id):
    conn = sqlite3.connect(db_path)
    v = conn.execute("SELECT cost_usd FROM usage_logs WHERE id=?", (row_id,)).fetchone()[0]
    conn.close()
    return v


@pytest.mark.asyncio
async def test_opus_gets_its_published_rate(tmp_path, monkeypatch):
    """1 M en entrée à 15 + 1 M en sortie à 75 = 90 USD."""
    db = tmp_path / "legacy.db"
    _seed(db)

    await _upgrade(db, monkeypatch)

    assert abs(_cost(db, "o1") - 90.0) < 0.01


@pytest.mark.asyncio
async def test_the_tools_suffix_is_covered_too(tmp_path, monkeypatch):
    """`+tools` ne doit pas faire échapper une ligne au rétablissement."""
    db = tmp_path / "legacy.db"
    _seed(db)

    await _upgrade(db, monkeypatch)

    assert abs(_cost(db, "o2") - 75.0) < 0.01


@pytest.mark.asyncio
async def test_the_rest_of_the_backfill_is_untouched(tmp_path, monkeypatch):
    """Garde-fou : ce lot ne rétablit QUE Claude Opus. Les modèles locaux
    neutralisés par 0028 et 0029 doivent le rester."""
    db = tmp_path / "legacy.db"
    _seed(db)

    await _upgrade(db, monkeypatch)

    assert _cost(db, "x1") == 0.0
