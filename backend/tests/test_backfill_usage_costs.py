# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_backfill_usage_costs.py
# @brief      Les coûts historiques sont recalculés avec les vrais tarifs.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la reprise des coûts déjà écrits dans ``usage_logs``.

**Pourquoi une reprise est nécessaire.** ``cost_usd`` est calculé À L'ÉCRITURE
puis simplement sommé à l'affichage. Les 9 117 lignes existantes portent donc
définitivement les tarifs en vigueur au moment du tour — c'est-à-dire, pour la
plupart, le générique inventé de 1,0/3,0 USD par million. Résultat mesuré :
**123,29 USD affichés**, dont **26,62 USD facturés à un modèle local gratuit**.

Renseigner les tarifs sur les instances (#272) corrige les tours À VENIR ;
seule une reprise corrige le passé.

**Deux traitements, et la distinction compte :**

1. *Recalcul* — pour les modèles encore configurés, on applique leurs tarifs
   réels. C'est de l'arithmétique, sans interprétation.
2. *Neutralisation* — pour des modèles RETIRÉS dont on sait qu'ils ne coûtaient
   rien à l'appel : ``gpt-5.5`` (consommé via l'abonnement ChatGPT — établi le
   26/07 en remontant le chemin ``_make_openai_codex``) et tout nom portant un
   marqueur de modèle local (``mlx``, ``lmstudio-community/``, ``LiquidAI/``).
   À eux seuls, 40,41 USD de coût fantôme.

⚠️ **Correction UNIQUE, pas une règle.** Ces motifs vivent dans une migration
datée, pas dans le code de calcul : une heuristique sur les noms de modèles
vieillirait en silence, ce qui est très exactement la classe de défaut que ce
chantier supprime.

Run with:  cd backend && python -m pytest tests/test_backfill_usage_costs.py -v
"""
from __future__ import annotations

import sqlite3
import types

import pytest


def _legacy_db(path):
    """Une base d'avant la reprise : des tours facturés au tarif générique."""
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
    # Un modèle local déclaré gratuit, et un modèle cloud tarifé.
    conn.executemany(
        "INSERT INTO llm_instances (id,label,provider,model,input_price_per_million,"
        "output_price_per_million) VALUES (?,?,?,?,?,?)",
        [("1", "local", "lm_studio", "qwen/qwen3.5-9b", 0.0, 0.0),
         ("2", "cloud", "deepseek", "deepseek-v4-pro", 0.435, 0.87)],
    )
    conn.executemany(
        "INSERT INTO usage_logs (id,model,input_tokens,output_tokens,cost_usd) "
        "VALUES (?,?,?,?,?)",
        [
            ("a", "qwen/qwen3.5-9b", 1_000_000, 1_000_000, 4.0),   # local, facturé à tort
            ("b", "deepseek-v4-pro", 1_000_000, 1_000_000, 4.0),   # cloud, tarif générique
            ("c", "gpt-5.5", 1_000_000, 1_000_000, 4.0),           # retiré, au forfait
            ("d", "mlx-community/ornith-1.0-9b", 1_000_000, 0, 1.0),  # retiré, local
            ("e", "kimi-k2.6", 1_000_000, 0, 1.0),                 # retiré, cloud inconnu
        ],
    )
    conn.commit()
    conn.close()


async def _run_migrations(db_path, monkeypatch):
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
async def test_a_local_model_stops_being_billed(tmp_path, monkeypatch):
    """LE cas qui a alerté Franck : 26,62 USD facturés à un Qwen local."""
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    await _run_migrations(db, monkeypatch)

    assert _cost(db, "a") == 0.0


@pytest.mark.asyncio
async def test_a_configured_model_gets_its_real_price(tmp_path, monkeypatch):
    """1 M en entrée à 0,435 + 1 M en sortie à 0,87 = 1,305 USD."""
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    await _run_migrations(db, monkeypatch)

    assert abs(_cost(db, "b") - 1.305) < 0.001


@pytest.mark.asyncio
async def test_the_subscription_model_is_neutralised(tmp_path, monkeypatch):
    """gpt-5.5 passait par l'abonnement ChatGPT : jamais facturé à l'appel.
    22,59 USD de coût fantôme à lui seul sur la base réelle."""
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    await _run_migrations(db, monkeypatch)

    assert _cost(db, "c") == 0.0


@pytest.mark.asyncio
async def test_a_retired_local_model_is_neutralised(tmp_path, monkeypatch):
    """Les noms `mlx-community/…` sont des modèles chargés localement."""
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    await _run_migrations(db, monkeypatch)

    assert _cost(db, "d") == 0.0


@pytest.mark.asyncio
async def test_a_retired_cloud_model_is_left_alone(tmp_path, monkeypatch):
    """Prudence : un modèle cloud retiré a bien coûté quelque chose. On ne sait
    pas combien, on n'invente pas — sa valeur d'origine est conservée."""
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    await _run_migrations(db, monkeypatch)

    assert _cost(db, "e") == 1.0
