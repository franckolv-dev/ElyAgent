# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_usage_instrumentation.py
# @brief      V2-1 — rendre la latence et l'architecture d'agent mesurables.
# @license    MIT
# =============================================================================
"""Pins de l'instrumentation d'usage (vague 2).

Constat qui motive ce lot (`docs_internes/v2_mesure_architectures.md`) :

- `usage_logs` compte 8 938 lignes et **ne porte aucune latence**. Le critère
  n° 1 de la décision mono-agent / sous-agents n'est donc pas mesurable.
- `usage_logs` ne porte **aucune ligne de canal** : `log_usage` n'est appelé
  ni depuis `telegram_bot.py`. Même
  avec du trafic, l'architecture à sous-agents resterait invisible.
- Rien n'indique **quelle architecture** a servi un tour. Or trois cohabitent :
  mono-agent (chat web), sous-agents (canaux, voix) et graphe plat (les 815
  conversations de tâches planifiées — la population la plus nombreuse).

Sans ces trois colonnes, le banc A/B de la vague 2 produirait des chiffres
qu'on ne saurait pas attribuer.

Run with:  cd backend && python -m pytest tests/test_usage_instrumentation.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.user import User


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _make_user() -> str:
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.commit()
        return u.id


# --------------------------------------------------- quelle architecture ?

def test_web_chat_is_labelled_mono_agent():
    """Le chat web passe un `toolset_profile`, ce qui court-circuite le
    routeur (`supervisor.py:894`) → un seul nœud agent."""
    from app.services.usage_instrumentation import architecture_label

    assert architecture_label(toolset_profile="default") == "mono"


def test_channel_turn_is_labelled_with_its_sub_agent():
    """Les canaux ne passent pas de profil : le routeur s'exécute vraiment et
    la demande part vers un spécialiste. C'est CE domaine qu'il faut tracer —
    `workspace` et `data` n'ont pas le même poids de prompt."""
    from app.services.usage_instrumentation import architecture_label

    assert architecture_label(domain="workspace") == "sub_agent:workspace"
    assert architecture_label(domain="research") == "sub_agent:research"


def test_scheduled_task_is_labelled_flat():
    """815 conversations en prod — ni mono-agent ni sous-agents, mais le
    graphe plat (`automated_task=True`). Les confondre fausserait le banc."""
    from app.services.usage_instrumentation import architecture_label

    assert architecture_label(automated_task=True) == "flat"
    # Le graphe plat gagne, même si un profil traîne dans l'état.
    assert architecture_label(automated_task=True, toolset_profile="default") == "flat"


def test_unknown_architecture_is_named_not_guessed():
    """Ne jamais inventer : un tour non attribuable doit se voir dans les
    chiffres plutôt que gonfler silencieusement une des trois familles."""
    from app.services.usage_instrumentation import architecture_label

    assert architecture_label() == "unknown"


# ------------------------------------------- extraction depuis un résultat

class _Msg:
    def __init__(self, usage=None):
        self.usage_metadata = usage


def test_tokens_are_summed_across_every_model_call_of_the_turn():
    """Un tour outillé enchaîne plusieurs appels ; le coût du tour est leur
    somme, pas celui du dernier."""
    from app.services.usage_instrumentation import usage_from_result

    result = {"messages": [
        _Msg({"input_tokens": 1200, "output_tokens": 40}),
        _Msg(None),
        _Msg({"input_tokens": 1500, "output_tokens": 90}),
    ]}

    usage = usage_from_result(result)

    assert usage["input_tokens"] == 2700
    assert usage["output_tokens"] == 130


def test_usage_extraction_survives_a_result_without_metadata():
    """LM Studio ne renvoie pas toujours `usage_metadata` — ne pas exploser,
    et ne pas prétendre à zéro token sans le dire."""
    from app.services.usage_instrumentation import usage_from_result

    usage = usage_from_result({"messages": [_Msg(None)]})

    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage["has_metadata"] is False


def test_usage_extraction_reports_the_routed_domain():
    """Le domaine choisi par le routeur vit dans l'état retourné."""
    from app.services.usage_instrumentation import usage_from_result

    assert usage_from_result({"messages": [], "domain": "workspace"})["domain"] == "workspace"


def test_usage_extraction_never_raises_on_garbage():
    from app.services.usage_instrumentation import usage_from_result

    for junk in (None, {}, {"messages": None}, "pas un état"):
        assert usage_from_result(junk)["input_tokens"] == 0


