# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/orchestrate_runner.py
# @brief      Programmatic Tool Calling — façade publique du sandbox orchestrate.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    0.4.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Programmatic Tool Calling — Sprint 2.7 (``orchestrate``).

Le LLM principal émet **un seul tool call** ``orchestrate(code=...)`` dont
le contenu est un script Python qui chaîne N appels d'outils en local.
Le script tourne dans un sandbox isolé (subprocess), parle au parent via
un RPC sur Unix Domain Socket, et seul son ``stdout`` final remonte au
contexte du LLM. Économies tokens attendues : 70-95% sur les workflows
multi-tools.

Pattern d'inspiration : Hermes Agent ``tools/code_execution_tool.py``
(Nous Research, MIT). Design note de référence dans le repo local :
``docs/external-references/hermes-zero-context-cost-turns.md``.
Implémentation : code maison, adapté à l'archi ELY (HITL, anonymisation,
multi-tier, Docker).

Décisions consolidées (19 mai 2026 — validées Franck)
=====================================================

§4.5 — Isolation du child Python
--------------------------------
Choix : **subprocess + PYTHONPATH whitelist**, *pas* Docker-in-Docker.

- ``subprocess.Popen`` lance le script dans le même container Docker que
  le backend.
- ``PYTHONPATH`` du child = ``{tmpdir}`` uniquement (où vivent
  ``script.py`` et ``ely_tools.py``). Le path ``backend/`` n'est jamais
  exposé — donc le script LLM ne peut PAS faire
  ``from app.services.vault_service import VAULT_KEY``.
- ``env`` du child filtré par préfixe : on ne laisse passer que
  ``PATH``, ``HOME``, ``USER``, ``LANG``, ``LC_*``, ``TERM``, ``TMPDIR``,
  ``SHELL``, ``LOGNAME``, ``XDG_*``, ``PYTHONDONTWRITEBYTECODE``, ``TZ``,
  ``ELY_RPC_SOCKET``. Toute var contenant ``KEY``, ``TOKEN``, ``SECRET``,
  ``PASSWORD``, ``CREDENTIAL``, ``PASSWD``, ``AUTH`` est bloquée même si
  son préfixe est whitelisté.
- ``HOME`` réécrit vers ``{tmpdir}/home/`` pour ne pas exposer le vrai
  ``~`` du process backend.
- ``os.setsid`` pour isoler le process group → kill propre si timeout.

Trade-off accepté : la sécurité repose sur la rigueur du scrubbing. Tout
ajout d'une nouvelle classe de secret au backend doit penser au sandbox
(d'où le fuzz testing dans les tests).

§4.4 — Adapter completion_guard
-------------------------------
Choix : **le RPC server logge les tools dispatchés + union dans le guard**.

- À chaque dispatch RPC, le serveur ajoute le nom du tool à un set
  ``tools_dispatched_via_sandbox`` exposé via la méthode
  ``OrchestrateRunner.last_run_tools_dispatched()``.
- Le retour du tool ``orchestrate`` au LLM inclut, *en plus du stdout du
  script*, un champ structuré indiquant la liste des tools réellement
  appelés. Le nœud agent récupère cette liste et la fournit à
  ``completion_guard.detect_unbacked_completion_claim`` comme nouvelle
  source ``tools_called_via_sandbox``. Le guard fait l'union avec les
  tools appelés directement (hors sandbox) — pas de bypass, pas de
  faux positif sur les scripts read-only.

Allow-list V1 (15 tools read-only)
==================================
Voir ``SANDBOX_ALLOWED_TOOLS_V1`` plus bas. Aucun tool destructif n'est
exposé au sandbox en V1 (cf. design note §4.1 — option A). Toute action
qui modifie l'état (gmail_trash_*, drive_delete_file, gmail_send_*,
notes_create, …) doit revenir au LLM principal qui passera par le flow
HITL standard.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.services.orchestrate_rpc import OrchestrateRPCServer
from app.services.orchestrate_stubs import generate_stubs

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Env scrubbing constants
# ──────────────────────────────────────────────────────────────────────
#
# Inspired by Hermes' ``_SAFE_ENV_PREFIXES`` / ``_SECRET_SUBSTRINGS``
# (see ``hermes-agent-main/tools/code_execution_tool.py`` line ~1034).
# Adapted for ELY:
#   - replaced HERMES_ prefix by ELY_
#   - dropped PYTHONPATH from the whitelist (we override it explicitly to
#     {tmpdir} only, otherwise the child would inherit the backend's
#     PYTHONPATH and could ``from app.services... import``)
#   - dropped VIRTUAL_ENV/CONDA: the child uses sys.executable, no need
#     to point at another venv

