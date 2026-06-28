# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/python_tool.py
# @brief      Python sandbox tool — exécute du code Python dans un sous-processus isolé
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Python sandbox tool — exécute du code Python dans un sous-processus isolé.

Sécurité (réelle, pas juste commentée) :
- Analyse AST avant exécution : bloque socket, subprocess, ctypes et imports dangereux
- Environnement minimal passé au sous-processus : AUCUNE variable d'env sensible (clés API…)
- preexec_fn applique les limites resource (CPU, mémoire, fichiers, processus) dans le child
- Répertoire de travail temporaire dédié (nettoyé après)
- Timeout 30 secondes côté asyncio + CPU hard limit via RLIMIT_CPU dans le child
- stdout + stderr capturés, limités à 8 000 caractères
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import textwrap
from pathlib import Path

from langchain_core.tools import tool

_TIMEOUT = 30          # secondes (asyncio)
_MAX_OUTPUT = 8_000    # caractères

# ── Modules interdits dans le sandbox ────────────────────────────────────────
# Inclut les accès réseau, exécution de processus et accès bas niveau.
_BLOCKED_MODULES: frozenset[str] = frozenset({
    "socket", "ssl", "http", "urllib", "urllib2", "urllib3",
    "httpx", "requests", "aiohttp", "httplib",
    "subprocess", "multiprocessing", "concurrent",
    "ctypes", "cffi", "pty", "tty", "termios", "fcntl",
    "mmap", "msvcrt", "winreg", "winsound",
    "importlib",   # empêche import dynamique de contournement
    "pkg_resources", "setuptools", "pip",
    "sysconfig", "distutils",
    "code", "codeop",   # REPL interactif
    "antigravity",      # fun mais inutile
    "os", "sys", "shutil", "pathlib", "glob",  # filesystem / system access
})

# Builtins dangereux qui ne doivent pas être appelés dans le sandbox
_BLOCKED_BUILTINS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "open", "__import__",
})

# ── Analyse statique du code par AST ─────────────────────────────────────────

