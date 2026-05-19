# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/orchestrate_stubs.py
# @brief      Stub generator pour le module ``ely_tools.py`` du sandbox.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    0.3.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Stub generator pour ``ely_tools.py`` — Jalon 3.

Génère un module Python ``ely_tools.py`` éphémère par run, contenant :

1. Un helper ``_rpc(tool, **kwargs)`` qui sérialise l'appel en
   length-prefixed JSON et le transmet au serveur RPC UDS via
   ``ELY_RPC_SOCKET`` (variable d'env injectée par le runner).
2. Un ``_call_lock`` global (threading.Lock) — sérialise les appels
   même si le script LLM lance plusieurs threads. C'est la mitigation
   de la faille de course concurrente RPC sans request-id (fix Hermes
   v0.12.0).
3. Une fonction stub par tool de l'allow-list. Chaque stub a la même
   signature que le @tool réel, **moins** les paramètres
   ``Annotated[..., InjectedToolArg]`` (notamment ``user_id``) — qui
   sont injectés côté parent par le RPC server. Le script LLM ne les
   voit jamais et ne peut donc pas tenter de cibler un autre user.
4. Trois helpers QoL : ``json_parse``, ``shell_quote``, ``retry``.

Self-contained
==============
Le module généré n'importe **que** des modules stdlib. Aucun import de
``app.*`` — le child sandbox tourne avec un ``PYTHONPATH`` réduit à
``{tmpdir}`` (§4.5), il n'a donc pas accès aux modules ELY.

Idempotence
===========
``generate_stubs()`` peut être appelé plusieurs fois sur la même cible
sans état partagé. Chaque appel écrase complètement le fichier cible.
"""
from __future__ import annotations

import inspect
import logging
import textwrap
import typing
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin

from langchain_core.tools import InjectedToolArg

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Module preamble — _rpc helper + _call_lock + protocol constants
# ──────────────────────────────────────────────────────────────────────
#
# Note importante : le préambule doit être un module Python valide
# **autonome** — pas d'import d'app.*, uniquement stdlib. Toutes les
# constantes de protocole (header size, max payload) sont dupliquées
# ici depuis ``orchestrate_rpc.py`` pour que le child reste indépendant.
# Toute modification du protocole doit être faite aux deux endroits.

_MODULE_PREAMBLE = '''\
"""ely_tools — auto-generated RPC stubs for the orchestrate sandbox.

DO NOT EDIT — regenerated on every run by
``app.services.orchestrate_stubs.generate_stubs``.

This module is imported by the script LLM-generated inside the sandbox.
Each function below is a thin RPC stub that delegates to the parent
backend via a Unix Domain Socket. The real implementation runs in the
backend process with full credentials — the sandbox never sees secrets.
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import struct
import threading
import time
from typing import Any


_SOCKET_PATH = os.environ["ELY_RPC_SOCKET"]
_HEADER_FMT = "!I"
_HEADER_SIZE = 4
_call_lock = threading.Lock()


class OrchestrateError(Exception):
    """Raised when the RPC server returns an error response."""


def _rpc(_tool: str, **kwargs: Any) -> Any:
    """Send one RPC request to the parent server and return its result.

    Args:
        _tool: name of the tool to invoke (must be in the allow-list).
        **kwargs: arguments forwarded as-is to the real tool.

    Returns:
        Whatever the real tool returned (typed as the tool documents).

    Raises:
        OrchestrateError: if the server responded with ok=False.
        ConnectionError: if the socket is closed (parent died).
    """
    with _call_lock:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(_SOCKET_PATH)
            payload = json.dumps(
                {"tool": _tool, "args": kwargs}, default=str
            ).encode("utf-8")
            s.sendall(struct.pack(_HEADER_FMT, len(payload)) + payload)
            header = _recv_exact(s, _HEADER_SIZE)
            (length,) = struct.unpack(_HEADER_FMT, header)
            response_bytes = _recv_exact(s, length)
            response = json.loads(response_bytes.decode("utf-8"))
    if not response.get("ok", False):
        err = response.get("error", "unknown RPC error")
        err_type = response.get("error_type", "OrchestrateError")
        raise OrchestrateError(f"{err_type}: {err}")
    return response.get("result")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(
                f"RPC parent closed connection after {len(buf)}/{n} bytes"
            )
        buf.extend(chunk)
    return bytes(buf)


# ──────────────────────────────────────────────────────────────────
# QoL helpers — exposed for free to the script LLM
# ──────────────────────────────────────────────────────────────────


def json_parse(text: str) -> Any:
    """json.loads but tolerant to literal \\t \\n inside JSON strings.

    Some tool outputs (e.g. terminal captures, raw HTML excerpts) contain
    unescaped control characters that strict json.loads rejects. This
    helper retries with the control chars escaped, so the LLM does not
    have to remember to clean them.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text.replace("\\t", "\\\\t").replace("\\n", "\\\\n"))


def shell_quote(s: str) -> str:
    """Alias of shlex.quote — safe interpolation in shell-style strings."""
    return shlex.quote(s)


def retry(fn, max_attempts: int = 3, delay: float = 2.0):
    """Retry ``fn()`` with exponential backoff. Re-raises after max attempts.

    Use for flaky network calls (web fetches, third-party APIs). Each
    attempt waits ``delay * (2 ** (attempt - 1))`` seconds before retry.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(delay * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


# ──────────────────────────────────────────────────────────────────
# Tool stubs — auto-generated from the registry below
# ──────────────────────────────────────────────────────────────────

'''


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def generate_stubs(
    *,
    allowed_tools: frozenset[str],
    socket_path: Path,
    target_path: Path,
) -> None:
    """Écrit ``ely_tools.py`` dans ``target_path``.

    Args:
        allowed_tools: ``SANDBOX_ALLOWED_TOOLS_V1`` (les 15 tools
            read-only de la V1).
        socket_path: path UDS du run courant (utilisé pour vérification
            d'existence du dossier parent — pas écrit dans le fichier).
        target_path: typiquement ``{tmpdir}/ely_tools.py``.

    Raises:
        ValueError: si l'allow-list est vide ou si un tool listé n'a
            pas pu être trouvé dans le registry.
        FileNotFoundError: si le parent de ``socket_path`` n'existe pas.
    """
    if not allowed_tools:
        raise ValueError("generate_stubs requires a non-empty allow-list")
    if not socket_path.parent.exists():
        raise FileNotFoundError(
            f"Socket parent dir does not exist: {socket_path.parent}"
        )

    # Import lazily — we don't want to pay the cost of loading the full
    # skill registry every time this module is imported (e.g. in tests
    # that don't exercise generate_stubs).
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    # The skill registry may not be bootstrapped yet in some entry points
    # (CLI scripts, isolated tests). ``register_all`` is idempotent so
    # it is safe to call here even if main.py already ran it.
    register_all()
    all_tools = {t.name: t for t in get_skill_registry().all_tools}

    missing = sorted(allowed_tools - all_tools.keys())
    if missing:
        raise ValueError(
            f"Tools in allow-list but not found in registry: {missing}. "
            "Check tool names in SANDBOX_ALLOWED_TOOLS_V1 — they must "
            "match the @tool decorator's ``name`` attribute."
        )

    stub_blocks: list[str] = []
    for tool_name in sorted(allowed_tools):
        tool = all_tools[tool_name]
        try:
            block = _render_stub(tool_name, tool)
        except Exception as exc:
            raise ValueError(
                f"Could not render stub for tool {tool_name!r}: {exc}"
            ) from exc
        stub_blocks.append(block)

    module_text = _MODULE_PREAMBLE + "\n\n".join(stub_blocks) + "\n"
    target_path.write_text(module_text, encoding="utf-8")
    logger.debug(
        "generate_stubs: wrote %d-byte ely_tools.py with %d stubs at %s",
        len(module_text), len(stub_blocks), target_path,
    )


# ──────────────────────────────────────────────────────────────────────
# Internal — per-tool rendering
# ──────────────────────────────────────────────────────────────────────


def _render_stub(tool_name: str, tool: Any) -> str:
    """Render one Python function stub from a LangChain @tool."""
    callable_ = _underlying_callable(tool)
    if callable_ is None:
        raise RuntimeError("tool has neither .coroutine nor .func — cannot introspect")

    # Most tool modules use ``from __future__ import annotations``, which
    # turns every annotation into a raw string (PEP 563). ``inspect`` won't
    # resolve those — we need ``typing.get_type_hints`` with
    # ``include_extras=True`` to evaluate the strings AND keep the
    # ``Annotated[...]`` metadata that flags ``InjectedToolArg``.
    sig = inspect.signature(callable_)
    try:
        resolved_hints = typing.get_type_hints(callable_, include_extras=True)
    except Exception:  # noqa: BLE001 — best effort, fall back to raw annotations
        resolved_hints = {}

    visible_params: list[inspect.Parameter] = []
    for name, param in sig.parameters.items():
        annotation = resolved_hints.get(name, param.annotation)
        if _is_injected_arg(annotation):
            continue
        # Replace the (possibly string) annotation with the resolved one so
        # downstream formatting works on real types.
        if name in resolved_hints:
            param = param.replace(annotation=annotation)
        visible_params.append(param)

    sig_str = _format_signature(visible_params)
    body_args = ", ".join(f"{p.name}={p.name}" for p in visible_params)
    rpc_call = f'_rpc("{tool_name}", {body_args})' if body_args else f'_rpc("{tool_name}")'

    docstring_line = _first_doc_line(getattr(tool, "description", "") or "")

    # Plain Python source — no f-string templating in the stub itself,
    # just literal text the LLM can read.
    return textwrap.dedent(f'''\
        def {tool_name}({sig_str}) -> Any:
            """{docstring_line} (RPC stub.)"""
            return {rpc_call}''')


def _underlying_callable(tool: Any) -> Any:
    """Return the wrapped async or sync function behind a LangChain tool."""
    return getattr(tool, "coroutine", None) or getattr(tool, "func", None)


def _is_injected_arg(annotation: Any) -> bool:
    """True if the annotation is ``Annotated[..., InjectedToolArg]``."""
    if annotation is inspect.Parameter.empty:
        return False
    if get_origin(annotation) is not Annotated:
        return False
    # The first arg of Annotated is the underlying type, the rest are
    # metadata. We look for an InjectedToolArg instance (or the class
    # itself, depending on how the user wrote it).
    for extra in get_args(annotation)[1:]:
        if extra is InjectedToolArg or isinstance(extra, InjectedToolArg):
            return True
    return False


def _format_signature(params: list[inspect.Parameter]) -> str:
    """Render a list of Parameters as a comma-separated signature string."""
    pieces: list[str] = []
    for p in params:
        pieces.append(_format_param(p))
    return ", ".join(pieces)


def _format_param(p: inspect.Parameter) -> str:
    """Format one Parameter as ``name``, ``name: T``, ``name = default``, etc."""
    parts = [p.name]
    if p.annotation is not inspect.Parameter.empty:
        annotation_str = _annotation_to_str(p.annotation)
        parts.append(f": {annotation_str}")
    if p.default is not inspect.Parameter.empty:
        parts.append(f" = {_default_to_str(p.default)}")
    return "".join(parts)


def _annotation_to_str(annotation: Any) -> str:
    """Best-effort stringification of a type annotation for the stub.

    Unwraps ``Annotated[T, ...]`` to ``T``. Falls back to ``Any`` for
    anything we can't print cleanly (e.g. parametrised generics in some
    Python versions).
    """
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    if annotation is inspect.Parameter.empty:
        return "Any"
    if isinstance(annotation, type):
        # Builtin types: ``str``, ``int``, ``list``, …
        return annotation.__name__
    # typing.Optional[str], list[str], dict[str, Any], … — str() gives a
    # readable form. We strip ``typing.`` prefix for compactness.
    text = str(annotation).replace("typing.", "")
    return text or "Any"


def _default_to_str(value: Any) -> str:
    """Render a parameter default as Python source.

    Most defaults are primitives (str, int, bool, None) — ``repr`` does
    the job. Falls back to ``None`` for opaque objects to avoid emitting
    something the LLM can't reason about.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return repr(value)
    if isinstance(value, (list, tuple, dict)):
        try:
            return repr(value)
        except Exception:
            return "None"
    return "None"


def _first_doc_line(text: str) -> str:
    """Extract a single-line description from a (possibly multiline) docstring.

    The first non-empty line, stripped, is returned. Used for the stub
    docstring so the LLM gets a one-shot reminder of what the tool does.
    Quotes are stripped to avoid breaking the triple-quoted docstring.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            # Escape triple quotes defensively (very rare in practice).
            return stripped.replace('"""', "'''")
    return "RPC stub for an ELY tool."


__all__ = ["generate_stubs"]