_SAFE_ENV_PREFIXES: tuple[str, ...] = (
    "PATH", "HOME", "USER", "LANG", "LC_", "TERM",
    "TMPDIR", "TMP", "TEMP", "SHELL", "LOGNAME",
    "XDG_", "PYTHONDONTWRITEBYTECODE", "TZ",
    "ELY_",
)

_SECRET_SUBSTRINGS: tuple[str, ...] = (
    "KEY", "TOKEN", "SECRET", "PASSWORD",
    "CREDENTIAL", "PASSWD", "AUTH",
)


# ──────────────────────────────────────────────────────────────────────
# Allow-list V1 — 15 tools read-only
# ──────────────────────────────────────────────────────────────────────
#
# Cette frozenset est la **source de vérité** pour ce que le sandbox peut
# appeler. Le stub generator (``orchestrate_stubs``) lit cette liste pour
# produire ``ely_tools.py``. Le RPC server (``orchestrate_rpc``) la lit
# pour rejeter tout appel hors-liste avec une erreur explicite.
#
# Critères de sélection V1 :
#   - read-only (aucun side-effect persistant côté user)
#   - bien testé en prod (utilisé dans le scénario screencast ou
#     manuellement par Franck depuis ≥ 1 semaine)
#   - signature simple (idéalement seulement ``user_id`` comme injected)
#
# Tools intentionnellement exclus en V1 (à ajouter en V2 après usage) :
#   - gmail_trash_*, drive_delete_*, gmail_send_*  → destructifs
#   - notes_create / notes_update / notes_delete   → écriture
#   - memory_archive / save_user_preference        → écriture mémoire
#   - browser_click / browser_fill                 → side-effect web
SANDBOX_ALLOWED_TOOLS_V1: frozenset[str] = frozenset({
    # Gmail (read)
    "gmail_list_emails",
    "gmail_read_email",
    "gmail_search_for_cleanup",
    # Calendar (read)
    "calendar_list_events",
    # Drive (read)
    "drive_list_files",
    "drive_read_file",
    # Web (read — search only, no fetch in V1 to stay strictly read-only.
    # ``browser_get_text`` is excluded because it requires a prior
    # ``browser_navigate`` that mutates the user's Playwright session.)
    "web_search",
    # System read-only diagnostics — useful for audits inside scripts.
    "system_list_scheduled_tasks",
    # Knowledge / mémoire (read)
    "knowledge_search",
    "knowledge_list",
    "memory_search",
    "memory_recent",
    "search_past_conversations_tool",
    # GitHub (read)
    "github_repo_stats",
    "github_traffic_stats",
})


# ──────────────────────────────────────────────────────────────────────
# Limites de ressources (configurables plus tard via app.config)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrchestrateLimits:
    """Limites de ressources appliquées au sandbox.

    Valeurs par défaut alignées avec Hermes (validées sur des workflows
    réels), légèrement plus conservatives sur ``stdout`` pour rester
    compatible avec nos contraintes de fenêtre LLM tier C.
    """

    timeout_seconds: int = 300
    max_tool_calls: int = 50
    max_stdout_bytes: int = 50_000
    max_stderr_bytes: int = 10_000
    # head/tail split de la troncature stdout : 40% début, 60% fin —
    # garantit que la conclusion du script (généralement la dernière
    # ligne) arrive toujours au LLM.
    stdout_head_ratio: float = 0.4
    # Délai après SIGTERM avant SIGKILL.
    sigkill_grace_seconds: float = 5.0


# ──────────────────────────────────────────────────────────────────────
# Résultat d'un run sandbox
# ──────────────────────────────────────────────────────────────────────


