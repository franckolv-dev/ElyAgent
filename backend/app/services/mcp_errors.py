# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_errors.py
# @brief      Taxonomie d'erreurs MCP — codes stables, sans secret.
# @license    Elastic License 2.0
# =============================================================================
"""Codes d'erreur MCP stables (cf. cadrage §15.1).

Le modèle et l'UI reçoivent une forme NORMALISÉE ; le détail (et tout secret)
reste dans les logs. ``last_error_code`` sur ``mcp_servers`` stocke l'une de
ces valeurs.
"""
from __future__ import annotations

from enum import Enum


class MCPErrorCode(str, Enum):
    CONFIG_INVALID = "MCP_CONFIG_INVALID"
    PERMISSION_DENIED = "MCP_PERMISSION_DENIED"
    AUTH_REQUIRED = "MCP_AUTH_REQUIRED"
    AUTH_EXPIRED = "MCP_AUTH_EXPIRED"
    CONNECT_FAILED = "MCP_CONNECT_FAILED"
    PROTOCOL_ERROR = "MCP_PROTOCOL_ERROR"
    TOOL_NOT_FOUND = "MCP_TOOL_NOT_FOUND"
    ARGUMENT_INVALID = "MCP_ARGUMENT_INVALID"
    TOOL_ERROR = "MCP_TOOL_ERROR"
    TIMEOUT = "MCP_TIMEOUT"
    RESULT_INVALID = "MCP_RESULT_INVALID"
    RESULT_TOO_LARGE = "MCP_RESULT_TOO_LARGE"
    SERVER_QUARANTINED = "MCP_SERVER_QUARANTINED"
    EGRESS_BLOCKED = "MCP_EGRESS_BLOCKED"


# Codes pour lesquels un retry automatique est acceptable (lecture idempotente
# uniquement — jamais une mutation). Cf. cadrage §15.2.
RETRYABLE_CODES = frozenset({
    MCPErrorCode.CONNECT_FAILED.value,
    MCPErrorCode.TIMEOUT.value,
})


class MCPConnectError(Exception):
    """Échec de connexion/handshake. Porte un code stable."""

    def __init__(self, message: str, *, code: str = MCPErrorCode.CONNECT_FAILED.value) -> None:
        super().__init__(message)
        self.code = code
