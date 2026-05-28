# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/ssh_tool.py
# @brief      Ssh Tool module
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from langchain_core.tools import tool

from app.services.ssh_manager import async_execute_ssh_command, is_command_allowed


@tool
async def ssh_execute(host: str, command: str) -> str:
    """Execute a command on a remote host via SSH.
    The command must be in the host's whitelist of allowed commands.

    Args:
        host: The name of the host as defined in hosts.yaml
        command: The shell command to execute
    """
    if not is_command_allowed(host, command):
        return f"ERROR: Command '{command}' is not allowed on host '{host}'. Check the allowed commands list."

    try:
        exit_code, stdout, stderr = await async_execute_ssh_command(host, command)
        result = f"Exit code: {exit_code}\n"
        if stdout:
            result += f"Output:\n{stdout}\n"
        if stderr:
            result += f"Errors:\n{stderr}\n"
        return result
    except Exception as e:
        return f"SSH Error: {str(e)}"
