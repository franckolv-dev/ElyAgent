# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_cached_tokens_measured.py
# @brief      Savoir enfin si la stratégie de cache de préfixe d'Ely fonctionne.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de la mesure des tokens servis par le cache.

**Le trou.** Ely découpe son prompt système exprès pour maximiser le cache de
préfixe : un segment **stable octet pour octet** (identité, règles, mémoire
figée, profil) suivi d'un segment **dynamique** (date, langue). La docstring de
``system_prompt_cache`` assume le choix — *« exactly the maximum cache hit we
can achieve without API-level cache_control markers »*.

Sauf que ``usage_metadata`` remonte déjà ``input_token_details.cache_read`` et
que ``usage_from_result`` lisait **uniquement** ``input_tokens`` et
``output_tokens``. Une stratégie soignée, et **aucun moyen de savoir si elle
mord**.

**Pourquoi mesurer partout, et pas seulement là où l'on paie :**

- **API payantes** (DeepSeek, Anthropic, Mistral) — un token servi par le cache
  coûte de 5 à 10 fois moins ;
- **forfait ChatGPT** — pas d'économie, mais un préfixe caché n'est pas
  retraité : la réponse démarre plus vite ;
- **modèles locaux** — c'est le gain le PLUS important. Sans réutilisation du
  cache KV, LM Studio recalcule tout le prompt à chaque tour ; sur un 9B avec
  15 000 tokens de préfixe, cela fait plusieurs secondes de traitement à chaque
  itération d'une boucle d'outils.

Deux compteurs distincts, et la distinction compte : ``cache_read`` est un
**succès** (tokens relus, facturés au rabais), ``cache_creation`` une
**écriture** (tokens mis en cache, parfois facturés plus cher que la normale
chez Anthropic). Les additionner masquerait un cache qui écrit sans jamais
relire — c'est-à-dire un cache inutile et coûteux.

Run with:  cd backend && python -m pytest tests/test_cached_tokens_measured.py -v
"""
from __future__ import annotations

import uuid

import pytest


class _Msg:
    def __init__(self, usage):
        self.usage_metadata = usage
        self.tool_calls = []


def test_the_cache_counters_are_extracted_from_the_response():
    """LE test du lot : la donnée était déjà là, on la jetait."""
    from app.services.usage_instrumentation import usage_from_result

    out = usage_from_result({"messages": [_Msg({
        "input_tokens": 12_000, "output_tokens": 300,
        "input_token_details": {"cache_read": 9_500, "cache_creation": 2_500},
    })]})

    assert out["cached_input_tokens"] == 9_500
    assert out["cache_creation_tokens"] == 2_500


def test_reads_and_writes_stay_separate():
    """Un cache qui écrit sans jamais relire est inutile ET coûteux (Anthropic
    facture l'écriture plus cher). Les additionner masquerait ce cas."""
    from app.services.usage_instrumentation import usage_from_result

    out = usage_from_result({"messages": [_Msg({
        "input_tokens": 5_000, "output_tokens": 100,
        "input_token_details": {"cache_read": 0, "cache_creation": 5_000},
    })]})

    assert out["cached_input_tokens"] == 0
    assert out["cache_creation_tokens"] == 5_000


def test_a_provider_that_reports_nothing_stays_at_zero():
    """La plupart des serveurs locaux ne remontent aucun détail : l'absence ne
    doit pas se lire comme un échec de cache."""
    from app.services.usage_instrumentation import usage_from_result

    out = usage_from_result({"messages": [_Msg({
        "input_tokens": 5_000, "output_tokens": 100,
    })]})

    assert out["cached_input_tokens"] == 0
    assert out["cache_creation_tokens"] == 0


def test_the_counters_accumulate_over_a_multi_step_turn():
    """Un tour avec boucle d'outils enchaîne plusieurs appels au modèle."""
    from app.services.usage_instrumentation import usage_from_result

    out = usage_from_result({"messages": [
        _Msg({"input_tokens": 10_000, "output_tokens": 50,
              "input_token_details": {"cache_read": 8_000, "cache_creation": 2_000}}),
        _Msg({"input_tokens": 11_000, "output_tokens": 60,
              "input_token_details": {"cache_read": 10_500, "cache_creation": 0}}),
    ]})

    assert out["cached_input_tokens"] == 18_500
    assert out["cache_creation_tokens"] == 2_000


def test_odd_payloads_never_break_the_extraction():
    """L'instrumentation ne doit jamais coûter un tour à l'utilisateur."""
    from app.services.usage_instrumentation import usage_from_result

    for details in (None, {}, {"cache_read": None}, {"cache_read": "beaucoup"}, []):
        out = usage_from_result({"messages": [_Msg({
            "input_tokens": 1, "output_tokens": 1, "input_token_details": details,
        })]})
        assert isinstance(out["cached_input_tokens"], int)


# ------------------------------------------------------ la persistance

@pytest.mark.asyncio
async def test_the_counters_reach_the_database():
    """Le but du lot : répondre « le cache mord-il ? » sur du trafic RÉEL. La
    leçon de #255 — le calcul n'est pas la livraison."""
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.usage_log import UsageLog
    from app.models.user import User
    from app.services.analytics_service import log_usage

    await init_db()
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uuid.uuid4().hex[:8]}",
                    email=f"{uuid.uuid4().hex[:8]}@t.local", hashed_password="x"))
        await db.commit()

    await log_usage(user_id=uid, model="m", provider="p",
                    input_tokens=12_000, output_tokens=300,
                    cached_input_tokens=9_500, cache_creation_tokens=2_500)

    async with async_session() as db:
        row = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == uid)
        )).scalar_one()

    assert row.cached_input_tokens == 9_500
    assert row.cache_creation_tokens == 2_500


@pytest.mark.asyncio
async def test_a_turn_without_cache_info_stays_at_zero():
    """Rétrocompatibilité : les appelants historiques ne passent rien."""
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.usage_log import UsageLog
    from app.models.user import User
    from app.services.analytics_service import log_usage

    await init_db()
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uuid.uuid4().hex[:8]}",
                    email=f"{uuid.uuid4().hex[:8]}@t.local", hashed_password="x"))
        await db.commit()

    await log_usage(user_id=uid, model="m", provider="p",
                    input_tokens=10, output_tokens=5)

    async with async_session() as db:
        row = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == uid)
        )).scalar_one()

    assert (row.cached_input_tokens or 0) == 0