def _ast_check(code: str) -> str | None:
    """Retourne un message d'erreur si le code contient des constructions
    dangereuses, sinon None.  Utilise l'AST Python pour éviter les faux positifs
    de regex."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Syntaxe invalide : {exc}"

    for node in ast.walk(tree):
        # import X  /  import X.Y
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _BLOCKED_MODULES:
                    return f"Module interdit dans le sandbox : '{alias.name}'"

        # from X import Y
        if isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in _BLOCKED_MODULES:
                return f"Module interdit dans le sandbox : '{node.module}'"

        # __import__("socket")  /  importlib.import_module("socket")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                if node.args and isinstance(node.args[0], ast.Constant):
                    mod = str(node.args[0].value).split(".")[0]
                    if mod in _BLOCKED_MODULES:
                        return f"Import dynamique interdit : '{node.args[0].value}'"

            # Bloc les appels directs à eval(), exec(), compile(), open()
            if isinstance(func, ast.Name) and func.id in _BLOCKED_BUILTINS:
                return f"Builtin interdit dans le sandbox : '{func.id}()'"

    return None


# ── Limites resource appliquées dans le child process ────────────────────────

def _apply_sandbox_limits() -> None:
    """Appelé dans le processus enfant juste avant exec (preexec_fn).

    Applique des limites système hard qui empêchent :
    - L'épuisement CPU (RLIMIT_CPU)
    - La consommation excessive de mémoire (RLIMIT_AS)
    - La création de fichiers géants (RLIMIT_FSIZE)
    - L'ouverture de trop de descripteurs (RLIMIT_NOFILE)
    - Le fork excessif (RLIMIT_NPROC)
    """
    try:
        import resource as _resource
        _resource.setrlimit(_resource.RLIMIT_CPU,   (25, 25))
        _resource.setrlimit(_resource.RLIMIT_FSIZE,  (100 * 1024 * 1024, 100 * 1024 * 1024))
        _resource.setrlimit(_resource.RLIMIT_NOFILE, (32, 32))
        try:
            _resource.setrlimit(_resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        except (ValueError, AttributeError):
            pass
        try:
            _resource.setrlimit(_resource.RLIMIT_NPROC, (8, 8))
        except (ValueError, AttributeError):
            pass
    except Exception:
        pass  # Non-Linux (Windows) : on ignore silencieusement


# ── Environnement minimal pour le sous-processus ─────────────────────────────

def _sandbox_env(workdir: str) -> dict[str, str]:
    """Construit un environnement minimaliste pour le sous-processus.

    AUCUNE variable sensible (clés API, tokens, secrets) n'est transmise.
    Le répertoire HOME est forcé sur le workdir pour éviter que le code
    n'accède aux fichiers de config de l'utilisateur système (~/.ssh, ~/.aws…).
    """
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": workdir,          # pas de ~/.ssh, ~/.aws, etc.
        "TMPDIR": workdir,
        "TEMP": workdir,
        "TMP": workdir,
        "MPLBACKEND": "Agg",      # matplotlib non-interactif
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }


@tool
async def python_execute(code: str) -> str:
    """Execute Python code and return the output.

    Use this tool for:
    - Mathematical calculations and statistics
    - Data processing and analysis
    - String manipulation
    - Generating charts (saved as image, path returned)
    - Any task that benefits from running actual code

    The execution environment has: Python standard library (except network/system
    modules) + numpy, pandas, matplotlib (if installed).
    Network access and system calls are blocked.

    Args:
        code: Valid Python code to execute. Use print() to output results.
    """
    # ── 1. Analyse statique avant toute exécution ─────────────────────────
    error = _ast_check(code)
    if error:
        return f"Code refusé par le sandbox : {error}"

    # ── 2. Exécution dans un répertoire temporaire isolé ──────────────────
    with tempfile.TemporaryDirectory(prefix="ely_sandbox_") as workdir:
        script_path = os.path.join(workdir, "script.py")

        # Préambule : redirige matplotlib et fixe le cwd
        # os et sys sont importés sous alias privé puis supprimés du namespace
        preamble = textwrap.dedent(f"""\
            import os as _os, sys as _sys
            _os.environ.setdefault("MPLBACKEND", "Agg")
            _WORKDIR = {workdir!r}
            _os.chdir(_WORKDIR)
            del _os, _sys
        """)

        Path(script_path).write_text(preamble + "\n" + code, encoding="utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=_sandbox_env(workdir),         # env sans secrets
                preexec_fn=_apply_sandbox_limits,  # resource limits dans le child
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return f"Timeout : l'exécution a dépassé {_TIMEOUT} secondes."

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            # Chercher des fichiers image générés (matplotlib savefig)
            try:
                images = [
                    f for f in os.listdir(workdir)
                    if f.endswith((".png", ".jpg"))  # pas de .svg (XSS possible)
                ]
            except OSError:
                images = []

            parts: list[str] = []
            if proc.returncode == 0:
                if out:
                    parts.append(out[:_MAX_OUTPUT])
                    if len(out) > _MAX_OUTPUT:
                        parts.append(f"[… sortie tronquée à {_MAX_OUTPUT} caractères]")
                if not out:
                    parts.append("Code exécuté avec succès (aucune sortie).")
                if images:
                    parts.append(f"Fichier(s) généré(s) dans le sandbox : {', '.join(images)}")
            else:
                parts.append(f"Erreur (code {proc.returncode}) :")
                if err:
                    err_lines = err.splitlines()
                    parts.append("\n".join(err_lines[-20:]))
                elif out:
                    parts.append(out[:_MAX_OUTPUT])

            return "\n".join(parts)

        except Exception as exc:
            return f"Impossible d'exécuter le code : {exc}"
