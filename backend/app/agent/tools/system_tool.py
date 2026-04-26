# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/system_tool.py
# @brief      System Tool module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
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
import platform
import subprocess

from langchain_core.tools import tool


async def _run_subprocess(cmd: list, **kwargs):
    """Run a blocking subprocess in a thread pool to avoid blocking the event loop."""
    return await asyncio.to_thread(subprocess.run, cmd, **kwargs)


@tool
async def system_info() -> str:
    """Retourne les informations sur la machine locale : OS, CPU, mémoire RAM, disque.
    Utilise cet outil quand l'utilisateur demande des infos sur le système, la machine,
    le serveur, le matériel, l'OS, la RAM, le CPU, l'espace disque, ou la version Python.
    Exemples : "infos système", "donne-moi les specs", "quelle est la RAM disponible",
    "informations sur ce système", "état du serveur".
    """
    info = {
        "os": platform.platform(),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
    }

    try:
        system = platform.system()
        if system == "Windows":
            result = await _run_subprocess(
                ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/Value"],
                capture_output=True, text=True, timeout=10,
            )
            info["memory"] = result.stdout.strip()
        elif system == "Darwin":
            result = await _run_subprocess(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=10,
            )
            total_bytes = int(result.stdout.strip())
            total_mb = total_bytes // (1024 * 1024)
            info["memory"] = f"Total: {total_mb} Mo ({total_mb // 1024} Go)"
        else:
            result = await _run_subprocess(
                ["free", "-m"], capture_output=True, text=True, timeout=10,
            )
            info["memory"] = result.stdout.strip()
    except Exception:
        info["memory"] = "unavailable"

    return "\n".join(f"{k}: {v}" for k, v in info.items())
