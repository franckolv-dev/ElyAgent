# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
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