@dataclass
class OrchestrateResult:
    """Résultat structuré d'un run ``orchestrate``.

    Le champ ``tools_dispatched`` est consommé par le wiring
    ``completion_guard`` (§4.4 — décision actée). Le LLM principal ne
    voit que ``stdout`` (re-formaté), pas la mécanique RPC.
    """

    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    # Liste ordonnée des tools réellement appelés via RPC pendant le run.
    # Utilisé par le completion_guard (§4.4) pour la détection d'unbacked
    # completion claims.
    tools_dispatched: list[str] = field(default_factory=list)
    # True si timeout, OOM, ou stdout > max — le LLM doit le savoir pour
    # ne pas mentir sur la complétude du travail.
    truncated: bool = False
    truncation_reason: str = ""


# ──────────────────────────────────────────────────────────────────────
# Façade publique
# ──────────────────────────────────────────────────────────────────────


# Type alias for clarity: a callable that, given (tool_name, args), runs
# the underlying tool and returns either the result or a coroutine.
ToolDispatcher = Callable[[str, dict[str, Any]], Any]


class OrchestrateRunner:
    """Façade publique du sandbox orchestrate.

    Usage typique (depuis ``orchestrate_tool.py``) :

        runner = OrchestrateRunner(
            user_id=user_id,
            tool_dispatcher=build_default_dispatcher(user_id),
        )
        result = await runner.run(code=llm_generated_python)
        return result.stdout, result.tools_dispatched

    Cycle de vie d'un run :
        1. Création d'un ``tmpdir`` éphémère.
        2. Génération de ``ely_tools.py`` (stub) via ``orchestrate_stubs``.
        3. Écriture du script LLM dans ``{tmpdir}/script.py``.
        4. Démarrage du RPC server UDS (``orchestrate_rpc``).
        5. ``subprocess.Popen`` du script avec env scrubbée + PYTHONPATH
           = tmpdir uniquement.
        6. Attente de la fin (timeout 300s) ou kill du process group.
        7. Lecture stdout / stderr + récupération de la liste des tools
           dispatchés.
        8. Cleanup du tmpdir et du socket UDS.
    """

    def __init__(
        self,
        *,
        user_id: str,
        tool_dispatcher: ToolDispatcher | None = None,
        limits: OrchestrateLimits | None = None,
        allowed_tools: frozenset[str] | None = None,
    ) -> None:
        if not user_id:
            raise ValueError("OrchestrateRunner requires a non-empty user_id")
        self.user_id = user_id
        self.limits = limits or OrchestrateLimits()
        self.allowed_tools = allowed_tools or SANDBOX_ALLOWED_TOOLS_V1
        # If the caller didn't pass a dispatcher, build the default one
        # lazily on the first run() — that avoids paying the registry
        # bootstrap cost in tests that only exercise input validation.
        self._tool_dispatcher: ToolDispatcher | None = tool_dispatcher
        self._tools_dispatched: list[str] = []

    async def run(self, code: str) -> OrchestrateResult:
        """Exécute ``code`` dans le sandbox et retourne le résultat.

        Args:
            code: script Python complet, fourni par le LLM principal.
                Doit utiliser uniquement les noms de fonctions du module
                ``ely_tools`` (stub auto-généré depuis
                ``SANDBOX_ALLOWED_TOOLS_V1``).

        Returns:
            ``OrchestrateResult`` avec stdout, stderr, exit_code,
            durée, et la liste des tools effectivement dispatchés.

        Raises:
            ValueError: si ``code`` est vide.
        """
        if not code or not code.strip():
            raise ValueError("orchestrate.run() requires non-empty code")

        start_time = time.monotonic()
        tmpdir = Path(tempfile.mkdtemp(prefix="ely_orchestrate_"))

        dispatcher = self._tool_dispatcher or _build_default_dispatcher(self.user_id)

        rpc_server = OrchestrateRPCServer(
            user_id=self.user_id,
            allowed_tools=self.allowed_tools,
            max_tool_calls=self.limits.max_tool_calls,
            tool_dispatcher=dispatcher,
        )

        try:
            # 1. Filesystem layout
            home_dir = tmpdir / "home"
            home_dir.mkdir()
            script_path = tmpdir / "script.py"
            ely_tools_path = tmpdir / "ely_tools.py"
            script_path.write_text(code, encoding="utf-8")

            # 2. Start RPC server (creates the UDS socket)
            socket_path = rpc_server.start()

            # 3. Generate ely_tools.py stubs
            generate_stubs(
                allowed_tools=self.allowed_tools,
                socket_path=socket_path,
                target_path=ely_tools_path,
            )

            # 4. Build the scrubbed environment for the child
            child_env = _build_scrubbed_env(
                socket_path=socket_path,
                tmpdir=tmpdir,
                home_dir=home_dir,
            )

            # 5. Spawn and wait
            result = await self._spawn_and_wait(
                script_path=script_path,
                tmpdir=tmpdir,
                child_env=child_env,
                start_time=start_time,
            )

            # 6. Attach the tools_dispatched list from the RPC server
            self._tools_dispatched = rpc_server.tools_dispatched
            result.tools_dispatched = self._tools_dispatched
            return result
        finally:
            try:
                rpc_server.stop()
            except Exception:  # noqa: BLE001
                logger.exception("orchestrate: failed to stop RPC server cleanly")
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                logger.exception("orchestrate: failed to cleanup tmpdir %s", tmpdir)

    def last_run_tools_dispatched(self) -> list[str]:
        """Liste des tools dispatchés pendant le dernier ``run()``.

        Utilisé par le wiring ``completion_guard`` (§4.4) côté nœud
        agent : le retour vers ``detect_unbacked_completion_claim`` se
        fait via cette source supplémentaire.
        """
        return list(self._tools_dispatched)

    # ── Internals ─────────────────────────────────────────────────────

    async def _spawn_and_wait(
        self,
        *,
        script_path: Path,
        tmpdir: Path,
        child_env: dict[str, str],
        start_time: float,
    ) -> OrchestrateResult:
        """Spawn the subprocess, wait with timeout, collect stdout/stderr.

        Implements head+tail stdout truncation à la Hermes : the first
        ``head_bytes`` are kept verbatim, then a rolling tail buffer of
        the last ``tail_bytes`` bytes is maintained. On overflow, the
        middle is replaced by a clear ``[truncated N bytes]`` marker.
        Stderr is head-only (errors typically appear early).
        """
        head_bytes = int(self.limits.max_stdout_bytes * self.limits.stdout_head_ratio)
        tail_bytes = self.limits.max_stdout_bytes - head_bytes

        # ``preexec_fn=os.setsid`` is POSIX-only. On Windows the sandbox
        # is unsupported anyway (UDS doesn't exist); we keep this guard
        # for explicitness.
        preexec = os.setsid if os.name != "nt" else None

        # ``-S`` disables ``site.py`` so the venv's editable-install .pth
        # files don't add ``backend/`` to sys.path. Without this, a script
        # running in our venv can ``import app.services.vault_service``
        # despite the PYTHONPATH whitelist. With -S, the child only sees
        # stdlib + cwd + our explicit PYTHONPATH (= tmpdir).
        proc = await asyncio.to_thread(
            subprocess.Popen,
            [sys.executable, "-S", str(script_path)],
            cwd=str(tmpdir),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            preexec_fn=preexec,
        )

        loop = asyncio.get_event_loop()
        timeout_at = start_time + self.limits.timeout_seconds
        truncated = False
        truncation_reason = ""

        # Background drainers — without them, a script that writes more
        # than the pipe buffer (~64 KB) blocks forever.
        stdout_head_chunks: list[bytes] = []
        stdout_tail_buf: deque[bytes] = deque()
        stdout_total = [0]
        stderr_chunks: list[bytes] = []

        def _drain_head_tail(pipe, head_chunks, tail_buf, head_limit, tail_limit, total_ref):
            head_collected = 0
            tail_collected = 0
            try:
                while True:
                    data = pipe.read(4096)
                    if not data:
                        break
                    total_ref[0] += len(data)
                    if head_collected < head_limit:
                        take = min(head_limit - head_collected, len(data))
                        head_chunks.append(data[:take])
                        head_collected += take
                        if take < len(data):
                            remaining = data[take:]
                            tail_buf.append(remaining)
                            tail_collected += len(remaining)
                    else:
                        tail_buf.append(data)
                        tail_collected += len(data)
                    # Roll the tail buffer to keep only the last tail_limit bytes
                    while tail_collected > tail_limit and tail_buf:
                        oldest = tail_buf[0]
                        excess = tail_collected - tail_limit
                        if len(oldest) <= excess:
                            tail_buf.popleft()
                            tail_collected -= len(oldest)
                        else:
                            tail_buf[0] = oldest[excess:]
                            tail_collected -= excess
            except (ValueError, OSError) as exc:
                logger.debug("orchestrate: stdout drain error: %s", exc)

        def _drain_head_only(pipe, chunks, max_bytes):
            total = 0
            try:
                while True:
                    data = pipe.read(4096)
                    if not data:
                        break
                    if total < max_bytes:
                        chunks.append(data[:max_bytes - total])
                    total += len(data)
            except (ValueError, OSError) as exc:
                logger.debug("orchestrate: stderr drain error: %s", exc)

        stdout_task = loop.run_in_executor(
            None, _drain_head_tail,
            proc.stdout, stdout_head_chunks, stdout_tail_buf,
            head_bytes, tail_bytes, stdout_total,
        )
        stderr_task = loop.run_in_executor(
            None, _drain_head_only,
            proc.stderr, stderr_chunks, self.limits.max_stderr_bytes,
        )

        # Poll for exit with periodic timeout check
        while True:
            if proc.poll() is not None:
                break
            if time.monotonic() >= timeout_at:
                truncated = True
                truncation_reason = (
                    f"timeout after {self.limits.timeout_seconds}s — "
                    "process group killed"
                )
                _kill_process_group(proc, grace=self.limits.sigkill_grace_seconds)
                break
            await asyncio.sleep(0.05)

        # Make sure the drains have completed (process is now dead or
        # has exited normally, so its pipes will EOF shortly).
        await stdout_task
        await stderr_task

        exit_code = proc.returncode if proc.returncode is not None else -1

        # Assemble stdout
        stdout_head = b"".join(stdout_head_chunks).decode("utf-8", errors="replace")
        stdout_tail = b"".join(stdout_tail_buf).decode("utf-8", errors="replace")
        if stdout_total[0] > self.limits.max_stdout_bytes and stdout_tail:
            omitted = stdout_total[0] - len(stdout_head.encode("utf-8")) - len(stdout_tail.encode("utf-8"))
            stdout_text = (
                f"{stdout_head}\n...[truncated {max(omitted, 0)} bytes]...\n{stdout_tail}"
            )
            if not truncated:
                truncated = True
                truncation_reason = (
                    f"stdout truncated — exceeded {self.limits.max_stdout_bytes} "
                    "bytes, kept head+tail only"
                )
        elif stdout_tail:
            # No overflow but data spilled into the tail buffer because
            # head was already full — concatenate cleanly.
            stdout_text = stdout_head + stdout_tail
        else:
            stdout_text = stdout_head

        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        return OrchestrateResult(
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            duration_seconds=time.monotonic() - start_time,
            tools_dispatched=[],
            truncated=truncated,
            truncation_reason=truncation_reason,
        )


