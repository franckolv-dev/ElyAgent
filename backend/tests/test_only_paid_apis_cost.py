# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_only_paid_apis_cost.py
# @brief      Seuls DeepSeek et Anthropic ont été facturés à l'appel.
# @license    MIT
# =============================================================================
"""Pins de la seconde reprise des coûts historiques.

La reprise 0028 avait ramené le total de **123,29 à 56,13 USD** en recalculant
depuis les tarifs déclarés et en neutralisant les modèles retirés reconnaissables
comme locaux (``mlx``, ``lmstudio-community/``, ``LiquidAI/``) ou consommés au
forfait (``gpt-5.5``).

Restaient des modèles dont le nom ne portait aucun marqueur exploitable —
``ministral-3-8b-instruct-2512``, ``google/gemma-4-12b``, ``qwen3.6-flash``,
``kimi-k2.6`` — pour lesquels j'ai refusé d'inventer. Franck a tranché : hors DeepSeek et
Anthropic, ce qui tournait alors était local — **sauf ``qwen3.6-flash`` et
``kimi-k2.6``**, deux API cloud qui ont bien consommé un peu.

**Le critère a changé en cours de route, et c'est instructif.** Une première
version filtrait sur des PRÉFIXES DE NOM (« deepseek- », « claude- »). Elle
aurait effacé les ~12 USD de ``mistral-large-latest``, une API payante bel et
bien configurée avec ses tarifs. Le critère est devenu : **une ligne n'est
neutralisée que si son modèle n'existe plus dans ``llm_instances``** — la
source de vérité que ce chantier a mise en place. Filtrer sur des noms, c'était
retomber dans l'heuristique qui vieillit ; s'appuyer sur la configuration
déclarée, c'est utiliser ce qu'on vient de construire.

⚠️ Reprise UNIQUE sur les lignes existantes, dans une migration datée. Les
tours À VENIR passent par les tarifs déclarés sur les instances (#272) : rien
ici ne devient une règle permanente sur les noms de modèles.

Run with:  cd backend && python -m pytest tests/test_only_paid_apis_cost.py -v
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
    # Comme en production : les API payantes SONT déclarées, avec leurs tarifs.
    conn.executemany(
        "INSERT INTO llm_instances (id,label,provider,model,"
        "input_price_per_million,output_price_per_million) VALUES (?,?,?,?,?,?)",
        [("i1", "ds-pro", "deepseek", "deepseek-v4-pro", 0.435, 0.87),
         ("i2", "ds-flash", "deepseek", "deepseek-v4-flash", 0.14, 0.28),
         ("i3", "opus", "anthropic", "claude-opus-4-5-20251101", 15.0, 75.0),
         ("i4", "haiku", "anthropic", "claude-haiku-4-5-20251001", 1.0, 5.0)],
    )
    conn.executemany(
        "INSERT INTO usage_logs (id,model,input_tokens,output_tokens,cost_usd) "
        "VALUES (?,?,?,?,?)",
        [
            ("p1", "deepseek-v4-pro", 1_000_000, 0, 22.70),
            ("p2", "deepseek-v4-flash", 1_000_000, 0, 8.92),
            ("p3", "claude-opus-4-5-20251101", 1_000_000, 0, 7.58),
            ("p4", "claude-haiku-4-5-20251001", 1_000_000, 0, 4.24),
            ("l1", "ministral-3-8b-instruct-2512", 1_000_000, 0, 3.50),
            ("l2", "google/gemma-4-12b", 1_000_000, 0, 1.19),
            ("c1", "qwen3.6-flash", 1_000_000, 0, 2.23),
            ("c2", "kimi-k2.6+tools", 1_000_000, 0, 0.33),
            ("l4", "deepseek-v4-pro+tools", 1_000_000, 0, 1.00),
            ("m1", "mistral-large-latest", 1_000_000, 0, 11.97),
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
@pytest.mark.parametrize("row_id", ["l1", "l2"])
async def test_a_local_model_costs_nothing(tmp_path, monkeypatch, row_id):
    """LE test du lot : hors DeepSeek et Anthropic, tout tournait chez Franck."""
    db = tmp_path / "legacy.db"
    _seed(db)

    await _upgrade(db, monkeypatch)

    assert _cost(db, row_id) == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("row_id,expected", [
    ("p1", 0.435), ("p2", 0.14), ("p3", 15.0), ("p4", 1.0),
])
async def test_a_paid_api_keeps_a_real_cost(tmp_path, monkeypatch, row_id, expected):
    """Les fournisseurs réellement facturés gardent un coût — recalculé par
    0028 depuis leurs tarifs déclarés (1 M de tokens d'entrée au prix du
    million), et surtout pas remis à zéro par 0029. Remplacer une
    surestimation par une sous-estimation ne serait pas un progrès."""
    db = tmp_path / "legacy.db"
    _seed(db)

    await _upgrade(db, monkeypatch)

    assert abs(_cost(db, row_id) - expected) < 0.01


@pytest.mark.asyncio
@pytest.mark.parametrize("row_id,expected", [("c1", 2.23), ("c2", 0.33)])
async def test_a_retired_but_paid_api_keeps_its_estimate(
    tmp_path, monkeypatch, row_id, expected,
):
    """qwen3.6-flash et kimi-k2.6 sont retirés mais ont bien consommé. Leur
    coût reste approximatif — les tarifs de l'époque ne sont plus connus, et on
    ne les invente pas."""
    db = tmp_path / "legacy.db"
    _seed(db)

    await _upgrade(db, monkeypatch)

    assert abs(_cost(db, row_id) - expected) < 0.01


@pytest.mark.asyncio
async def test_a_configured_cloud_model_is_not_erased(tmp_path, monkeypatch):
    """LE piège évité : filtrer sur des préfixes de nom aurait effacé les
    ~12 USD de Mistral, une API payante bel et bien configurée."""
    db = tmp_path / "legacy.db"
    _seed(db)
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO llm_instances (id,label,provider,model,"
                 "input_price_per_million,output_price_per_million) "
                 "VALUES ('m','mistral','mistral','mistral-large-latest',0.5,1.5)")
    conn.commit()
    conn.close()

    await _upgrade(db, monkeypatch)

    assert _cost(db, "m1") > 0


@pytest.mark.asyncio
async def test_the_tools_suffix_does_not_hide_a_paid_model(tmp_path, monkeypatch):
    """Le nom du modèle peut porter « +tools » : le comparer tel quel ferait
    passer un vrai DeepSeek pour un modèle local, et effacerait son coût."""
    db = tmp_path / "legacy.db"
    _seed(db)

    await _upgrade(db, monkeypatch)

    assert _cost(db, "l4") > 0, (
        "un DeepSeek suffixé « +tools » a été pris pour un modèle retiré"
    )
