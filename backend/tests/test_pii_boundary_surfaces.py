# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_pii_boundary_surfaces.py
# @brief      C0 (audit 16/07, P0/§6.2) — frontière PII uniforme sur toutes
#             les surfaces : sous-agents spécialistes, canaux, scheduler.
# @license    Elastic License 2.0
# =============================================================================
"""Tests contractuels de la frontière PII.

Contrat (identique au nœud d'outils central, ``tool_node.py``) :
  1. un placeholder émis par le LLM est restauré AVANT l'appel d'outil ;
  2. la PII contenue dans un résultat d'outil est masquée AVANT le retour
     au LLM (cloud sur tiers B/C) ;
  3. toutes les surfaces partagent LE MÊME filtre par ``conversation_id``
     (registre ``conversation_filters``) — sinon les placeholders sont
     irrésolubles d'une surface à l'autre.

Run with:  cd backend && python -m pytest tests/test_pii_boundary_surfaces.py -v
"""
from __future__ import annotations

import importlib
import inspect
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.database import async_session, init_db

EMAIL = "jean.dupont@example.org"


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


def _fresh_conv() -> str:
    return f"conv-pii-{uuid.uuid4()}"


# ── 1. Registre partagé ─────────────────────────────────────────────────────


def test_filters_proxy_exposes_get():
    """factory.py appelait ``_filters.get(...)`` → AttributeError avalée par
    un ``except: pass`` (audit P0). Le shim legacy doit exposer ``get()`` et
    renvoyer l'instance du registre partagé."""
    from app.routers.chat import _filters
    from app.services.conversation_filters import get_filter

    conv = _fresh_conv()
    sf = _filters.get(conv)
    assert sf is not None
    assert sf is get_filter(conv)


# ── 2. Sous-agents spécialistes ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "mod_name", ["telegram_bot", "slack_bot", "discord_bot", "whatsapp"]
)
def test_channel_uses_shared_registry(mod_name):
    """Chaque canal doit utiliser le registre par ``conversation_id`` — un
    dict local par id de plateforme (ou un filtre jetable) rend les
    placeholders irrésolubles pour tool_node et les sous-agents (audit P0)."""
    mod = importlib.import_module(f"app.channels.{mod_name}")
    src = inspect.getsource(mod)
    assert "conversation_filters" in src, mod_name
    assert not hasattr(mod, "_filters"), f"{mod_name} garde un dict de filtres local"


# ── 3b. Contenu en liste de blocs (openai-codex / Responses API) ────────────


def test_content_blocks_flatten_then_deanonymize():
    """gpt-5.6 (tier codex / Responses API) renvoie ``content`` en LISTE de
    blocs ``[{"type": "text", "text": ...}]`` — ``deanonymize`` fait du
    ``str.replace`` et exige une string. Les surfaces doivent aplatir via
    ``content_to_text`` AVANT de restaurer (crash réel Telegram 18/07 :
    ``AttributeError: 'list' object has no attribute 'replace'``)."""
    from app.agent.helpers.message_content import content_to_text
    from app.services.conversation_filters import get_filter

    conv = _fresh_conv()
    sf = get_filter(conv)
    masked = sf.anonymize(f"écris à {EMAIL}", ner_detection=False)
    placeholder = masked.split()[-1]
    assert placeholder.startswith("[") and placeholder.endswith("]")

    blocks = [{"type": "text", "text": f"Mail envoyé à {placeholder}", "index": 0}]
    assert sf.deanonymize(content_to_text(blocks)) == f"Mail envoyé à {EMAIL}"


@pytest.mark.parametrize(
    "mod_name", ["telegram_bot", "slack_bot", "discord_bot", "whatsapp"]
)
def test_channel_flattens_content_before_deanonymize(mod_name):
    """Chaque canal doit extraire la réponse via ``content_to_text(...)`` —
    l'accès brut ``invoke_result["messages"][-1].content`` passé tel quel à
    ``deanonymize`` crashe dès que le tier actif renvoie des blocs (le
    scheduler a son propre aplatissement ; la voix streame du texte)."""
    mod = importlib.import_module(f"app.channels.{mod_name}")
    src = inspect.getsource(mod)
    assert "content_to_text(invoke_result" in src, mod_name


# ── 4. Scheduler ────────────────────────────────────────────────────────────


class _CaptureGraph:
    """Faux graphe : capture l'entrée, répond avec un placeholder connu."""

    def __init__(self, reply: str):
        self._reply = reply
        self.seen: list[dict] = []

    async def ainvoke(self, payload, config=None):
        self.seen.append(payload)
        return {"messages": [SimpleNamespace(content=self._reply, tool_calls=[])]}


@pytest.mark.asyncio
async def test_scheduler_prompt_anonymized_and_reply_restored(monkeypatch):
    """Le prompt d'une tâche planifiée (adresse, consigne personnelle…) ne
    doit pas partir en clair vers le LLM (audit §6.2) ; la livraison à
    l'utilisateur doit restaurer les vraies valeurs."""
    import app.agent.graph as graph_mod
    import app.services.budget_guard as budget_mod
    import app.services.learning.facade_detection as facade_mod
    import app.services.learning.outcome_recording as outcome_mod
    import app.services.scheduler as sched_mod
    from app.models.scheduled_task import ScheduledTask
    from app.models.user import User

    uid = "c0_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()
    async with async_session() as db:
        task = ScheduledTask(user_id=uid, name="brief C0",
                             prompt=f"Envoie le brief quotidien à {EMAIL}",
                             cron_expression="0 8 * * *", channel="web")
        db.add(task)
        await db.commit()
        task_id = task.id

    graph = _CaptureGraph("Brief envoyé à [EMAIL_0].")
    delivered: list[str] = []

    async def _fake_budget(_uid):
        return False

    async def _fake_deliver(_task, content):
        delivered.append(content)

    async def _fake_outcome(**_kw):
        return None

    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: graph)
    monkeypatch.setattr(budget_mod, "check_user_budget", _fake_budget)
    monkeypatch.setattr(sched_mod, "_deliver_result", _fake_deliver)
    monkeypatch.setattr(outcome_mod, "record_scheduled_outcome", _fake_outcome)
    monkeypatch.setattr(facade_mod, "tools_called_from_messages", lambda _m: [])

    await sched_mod._execute_task(task_id)

    # 1. le prompt atteint le LLM SANS la PII en clair
    assert graph.seen, "le graphe n'a pas été invoqué"
    sent = graph.seen[0]["messages"][0].content
    assert EMAIL not in sent
    assert "[EMAIL_" in sent
    # 2. la réponse livrée à l'utilisateur est RESTAURÉE
    assert delivered and EMAIL in delivered[0]
