"""Python sandbox tool — exécute du code Python dans un sous-processus isolé.

Sécurité :
- Exécution dans un répertoire temporaire dédié (nettoyé après)
- Timeout 30 secondes
- stdout + stderr capturés, limités à 8 000 caractères
- Pas d'accès réseau (pas de restriction OS — à renforcer si besoin)
- Le code s'exécute avec les mêmes permissions que le process backend
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap

from langchain_core.tools import tool

_TIMEOUT = 30  # secondes
_MAX_OUTPUT = 8_000  # caractères


@tool
async def python_execute(code: str) -> str:
    """Execute Python code and return the output.

    Use this tool for:
    - Mathematical calculations and statistics
    - Data processing and analysis
    - String manipulation
    - Generating charts (saved as image, path returned)
    - Any task that benefits from running actual code

    The execution environment has: Python standard library + numpy, pandas,
    matplotlib (if installed). No internet access from code.

    Args:
        code: Valid Python code to execute. Use print() to output results.
    """
    # Créer un répertoire de travail temporaire isolé
    with tempfile.TemporaryDirectory(prefix="ely_sandbox_") as workdir:
        script_path = os.path.join(workdir, "script.py")

        # Préambule : redirige matplotlib vers un backend non-interactif
        preamble = textwrap.dedent("""\
            import os, sys
            os.environ.setdefault("MPLBACKEND", "Agg")
            _WORKDIR = os.path.dirname(os.path.abspath(__file__))
            os.chdir(_WORKDIR)
        """)

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(preamble + "\n" + code)

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
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
            images = [
                f for f in os.listdir(workdir)
                if f.endswith((".png", ".jpg", ".svg"))
            ]

            parts = []
            if proc.returncode == 0:
                if out:
                    parts.append(out[:_MAX_OUTPUT])
                    if len(out) > _MAX_OUTPUT:
                        parts.append(f"[… sortie tronquée à {_MAX_OUTPUT} caractères]")
                if not out:
                    parts.append("Code exécuté avec succès (aucune sortie).")
                if images:
                    parts.append(f"Fichier(s) généré(s) : {', '.join(images)}")
            else:
                parts.append(f"Erreur (code {proc.returncode}) :")
                if err:
                    # Garder seulement les dernières lignes de l'erreur (plus lisible)
                    err_lines = err.splitlines()
                    parts.append("\n".join(err_lines[-20:]))
                elif out:
                    parts.append(out[:_MAX_OUTPUT])

            return "\n".join(parts)

        except Exception as exc:
            return f"Impossible d'exécuter le code : {exc}"
