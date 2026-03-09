import fnmatch
from pathlib import Path

import paramiko
import yaml
import structlog

logger = structlog.get_logger()

_host_config: dict | None = None


def load_host_config() -> dict:
    global _host_config
    if _host_config is not None:
        return _host_config

    config_path = Path(__file__).parent.parent.parent.parent / "config" / "hosts.yaml"
    if config_path.exists():
        with open(config_path) as f:
            _host_config = yaml.safe_load(f) or {}
    else:
        _host_config = {}
    return _host_config


def is_command_allowed(host_name: str, command: str) -> bool:
    config = load_host_config()
    hosts = config.get("hosts", {})
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
    hosts = config.get("hosts", {})
    host = hosts.get(host_name)
    if not host:
        raise ValueError(f"Unknown host: {host_name}")

    if not is_command_allowed(host_name, command):
        raise PermissionError(f"Command not allowed on {host_name}: {command}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

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
