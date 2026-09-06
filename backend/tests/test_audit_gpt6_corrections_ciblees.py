# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_audit_gpt6_corrections_ciblees.py
# @brief      Audit GPT-6 du 06/09/2026, lot 2 « corrections ciblées » :
#             F08 (deux noms non définis que la CI ne voyait pas) et
#             F09 (un garde préalable qui plante laissait passer l'action).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Trois reproductions de l'audit, inversées en tests de non-régression.

F08 — `F821` était ignorée par ruff : `save_app_config` appelait un `logger`
jamais défini (l'interface annonçait une erreur APRÈS un enregistrement
réel), et `get_fallback_llms` lisait une variable `model` inexistante — le
candidat Gemini disparaissait de la chaîne de repli, en silence, à chaque
appel.

F09 — la passerelle exécutait l'outil quand le hook `pre_execute` levait.
Or le dispatcher des missions porte par ce hook les disjoncteurs de budget :
un service de budget en panne AUTORISAIT ce qu'il devait arbitrer.

Run with:  cd backend && python -m pytest tests/test_audit_gpt6_corrections_ciblees.py -v
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


# ── F08a — le wizard Google enregistre ET répond ─────────────────────────────


@pytest.mark.asyncio
async def test_le_wizard_google_repond_apres_avoir_enregistre(monkeypatch):
    import app.services.system_config as sc
    from app.routers.google import SaveAppConfigRequest, save_app_config

    ecrits: list[tuple[str, str]] = []

    async def _set_config(key, value, **_kw):
        ecrits.append((key, value))

    monkeypatch.setattr(sc, "set_config", _set_config)

    reponse = await save_app_config(
        SaveAppConfigRequest(client_id="id-123", client_secret="secret-456"),
        admin=SimpleNamespace(username="franck"),
    )

    assert reponse == {"configured": True}
    assert [k for k, _v in ecrits] == ["google_client_id", "google_client_secret"]


# ── F08b — Gemini reste dans la chaîne de repli ──────────────────────────────


def test_gemini_figure_dans_les_replis_quand_sa_cle_est_connue(monkeypatch):
    import app.services.llm_provider as lp

    class _FauxGemini:
        def __init__(self, **kw):
            self.kw = kw

    import langchain_google_genai

    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", _FauxGemini)
    monkeypatch.setitem(lp._runtime, "provider", "anthropic")
    monkeypatch.setitem(lp._runtime, "key_gemini", "cle-de-test")

    labels = [label for label, _llm in lp.get_fallback_llms()]

    assert "gemini/gemini-2.5-flash" in labels, (
        "le candidat Gemini a disparu de la chaîne de repli : son constructeur "
        "n'a pas été atteint"
    )


# ── F09 — un garde préalable qui plante SUSPEND l'action ─────────────────────


class _OutilEspion:
    name = "outil_espion"

    def __init__(self) -> None:
        self.appels = 0

    async def ainvoke(self, args):
        self.appels += 1
        return "exécuté"


def _ctx(pre_execute):
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    conv = f"conv-f09-{uuid.uuid4()}"
    return GatewayContext(
        user_id="u-f09", conversation_id=conv,
        pii_filter=get_filter(conv), criticality_filter=SecurityFilter(),
        hitl=None, memory=None, pre_execute=pre_execute,
    )


@pytest.mark.asyncio
async def test_un_garde_prealable_qui_plante_n_execute_pas_l_outil():
    from app.services.tool_gateway import execute_tool_call

    async def _garde_en_panne(_tool_name, _args):
        raise RuntimeError("service de budget injoignable")

    outil = _OutilEspion()
    meta: dict = {}
    msg = await execute_tool_call(
        _ctx(_garde_en_panne),
        {"name": outil.name, "args": {}, "id": "t-f09"},
        {outil.name: outil}, meta=meta,
    )

    assert outil.appels == 0, "l'outil a tourné alors que son garde était en panne"
    assert meta.get("success") is not True
    contenu = msg["content"] if isinstance(msg, dict) else msg.content
    assert "non exécutée" in contenu.lower()
    assert "budget injoignable" in contenu


@pytest.mark.asyncio
async def test_un_garde_prealable_sain_laisse_passer():
    from app.services.tool_gateway import execute_tool_call

    async def _garde_ok(_tool_name, _args):
        return None

    outil = _OutilEspion()
    meta: dict = {}
    await execute_tool_call(
        _ctx(_garde_ok), {"name": outil.name, "args": {}, "id": "t-f09b"},
        {outil.name: outil}, meta=meta,
    )

    assert outil.appels == 1
    assert meta.get("success") is True