# ──────────────────────────────────────────────────────────────────────
# Env scrubbing helper
# ──────────────────────────────────────────────────────────────────────


def _build_scrubbed_env(
    *,
    socket_path: Path,
    tmpdir: Path,
    home_dir: Path,
) -> dict[str, str]:
    """Build the env dict to pass to the child subprocess.

    Rules (in order):
        1. Any var whose name (uppercased) contains a secret substring
           (``KEY``, ``TOKEN``, …) is **blocked** — even if its prefix
           matches the whitelist. This is the defence in depth: an
           operator who adds a new ``ELY_API_KEY`` var doesn't have to
           remember to update the sandbox config.
        2. Any var whose name starts with a whitelisted prefix is
           **kept**.
        3. Mandatory overrides:
           - ``ELY_RPC_SOCKET = socket_path``
           - ``HOME = tmpdir/home/`` (isolation from the parent's ``~``)
           - ``PYTHONPATH = tmpdir`` (NO inherit — only the staging dir
             is importable, preventing ``from app... import secret``)
           - ``PYTHONDONTWRITEBYTECODE = 1`` (no .pyc litter)
    """
    child_env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(s in upper for s in _SECRET_SUBSTRINGS):
            continue
        if any(key.startswith(p) for p in _SAFE_ENV_PREFIXES):
            child_env[key] = value

    # Hard overrides — must happen AFTER the loop so they win over any
    # whitelist-derived inheritance (e.g. parent's HOME).
    child_env["ELY_RPC_SOCKET"] = str(socket_path)
    child_env["HOME"] = str(home_dir)
    child_env["PYTHONPATH"] = str(tmpdir)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    return child_env


