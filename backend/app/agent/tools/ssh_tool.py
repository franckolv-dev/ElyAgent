from langchain_core.tools import tool

from app.services.ssh_manager import execute_ssh_command, is_command_allowed


@tool
def ssh_execute(host: str, command: str) -> str:
    """Execute a command on a remote host via SSH.
    The command must be in the host's whitelist of allowed commands.

    Args:
        host: The name of the host as defined in hosts.yaml
        command: The shell command to execute
    """
    if not is_command_allowed(host, command):
        return f"ERROR: Command '{command}' is not allowed on host '{host}'. Check the allowed commands list."

    try:
        exit_code, stdout, stderr = execute_ssh_command(host, command)
        result = f"Exit code: {exit_code}\n"
        if stdout:
            result += f"Output:\n{stdout}\n"
        if stderr:
            result += f"Errors:\n{stderr}\n"
        return result
    except Exception as e:
        return f"SSH Error: {str(e)}"
