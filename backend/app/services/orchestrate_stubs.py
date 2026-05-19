# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/orchestrate_stubs.py
# @brief      Stub generator pour le module ``ely_tools.py`` du sandbox.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    0.1.0-skeleton
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Stub generator pour ``ely_tools.py`` — squelette Jalon 1.

À chaque run, on génèrera un fichier ``ely_tools.py`` éphémère dans le
``tmpdir`` du sandbox. Ce fichier contiendra :

1. Une fonction stub par tool de ``SANDBOX_ALLOWED_TOOLS_V1``, avec la
   même signature que le @tool réel **moins** les paramètres
   ``Annotated[..., InjectedToolArg]``.
2. Un helper ``_rpc`` qui sérialise les calls en length-prefixed JSON
   et les envoie au serveur UDS via ``ELY_RPC_SOCKET``.
3. Trois helpers QoL : ``json_parse``, ``shell_quote``, ``retry``.

Status : SKELETON
=================
``generate_stubs`` lève ``NotImplementedError``. L'implémentation arrive
au Jalon 3 avec :
    - introspection des @tool via ``inspect.signature`` +
      ``typing.get_type_hints(include_extras=True)`` (pour décoder les
      annotations stringifiées par ``from __future__ import annotations``)
    - filtrage des ``Annotated[..., InjectedToolArg]``
    - rendu textuel du module self-contained (stdlib only).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
        ValueError: si l'allow-list est vide.
        FileNotFoundError: si le parent de ``socket_path`` n'existe pas.
        NotImplementedError: tant que Jalon 3 n'est pas terminé.
    """
    if not allowed_tools:
        raise ValueError("generate_stubs requires a non-empty allow-list")
    if not socket_path.parent.exists():
        raise FileNotFoundError(
            f"Socket parent dir does not exist: {socket_path.parent}"
        )
    raise NotImplementedError(
        "generate_stubs() is a skeleton — Jalon 3 pending"
    )


__all__ = ["generate_stubs"]