# ------------------------------------------------------ persistance réelle

@pytest.mark.asyncio
async def test_latency_and_architecture_are_persisted():
    """LE test du lot : les deux colonnes qui manquaient arrivent en base."""
    from app.database import async_session
    from app.models.usage_log import UsageLog
    from app.services.analytics_service import log_usage

    user_id = await _make_user()
    await log_usage(
        user_id=user_id, model="claude-opus-5", provider="anthropic",
        input_tokens=1200, output_tokens=80, channel="telegram",
        latency_ms=4310, architecture="sub_agent:workspace",
    )

    async with async_session() as db:
        row = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == user_id)
        )).scalar_one()

    assert row.latency_ms == 4310
    assert row.architecture == "sub_agent:workspace"


@pytest.mark.asyncio
async def test_existing_callers_keep_working_without_the_new_fields():
    """Rétrocompatibilité : les appels historiques ne passent pas ces
    champs — ils doivent rester valides, à NULL (et non à 0, qui se
    confondrait avec une latence mesurée nulle)."""
    from app.database import async_session
    from app.models.usage_log import UsageLog
    from app.services.analytics_service import log_usage

    user_id = await _make_user()
    await log_usage(
        user_id=user_id, model="m", provider="p",
        input_tokens=10, output_tokens=5,
    )

    async with async_session() as db:
        row = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == user_id)
        )).scalar_one()

    assert row.latency_ms is None
    assert row.architecture is None


@pytest.mark.asyncio
async def test_record_turn_usage_writes_a_complete_row_for_a_channel_turn():
    """Comportemental : c'est ce que les trois bots appellent. Un tour
    Telegram routé vers `workspace` doit produire une ligne complète —
    tokens sommés, latence, et architecture attribuée au bon spécialiste."""
    import time

    from app.database import async_session
    from app.models.usage_log import UsageLog
    from app.services.usage_instrumentation import record_turn_usage

    user_id = await _make_user()
    result = {
        "messages": [
            _Msg({"input_tokens": 900, "output_tokens": 30}),
            _Msg({"input_tokens": 1100, "output_tokens": 70}),
        ],
        "domain": "workspace",
        "model_used": "llm:anthropic/claude-opus-5+tools",
    }

    await record_turn_usage(
        user_id=user_id, conversation_id="c-1", channel="telegram",
        result=result, started_at=time.monotonic() - 2.5,
    )

    async with async_session() as db:
        row = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == user_id)
        )).scalar_one()

    assert row.architecture == "sub_agent:workspace"
    assert row.channel == "telegram"
    assert row.input_tokens == 2000
    assert row.output_tokens == 100
    assert row.provider == "anthropic"
    assert row.model == "claude-opus-5"
    assert 2400 <= row.latency_ms <= 3000, f"latence invraisemblable : {row.latency_ms}"


@pytest.mark.asyncio
async def test_record_turn_usage_never_breaks_a_delivered_answer():
    """L'analytique ne doit jamais casser une réponse déjà produite."""
    from app.services.usage_instrumentation import record_turn_usage

    await record_turn_usage(
        user_id="", conversation_id=None, channel="telegram",
        result="pas un état", started_at=0.0,
    )


# ---------------------------------- les canaux doivent enfin écrire quelque chose

@pytest.mark.parametrize("bot", ["telegram_bot"])
def test_channel_bots_record_their_usage(bot):
    """Aujourd'hui aucun des trois n'appelle `log_usage` : l'architecture à
    sous-agents est invisible dans les chiffres. Pin source-grep — le banc
    A/B en dépend."""
    from pathlib import Path

    src = Path(f"app/channels/{bot}.py").read_text(encoding="utf-8")
    assert "record_turn_usage" in src, f"{bot} n'enregistre toujours aucun usage"
    # Le chrono doit partir AVANT l'invocation, sinon la latence mesurée
    # n'est pas celle que l'utilisateur subit.
    assert "_turn_started_at = time.monotonic()" in src, f"{bot} ne chronomètre rien"
    invoke = src.index("agent.ainvoke")
    assert src.index("_turn_started_at = time.monotonic()") < invoke, (
        f"{bot} démarre son chrono APRÈS l'invocation"
    )


def test_web_chat_records_latency():
    from pathlib import Path

    src = Path("app/routers/chat.py").read_text(encoding="utf-8")
    assert "latency_ms" in src
    assert "architecture" in src