# ──────────────────────────────────────────────────────────────────────
# Kill helper — process group escalation
# ──────────────────────────────────────────────────────────────────────


def _kill_process_group(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """SIGTERM the whole process group; if still alive after ``grace``, SIGKILL.

    Pattern lifted from Hermes (``_kill_process_group``). Required to
    handle scripts that spawn threads or sub-children — terminating the
    parent Popen alone may leave orphans behind.
    """
    if os.name == "nt":  # pragma: no cover — sandbox unsupported on Windows
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            logger.exception("orchestrate: failed to terminate child on Windows")
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as exc:
        logger.debug("orchestrate: SIGTERM killpg failed (%s) — falling back to proc.kill", exc)
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            logger.exception("orchestrate: fallback proc.kill also failed")
        return

    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError) as exc:
            logger.debug("orchestrate: SIGKILL killpg failed: %s", exc)
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                logger.exception("orchestrate: final proc.kill also failed")


# ──────────────────────────────────────────────────────────────────────
# Default tool_dispatcher — registry-backed
# ──────────────────────────────────────────────────────────────────────


def _build_default_dispatcher(user_id: str) -> ToolDispatcher:
    """Build a dispatcher that routes RPC calls to the real registry tools.

    Each call:
        1. Looks up the @tool by name in the global skill registry.
        2. Adds ``user_id`` to the args (the only injection we handle in
           V1 — see roadmap §4.4 for the multi-injected case).
        3. Calls ``tool.ainvoke({...})`` which returns a coroutine — the
           RPC server's thread event loop awaits it via
           ``run_until_complete``.

    Limit V1: tools that need other ``InjectedToolArg`` parameters (e.g.
    Gmail's ``user_google_credentials_json`` / ``account``) will FAIL
    when invoked through this dispatcher — those tools must be wired
    through the agent's full injection chain or excluded from the V1
    allow-list. Tracked for V2.
    """
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    tools_by_name = {t.name: t for t in get_skill_registry().all_tools}

    def dispatch(tool_name: str, args: dict[str, Any]) -> Any:
        tool = tools_by_name.get(tool_name)
        if tool is None:
            raise LookupError(f"tool {tool_name!r} not found in skill registry")
        full_args = {**args, "user_id": user_id}
        return tool.ainvoke(full_args)

    return dispatch


