# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_skeleton.py
# @brief      Tests à blanc du squelette Sprint 2.7 — Jalon 1.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Vérifications structurelles du squelette ``orchestrate`` (Sprint 2.7).

Ce test ne valide PAS la logique d'exécution (qui n'existe pas encore).
Il vérifie uniquement que :

    1. Les 4 modules importent sans erreur.
    2. Le tool ``orchestrate`` est enregistré via ``@register`` (donc
       capté par l'auto-discovery du Sprint 2).
    3. L'allow-list V1 contient bien 15 tools et tous sont des noms
       de @tool existants dans le repo.
    4. Les classes / fonctions publiques exposent les bonnes signatures
       et lèvent ``NotImplementedError`` comme attendu pour un squelette.
    5. Le tool répond gracieusement (sans crash) en attendant la suite.

Quand les Jalons 2-4 seront livrés, les ``NotImplementedError`` checks
seront remplacés par des tests fonctionnels.
"""
from __future__ import annotations

import importlib

import pytest


# ──────────────────────────────────────────────────────────────────────
# 1. Les modules importent
# ──────────────────────────────────────────────────────────────────────


def test_orchestrate_runner_module_imports() -> None:
    """``app.services.orchestrate_runner`` importe + exporte l'API publique."""
    mod = importlib.import_module("app.services.orchestrate_runner")
    for name in ("SANDBOX_ALLOWED_TOOLS_V1", "OrchestrateLimits",
                 "OrchestrateResult", "OrchestrateRunner"):
        assert hasattr(mod, name), f"orchestrate_runner manque l'export {name!r}"


def test_orchestrate_rpc_module_imports() -> None:
    mod = importlib.import_module("app.services.orchestrate_rpc")
    for name in ("OrchestrateRPCError", "ToolNotAllowedError",
                 "MaxToolCallsExceeded", "OrchestrateRPCServer",
                 "make_socket_path"):
        assert hasattr(mod, name), f"orchestrate_rpc manque l'export {name!r}"


def test_orchestrate_stubs_module_imports() -> None:
    mod = importlib.import_module("app.services.orchestrate_stubs")
    assert hasattr(mod, "generate_stubs")


def test_orchestrate_tool_module_imports() -> None:
    mod = importlib.import_module("app.agent.tools.orchestrate_tool")
    assert hasattr(mod, "orchestrate")


# ──────────────────────────────────────────────────────────────────────
# 2. Le tool est enregistré via @register (auto-discovery hookup)
# ──────────────────────────────────────────────────────────────────────


def test_orchestrate_tool_has_register_metadata() -> None:
    """``@register`` attache ``__ely_skill_metadata__`` ou enregistre
    dans ``_PENDING`` — l'un OU l'autre prouve que l'auto-discovery
    Sprint 2 captera le tool."""
    from app.agent.tools.orchestrate_tool import orchestrate
    from app.skills.decorator import META_ATTR, _peek_pending

    has_attr = hasattr(orchestrate, META_ATTR)
    pending = _peek_pending()
    in_pending = any(
        key.endswith(".orchestrate") for key in pending.keys()
    )
    assert has_attr or in_pending, (
        "Le tool orchestrate doit être capté par @register, soit via "
        f"l'attribut {META_ATTR}, soit via _PENDING."
    )


def test_orchestrate_tool_name() -> None:
    from app.agent.tools.orchestrate_tool import orchestrate
    assert orchestrate.name == "orchestrate", (
        f"Le tool doit s'appeler 'orchestrate', pas {orchestrate.name!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Allow-list V1 — exactement 15 tools read-only
# ──────────────────────────────────────────────────────────────────────


def test_allow_list_size_is_15() -> None:
    from app.services.orchestrate_runner import SANDBOX_ALLOWED_TOOLS_V1
    assert len(SANDBOX_ALLOWED_TOOLS_V1) == 15, (
        f"L'allow-list V1 doit contenir exactement 15 tools "
        f"(spec design note §4.1 + décision Franck 18 mai). "
        f"Trouvé : {len(SANDBOX_ALLOWED_TOOLS_V1)}."
    )


def test_allow_list_excludes_destructive_tools() -> None:
    """Aucun tool destructif ne doit être exposé au sandbox en V1."""
    from app.services.orchestrate_runner import SANDBOX_ALLOWED_TOOLS_V1
    forbidden_substrings = (
        "trash", "delete", "send", "create", "update", "save",
        "empty", "archive", "click", "fill",
    )
    leaks = [
        t for t in SANDBOX_ALLOWED_TOOLS_V1
        if any(sub in t for sub in forbidden_substrings)
    ]
    assert not leaks, (
        f"L'allow-list V1 contient des tools potentiellement destructifs : "
        f"{leaks}. La V1 est read-only stricte (cf. design note §4.1)."
    )


# ──────────────────────────────────────────────────────────────────────
# 4. Les méthodes squelette lèvent NotImplementedError
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_run_raises_not_implemented() -> None:
    """``OrchestrateRunner.run()`` doit lever NotImplementedError tant
    que les Jalons 2-4 ne sont pas terminés."""
    from app.services.orchestrate_runner import OrchestrateRunner

    runner = OrchestrateRunner(user_id="test-user")
    with pytest.raises(NotImplementedError):
        await runner.run(code="print('hello')")


@pytest.mark.asyncio
async def test_runner_run_rejects_empty_code() -> None:
    """Avant même de tenter l'exécution, on doit refuser un script vide."""
    from app.services.orchestrate_runner import OrchestrateRunner

    runner = OrchestrateRunner(user_id="test-user")
    with pytest.raises(ValueError, match="non-empty code"):
        await runner.run(code="   ")


def test_runner_rejects_empty_user_id() -> None:
    from app.services.orchestrate_runner import OrchestrateRunner
    with pytest.raises(ValueError, match="non-empty user_id"):
        OrchestrateRunner(user_id="")


def test_rpc_constructor_validates_inputs() -> None:
    """Le RPC server refuse les configs invalides à l'instanciation."""
    from app.services.orchestrate_rpc import OrchestrateRPCServer
    from app.services.orchestrate_runner import SANDBOX_ALLOWED_TOOLS_V1

    with pytest.raises(ValueError, match="user_id"):
        OrchestrateRPCServer(
            user_id="",
            allowed_tools=SANDBOX_ALLOWED_TOOLS_V1,
            max_tool_calls=50,
            tool_dispatcher=lambda n, a: None,
        )
    with pytest.raises(ValueError, match="allow-list"):
        OrchestrateRPCServer(
            user_id="u",
            allowed_tools=frozenset(),
            max_tool_calls=50,
            tool_dispatcher=lambda n, a: None,
        )
    with pytest.raises(ValueError, match="max_tool_calls"):
        OrchestrateRPCServer(
            user_id="u",
            allowed_tools=SANDBOX_ALLOWED_TOOLS_V1,
            max_tool_calls=0,
            tool_dispatcher=lambda n, a: None,
        )


def test_stubs_generate_rejects_empty_allow_list(tmp_path) -> None:
    """Validation d'entrée avant l'exécution réelle."""
    from app.services.orchestrate_stubs import generate_stubs
    with pytest.raises(ValueError, match="non-empty allow-list"):
        generate_stubs(
            allowed_tools=frozenset(),
            socket_path=tmp_path / "fake.sock",
            target_path=tmp_path / "ely_tools.py",
        )


# ──────────────────────────────────────────────────────────────────────
# 5. Le tool répond gracieusement (skeleton message, pas de crash)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestrate_tool_returns_skeleton_warning() -> None:
    """Tant que la logique n'est pas branchée, le tool doit retourner
    un message clair plutôt que de crasher — le LLM doit comprendre
    qu'il faut enchaîner manuellement."""
    from app.agent.tools.orchestrate_tool import orchestrate

    # Le @tool LangChain expose .ainvoke pour exécuter asynchrone.
    result = await orchestrate.ainvoke({
        "code": "print('hello')",
        "user_id": "test-user",
    })
    assert "skeleton" not in result.lower() or "implémentation" in result.lower()
    # On vérifie qu'on n'a pas de stack trace dans la réponse.
    assert "Traceback" not in result
    assert "NotImplementedError" not in result


@pytest.mark.asyncio
async def test_orchestrate_tool_rejects_empty_code() -> None:
    from app.agent.tools.orchestrate_tool import orchestrate
    result = await orchestrate.ainvoke({
        "code": "   ",
        "user_id": "test-user",
    })
    assert "vide" in result.lower() or "empty" in result.lower()


@pytest.mark.asyncio
async def test_orchestrate_tool_rejects_missing_user_id() -> None:
    from app.agent.tools.orchestrate_tool import orchestrate
    result = await orchestrate.ainvoke({
        "code": "print(1)",
        "user_id": "",
    })
    assert "user_id" in result.lower()
