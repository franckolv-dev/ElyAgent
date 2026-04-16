# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/ssh_manager.py
# @brief      Ssh Manager module
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
import asyncio
import base64
import re
from io import StringIO
from pathlib import Path

import paramiko
import yaml
import logging

logger = logging.getLogger(__name__)

_host_config: dict | None = None

# Shell metacharacters that indicate injection attempts.
# Checked before any pattern matching.
_SHELL_META = re.compile(r'[;&|`$<>\\\'\"()\n\r]')

# Single token: no whitespace, no metacharacters (used in wildcard slots)
_SAFE_TOKEN = re.compile(r'^[^\s;&|`$<>\\\'\"()\n\r]+$')


def load_host_config() -> dict:
    global _host_config
    if _host_config is not None:
        return _host_config

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


def _match_command(command: str, pattern: str) -> bool:
    """Token-based command matching (SEC-5).

    Replaces fnmatch to prevent extra-argument injection.

    Rules:
    - Split both command and pattern into whitespace-delimited tokens
    - Literal tokens must match exactly (case-sensitive)
    - A single '*' token matches exactly ONE command token (no spaces)
    - The number of tokens must be identical — no extra tokens allowed

    Examples:
        _match_command("docker ps", "docker ps")           → True
        _match_command("docker logs myapp", "docker logs *") → True
        _match_command("docker logs a b", "docker logs *") → False (2 args, 1 slot)
        _match_command("ls /var/log", "ls *")              → True
        _match_command("ls /var /etc", "ls *")             → False
    """
    cmd_tokens = command.split()
    pat_tokens = pattern.split()

    if len(cmd_tokens) != len(pat_tokens):
        return False

    for cmd_tok, pat_tok in zip(cmd_tokens, pat_tokens):
        if pat_tok == "*":
            # Wildcard slot: argument must be a single safe token
            if not _SAFE_TOKEN.match(cmd_tok):
                return False
        elif cmd_tok != pat_tok:
            return False

    return True


def is_command_allowed(host_name: str, command: str) -> bool:
    """Return True only if command is explicitly permitted for this host."""
    # Reject shell metacharacters before anything else
    if _SHELL_META.search(command):
        logger.warning("shell_metachar_blocked", host=host_name, command=command[:200])
        return False

    config = load_host_config()
    hosts = config.get("hosts") or {}
    host = hosts.get(host_name)
    if not host:
        return False

    # Blocked patterns take precedence (substring match is intentional here —
    # these are safety nets for catastrophic commands like "rm -rf")
    for pattern in host.get("blocked_patterns", []):
        if pattern in command:
            logger.warning("blocked_command", host=host_name, command=command, pattern=pattern)
            return False

    # Strict token-based whitelist
    for pattern in host.get("allowed_commands", []):
        if _match_command(command, pattern):
            return True

    return False


def _load_host_keys(host: dict) -> paramiko.HostKeys | None:
    """Build a HostKeys object from the fingerprint stored in hosts.yaml.

    The 'host_key' field must be in the format returned by ssh-keyscan:
        "<key-type> <base64-key>"
    e.g.:
        host_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA..."

    Returns None if no host_key is configured.
    """
    raw = host.get("host_key", "").strip()
    if not raw:
        return None

    hostname = host["hostname"]
    port = host.get("port", 22)
    # paramiko known_hosts format: "[hostname]:port key-type base64"  (non-22)
    # or "hostname key-type base64"  (port 22)
    if port != 22:
        known_hosts_line = f"[{hostname}]:{port} {raw}\n"
    else:
        known_hosts_line = f"{hostname} {raw}\n"

    host_keys = paramiko.HostKeys()
    host_keys.load(StringIO(known_hosts_line))
    return host_keys


def execute_ssh_command(host_name: str, command: str) -> tuple[int, str, str]:
    config = load_host_config()
    hosts = config.get("hosts") or {}
    host = hosts.get(host_name)
    if not host:
        raise ValueError(f"Unknown host: {host_name}")

    if not is_command_allowed(host_name, command):
        raise PermissionError(f"Command not allowed on {host_name}: {command}")

    client = paramiko.SSHClient()

    # SEC-6: use RejectPolicy when a host_key fingerprint is configured.
    # Without a fingerprint, fall back to WarningPolicy and emit a loud warning.
    host_keys = _load_host_keys(host)
    if host_keys is not None:
        client._host_keys = host_keys
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        logger.warning(
            "ssh_no_fingerprint",
            host=host_name,
            msg=(
                "No host_key configured — using WarningPolicy (MITM risk). "
                "Add 'host_key' to hosts.yaml. "
                "Run: ssh-keyscan -t ed25519 <hostname> to get the fingerprint."
            ),
        )
        client.set_missing_host_key_policy(paramiko.WarningPolicy())

    try:
        connect_kwargs: dict = {
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
    """Async wrapper — runs blocking SSH call in a thread pool."""
    return await asyncio.to_thread(execute_ssh_command, host_name, command)
