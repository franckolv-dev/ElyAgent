# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/env_filter.py
# @brief      Reusable env-var filter (whitelist prefixes + blocklist substrings)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Pure env-filtering helper, shared by orchestrate sandbox and MCP stdio.

Two consumers need the same defense-in-depth rule when they spawn a
child process:
  1. The orchestrate sandbox (``orchestrate_runner``) runs a generated
     Python script in a subprocess with a stripped env.
  2. The MCP client (``mcp_client``) launches arbitrary tool servers
     via ``uv tool run …``, ``npx …``, etc.

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

import os


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
