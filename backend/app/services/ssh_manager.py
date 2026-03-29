import asyncio
import fnmatch
import re
from pathlib import Path

import paramiko
import yaml
import structlog

logger = structlog.get_logger()

_host_config: dict | None = None

# Shell metacharacters that indicate potential injection attempts
_SHELL_META = re.compile(r'[;&|`$<>\\\'\"()\n\r]')


def load_host_config() -> dict:
    global _host_config
    if _host_config is not None:
        return _host_config

    # Support both local dev (relative to project root) and Docker (/config volume)
    candidates = [
        Path("/config/hosts.yaml"),
        Path(__file__).parent.parent.parent.parent / "config" / "hosts.yaml",
    ]
    for config_path in candidates:
        if config_path.exists():
            with open(config_path) as f:
                _host_config = yaml.safe_load(f) or {}
            return _host_config

    _host_config = {}
    return _host_config


def is_command_allowed(host_name: str, command: str) -> bool:
    # MED-4: Reject any command containing shell metacharacters before pattern matching
    if _SHELL_META.search(command):
        logger.warning(
            "shell_metachar_blocked", host=host_name, command=command[:200]
        )
        return False

    config = load_host_config()
    hosts = config.get("hosts") or {}
    host = hosts.get(host_name)
    if not host:
        return False

    # Check blocked patterns first
    blocked = host.get("blocked_patterns", [])
    for pattern in blocked:
        if pattern in command:
            logger.warning("blocked_command", host=host_name, command=command, pattern=pattern)
            return False

    # Check allowed commands
    allowed = host.get("allowed_commands", [])
    for pattern in allowed:
        if fnmatch.fnmatch(command, pattern):
            return True

    return False


def execute_ssh_command(host_name: str, command: str) -> tuple[int, str, str]:
    config = load_host_config()
    hosts = config.get("hosts") or {}
    host = hosts.get(host_name)
    if not host:
        raise ValueError(f"Unknown host: {host_name}")

    if not is_command_allowed(host_name, command):
        raise PermissionError(f"Command not allowed on {host_name}: {command}")

    client = paramiko.SSHClient()
    # HIGH-2: Use WarningPolicy instead of AutoAddPolicy.
    # WarningPolicy logs unknown host keys but does not silently accept them the
    # way AutoAddPolicy does, making MITM attacks visible in server logs.
    # TODO: migrate to RejectPolicy once host_key fingerprints are stored in DB
    # and loaded here via client.get_host_keys().add(...).
    client.set_missing_host_key_policy(paramiko.WarningPolicy())

    try:
        connect_kwargs = {
            "hostname": host["hostname"],
            "port": host.get("port", 22),
            "username": host["username"],
        }
        key_file = host.get("key_file")
        if key_file:
            connect_kwargs["key_filename"] = str(Path(key_file).expanduser())

        client.connect(**connect_kwargs)
        stdin, stdout, stderr = client.exec_command(command, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")

        logger.info("ssh_command_executed", host=host_name, command=command, exit_code=exit_code)
        return exit_code, out, err
    finally:
        client.close()


async def async_execute_ssh_command(host_name: str, command: str) -> tuple[int, str, str]:
    """Async wrapper: runs the blocking SSH call in a thread pool so the
    FastAPI event loop stays free during long-running commands."""
    return await asyncio.to_thread(execute_ssh_command, host_name, command)
