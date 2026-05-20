# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_delegation.py
# @brief      Tests Option C — délégation tier C pour orchestrate(intent=...).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests Option C (Sprint 2.7, 20 mai 2026) — délégation tier C.

Le tool ``orchestrate`` accepte désormais deux modes :
    - ``orchestrate(code="...")`` : exécution directe (path historique).
    - ``orchestrate(intent="...")`` : un LLM tier C écrit le script en
      interne, puis le runner l'exécute.

Couvre :
    1. La signature publique du tool expose bien les deux args.
    2. ``_strip_markdown_fences`` retire les fences ```python correctement.
    3. ``describe_allowed_tools_for_prompt`` produit une description
       compacte non vide pour ``SANDBOX_ALLOWED_TOOLS_V1``.
    4. Avec ``intent`` fourni et tier C mocké, l'appel à
       ``OrchestrateRunner`` se fait avec le code généré par le LLM.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


# ──────────────────────────────────────────────────────────────────────
# 1. Signature publique — les deux args sont exposés
# ──────────────────────────────────────────────────────────────────────


def test_orchestrate_tool_exposes_intent_and_code() -> None:
    """Le @tool LangChain doit voir `intent` et `code` dans ses params."""
    from app.agent.tools.orchestrate_tool import orchestrate

    # ``args`` est la propriété LangChain qui expose les params publics.
    args = orchestrate.args
    assert "intent" in args, f"`intent` manquant dans {list(args)}"
    assert "code" in args, f"`code` manquant dans {list(args)}"
    # user_id reste injecté côté serveur — ne doit PAS apparaître dans
    # le schema public exposé au LLM.
    assert "user_id" not in args


# ──────────────────────────────────────────────────────────────────────
# 2. _strip_markdown_fences
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Cas standard : ```python ... ```
        ("```python\nprint('hi')\n```", "print('hi')"),
        # Cas court : ``` ... ```
        ("```\nprint(1)\n```", "print(1)"),
        # Cas py
        ("```py\nx = 1\n```", "x = 1"),
        # Pas de fence — laissé tel quel
        ("print('hi')", "print('hi')"),
        # Espaces avant/après
        ("  ```python\nprint(1)\n```  ", "print(1)"),
        # Fence ouvrante seule (LLM tronqué)
        ("```python\nprint(1)", "print(1)"),
    ],
)
def test_strip_markdown_fences_handles_common_shapes(raw, expected) -> None:
    from app.agent.tools.orchestrate_tool import _strip_markdown_fences
    assert _strip_markdown_fences(raw) == expected


# ──────────────────────────────────────────────────────────────────────
# 3. describe_allowed_tools_for_prompt
# ──────────────────────────────────────────────────────────────────────


def test_describe_allowed_tools_for_prompt_renders_all_v1_stubs() -> None:
    from app.services.orchestrate_runner import SANDBOX_ALLOWED_TOOLS_V1
    from app.services.orchestrate_stubs import describe_allowed_tools_for_prompt

    text = describe_allowed_tools_for_prompt(SANDBOX_ALLOWED_TOOLS_V1)
    # Should contain one bullet per V1 tool. Use the names as anchors.
    for name in SANDBOX_ALLOWED_TOOLS_V1:
        assert f"`{name}(" in text, (
            f"Le stub `{name}(...)` doit apparaître dans la description "
            f"prompt. Description reçue (premiers 300 chars) :\n{text[:300]}"
        )
    # Should not leak the user_id arg — it's injected server-side.
    assert "user_id" not in text


def test_describe_allowed_tools_for_prompt_handles_empty_set() -> None:
    from app.services.orchestrate_stubs import describe_allowed_tools_for_prompt
    text = describe_allowed_tools_for_prompt(frozenset())
    assert text == "(aucun outil disponible)"


# ──────────────────────────────────────────────────────────────────────
# 4. End-to-end : intent → tier C mock → OrchestrateRunner reçoit le code
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intent_delegates_to_tier_c_and_runs_generated_code(
    monkeypatch,
) -> None:
    """L'intégralité du path Option C, sans appel LLM réel.

    Étapes :
        1. Mock ``get_llm_for_tier`` → retourne un faux LLM dont
           ``ainvoke`` renvoie un script précis.
        2. Mock ``OrchestrateRunner`` → enregistre le ``code`` reçu, ne
           lance pas vraiment le sandbox.
        3. Appelle le tool avec ``intent="..."``.
        4. Vérifie que le mock runner a vu le code généré par le LLM.
    """
    # ── Mock LLM tier C ──────────────────────────────────────────────
    class _FakeContent:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        def __init__(self, script: str):
            self._script = script

        async def ainvoke(self, messages):
            return _FakeContent(content=self._script)

    GENERATED = "from ely_tools import github_repo_stats\nprint(github_repo_stats())\n"
    fake_llm = _FakeLLM(f"```python\n{GENERATED}```")

    def _fake_get_llm_for_tier(tier):
        return fake_llm

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", _fake_get_llm_for_tier
    )

    # ── Mock runner ──────────────────────────────────────────────────
    received_codes: list[str] = []

    class _FakeRunner:
        def __init__(self, *, user_id, **_kw):
            self.user_id = user_id

        async def run(self, *, code):
            received_codes.append(code)
            from app.services.orchestrate_runner import OrchestrateResult
            return OrchestrateResult(
                stdout="ok\n",
                stderr="",
                exit_code=0,
                duration_seconds=0.1,
                tools_dispatched=["github_repo_stats"],
                truncated=False,
                truncation_reason="",
            )

    monkeypatch.setattr(
        "app.services.orchestrate_runner.OrchestrateRunner", _FakeRunner
    )

    # ── Invocation ───────────────────────────────────────────────────
    from app.agent.tools.orchestrate_tool import orchestrate
    result = await orchestrate.ainvoke({
        "intent": "Donne-moi les stats GitHub du repo",
        "code": "",
        "user_id": "test-user-delegation",
    })

    # ── Assertions ──────────────────────────────────────────────────
    assert received_codes, "Le runner n'a pas été appelé"
    assert "github_repo_stats" in received_codes[0], (
        f"Code reçu par le runner inattendu :\n{received_codes[0]!r}"
    )
    # Le fence ```python doit être strippé avant exécution
    assert not received_codes[0].startswith("```"), (
        "Les fences markdown n'ont pas été retirés avant l'exécution"
    )
    # Le retour doit contenir le stdout du sandbox + le meta tools=...
    assert "github_repo_stats" in result
    assert "ok" in result


@pytest.mark.asyncio
async def test_intent_with_tier_c_unavailable_returns_clear_error(
    monkeypatch,
) -> None:
    """Si ``get_llm_for_tier`` retourne None (tier C non configuré),
    le tool doit renvoyer un message d'erreur lisible plutôt que de
    crasher."""
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: None
    )
    from app.agent.tools.orchestrate_tool import orchestrate
    result = await orchestrate.ainvoke({
        "intent": "fais X",
        "code": "",
        "user_id": "test-user",
    })
    assert "erreur" in result.lower()
    assert "tier c" in result.lower() or "indispo" in result.lower() or "unavailable" in result.lower()
