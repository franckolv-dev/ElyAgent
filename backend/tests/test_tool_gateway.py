# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_gateway.py
# @brief      C3a — contrat de la passerelle unique d'exécution d'outils
#             (services/tool_gateway.py) : PII aller-retour, outil inconnu,
#             HITL bloquant. Le comportement fin (vault, idempotence, journal,
#             préférences) reste couvert par les suites existantes qui passent
#             par tool_node → gateway.
# @license    MIT
# =============================================================================
"""Tests de contrat du Tool Gateway (C3a).

Run with:  cd backend && python -m pytest tests/test_tool_gateway.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.database import init_db

EMAIL = "marc.leblanc@example.org"


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


def _ctx(hitl=None):
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    conv = f"conv-gw-{uuid.uuid4()}"
    ctx = GatewayContext(
        user_id="u-gw", conversation_id=conv,
        pii_filter=get_filter(conv), criticality_filter=SecurityFilter(),
        hitl=hitl, memory=None,
    )
    return ctx


class _EchoTool:
    """Outil inoffensif : renvoie l'argument reçu + une PII « récupérée »."""

    name = "echo_tool"

    async def ainvoke(self, args):
        return f"reçu: {args.get('to')} — contact trouvé {EMAIL}"


@pytest.mark.asyncio
async def test_gateway_pii_round_trip():
    """Placeholder restauré AVANT l'outil, PII du résultat re-masquée APRÈS
    (contrat souveraineté du nœud central, désormais porté par la passerelle)."""
    from app.services.tool_gateway import execute_tool_call

    ctx = _ctx()
    masked = ctx.pii_filter.anonymize(f"écris à {EMAIL}", ner_detection=False)
    placeholder = masked.split()[-1]
    assert placeholder.startswith("[EMAIL_")

    msg = await execute_tool_call(
        ctx, {"name": "echo_tool", "args": {"to": placeholder}, "id": "t1"},
        {"echo_tool": _EchoTool()},
    )
    # L'outil a reçu la VRAIE adresse (écho re-masqué au retour) et rien ne
    # repart en clair vers le LLM.
    assert EMAIL not in msg["content"]
    assert "reçu: [EMAIL_" in msg["content"]
    assert EMAIL in ctx.pii_filter.deanonymize(msg["content"])


@pytest.mark.asyncio
async def test_gateway_unknown_tool_returns_tool_message():
    from langchain_core.messages import ToolMessage
    from app.services.tool_gateway import execute_tool_call

    msg = await execute_tool_call(_ctx(), {"name": "nope", "args": {}, "id": "t2"}, {})
    assert isinstance(msg, ToolMessage)
    assert "non disponible" in msg.content


@pytest.mark.asyncio
async def test_gateway_hitl_deny_blocks_execution():
    """Un deny HITL retourne le refus SANS exécuter l'outil (fail-closed)."""
    from app.services.security_filter import ALWAYS_CRITICAL_TOOLS
    from app.services.tool_gateway import execute_tool_call

    critical_name = sorted(ALWAYS_CRITICAL_TOOLS)[0]
    prompts: list[str] = []

    class _Hitl:
        async def request_validation(self, description, user_id):
            prompts.append(description)
            return ("deny", "non merci")

    class _NeverRun:
        name = critical_name

        async def ainvoke(self, args):
            raise AssertionError("ne doit JAMAIS s'exécuter après un deny")

    msg = await execute_tool_call(
        _ctx(hitl=_Hitl()),
        {"name": critical_name, "args": {"query": "x"}, "id": "t3"},
        {critical_name: _NeverRun()},
    )
    assert "refusée" in msg["content"]
    assert prompts, "le HITL doit avoir été sollicité"


# ── C3b — capacités absorbées des spécialistes ──────────────────────────────


@pytest.mark.asyncio
async def test_gateway_self_mail_skips_hitl():
    """Envoi à sa PROPRE adresse : pas de HITL — le digest planifié de 6 h
    part sans confirmation impossible à donner (capacité ex-spécialistes,
    généralisée par la passerelle)."""
    from app.database import async_session
    from app.models.user import User
    from app.services.tool_gateway import execute_tool_call

    uid = "gwsm_" + uuid.uuid4().hex[:8]
    email = f"{uid}@moi.example"
    async with async_session() as db:
        db.add(User(id=uid, username=uid, email=email, hashed_password="x"))
        await db.commit()

    class _NoHitl:
        async def request_validation(self, description, user_id):
            raise AssertionError("HITL sollicité pour un self-mail")

    sent: dict = {}

    class _Send:
        name = "gmail_send_email"

        async def ainvoke(self, args):
            sent.update(args)
            return "Message envoyé."

    ctx = _ctx(hitl=_NoHitl())
    ctx.user_id = uid
    msg = await execute_tool_call(
        ctx,
        {"name": "gmail_send_email",
         "args": {"to": email, "subject": "digest", "body": "…"}, "id": "t4"},
        {"gmail_send_email": _Send()},
    )
    assert "envoyé" in msg["content"]
    assert sent.get("to") == email


@pytest.mark.asyncio
async def test_gateway_google_multiaccount_alias():
    """L'alias ``account`` cible le GoogleAccount lié (multi-boîtes) ; l'arg
    est retiré avant l'outil (les wrappers Google ne l'acceptent pas)."""
    from app.database import async_session
    from app.models.google_account import GoogleAccount
    from app.models.user import User
    from app.services.tool_gateway import execute_tool_call

    uid = "gwma_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=uid, email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()
    async with async_session() as db:
        db.add(GoogleAccount(user_id=uid, alias="pro",
                             email=f"pro-{uid}@boulot.example",
                             credentials_json='{"tok":"pro"}'))
        await db.commit()

    captured: dict = {}

    class _List:
        name = "gmail_list_emails"

        async def ainvoke(self, args):
            captured.update(args)
            return "3 messages."

    ctx = _ctx()
    ctx.user_id = uid
    msg = await execute_tool_call(
        ctx,
        {"name": "gmail_list_emails",
         "args": {"query": "in:inbox", "account": "pro"}, "id": "t5"},
        {"gmail_list_emails": _List()},
    )
    assert "messages" in msg["content"]
    assert captured.get("user_google_credentials_json") == '{"tok":"pro"}'
    assert "account" not in captured
