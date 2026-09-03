# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/env_filter.py
# @brief      Reusable env-var filter (whitelist prefixes + blocklist substrings)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Durcissement partagé des sous-processus : filtre d'environnement + kill.

Deux consommateurs ont besoin de la même règle de défense en profondeur
quand ils lancent un processus enfant :
  1. Le bac à sable de validation des compétences (``learning.smoke_sandbox``)
     exécute un script Python généré, dans un sous-processus à l'environnement
     réduit.
  2. Le client MCP (``mcp_client``) lance des serveurs d'outils arbitraires
     via ``uv tool run …``, ``npx …``, etc.

⚠️ Ces trois symboles — ``SAFE_ENV_PREFIXES``, ``SECRET_SUBSTRINGS`` et
``kill_process_group`` — vivaient dans ``orchestrate_runner``, démantelé le
29/07 (ménage lot 5). Ils n'avaient rien d'« orchestrate » : c'est du
durcissement de sous-processus, le métier de ce module. Les déplacer était la
condition pour supprimer le bac à sable sans casser la validation des
compétences apprises.

Both must avoid leaking ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` /
``GITHUB_TOKEN`` / database credentials into the child's environment.
This module hosts the small pure filter so both consumers share one
audited implementation.

Rules
-----
1. If a var's name (uppercased) contains any **secret substring**
   (``KEY``, ``TOKEN``, …) it is **dropped** — even if its prefix
   matches the whitelist. Defense in depth: a future
   ``ELY_BACKUP_KEY`` is blocked the moment it's defined, without
   touching this file.
2. Otherwise, the var is **kept** if its name starts with any
   whitelisted prefix.
3. Everything else is dropped.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess

logger = logging.getLogger(__name__)

# Préfixes de variables conservés pour un enfant. Tout le reste est coupé.
SAFE_ENV_PREFIXES: tuple[str, ...] = (
    "PATH", "HOME", "USER", "LANG", "LC_", "TERM",
    "TMPDIR", "TMP", "TEMP", "SHELL", "LOGNAME",
    "XDG_", "PYTHONDONTWRITEBYTECODE", "TZ",
    "ELY_",
)

# Sous-chaînes qui font tomber une variable même si son préfixe est autorisé.
SECRET_SUBSTRINGS: tuple[str, ...] = (
    "KEY", "TOKEN", "SECRET", "PASSWORD",
    "CREDENTIAL", "PASSWD", "AUTH",
)


def kill_process_group(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """SIGTERM tout le groupe de processus ; SIGKILL après ``grace``.

    Nécessaire pour les scripts qui lancent des fils ou des petits-enfants :
    terminer le seul ``Popen`` parent laisserait des orphelins derrière lui.
    """
    if os.name == "nt":  # pragma: no cover — bac à sable non supporté sur Windows
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            logger.exception("sandbox: échec de terminate() sur Windows")
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as exc:
        logger.debug("sandbox: killpg SIGTERM échoué (%s) — repli sur proc.kill", exc)
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            logger.exception("sandbox: le repli proc.kill a échoué aussi")
        return

    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError) as exc:
            logger.debug("sandbox: killpg SIGKILL échoué : %s", exc)
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                logger.exception("sandbox: le proc.kill final a échoué aussi")


def filter_safe_env(
    *,
    safe_prefixes: tuple[str, ...],
    secret_substrings: tuple[str, ...],
    source: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the subset of ``source`` whose keys match the rules.

    Parameters
    ----------
    safe_prefixes
        Tuple of allowed name prefixes (``"PATH"``, ``"ELY_"``, …).
    secret_substrings
        Tuple of forbidden substrings (matched case-insensitively against
        the variable name). Any match drops the variable, even if its
        prefix is whitelisted.
    source
        Mapping to filter. Defaults to ``os.environ``.

    Returns
    -------
    dict[str, str]
        Fresh dict suitable to pass as ``env=`` to ``subprocess.Popen`` /
        ``StdioServerParameters``.
    """
    if source is None:
        source = dict(os.environ)
    out: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if any(s in upper for s in secret_substrings):
            continue
        if any(key.startswith(p) for p in safe_prefixes):
            out[key] = value
    return out