# ──────────────────────────────────────────────────────────────────────
# Parsing helper — reverse of the meta header produced by orchestrate_tool
# ──────────────────────────────────────────────────────────────────────


def parse_dispatched_from_result(tool_output: str) -> list[str]:
    """Extract the list of dispatched tool names from an ``orchestrate`` result.

    The ``orchestrate`` tool prepends every result with a meta header of
    the form ``[orchestrate tools=A,B,C (count=N) | …]`` (or
    ``[orchestrate no tools called]`` when no RPC fired). This helper
    parses that header so the chat router can union the dispatched tools
    into ``tools_called`` before the completion_guard runs (§4.4).

    Args:
        tool_output: the string returned by the ``orchestrate`` @tool.

    Returns:
        Ordered list of tool names (with duplicates preserved). Returns
        an empty list if the header is malformed or no tools were
        dispatched — never raises.
    """
    if not tool_output or not isinstance(tool_output, str):
        return []
    # Header must be the very first line, between ``[orchestrate`` and ``]``.
    first_newline = tool_output.find("\n")
    header = tool_output[:first_newline] if first_newline != -1 else tool_output
    if not header.startswith("[orchestrate"):
        return []
    # Locate "tools=" inside the header.
    marker = "tools="
    idx = header.find(marker)
    if idx == -1:
        return []
    rest = header[idx + len(marker):]
    # The tool list ends at whitespace, ``|``, or ``]``.
    for terminator in (" ", "|", "]"):
        cut = rest.find(terminator)
        if cut != -1:
            rest = rest[:cut]
    return [name for name in rest.split(",") if name]


__all__ = [
    "SANDBOX_ALLOWED_TOOLS_V1",
    "OrchestrateLimits",
    "OrchestrateResult",
    "OrchestrateRunner",
    "ToolDispatcher",
    "parse_dispatched_from_result",
]
