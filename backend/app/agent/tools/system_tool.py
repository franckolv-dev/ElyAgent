import asyncio
import platform
import subprocess

from langchain_core.tools import tool


async def _run_subprocess(cmd: list, **kwargs):
    """Run a blocking subprocess in a thread pool to avoid blocking the event loop."""
    return await asyncio.to_thread(subprocess.run, cmd, **kwargs)


@tool
def system_info() -> str:
    """Get information about the local system (OS, CPU, memory, disk).
    Use this when the user asks about the current machine's status.
    """
    info = {
        "os": platform.platform(),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
    }

    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/Value"],
                capture_output=True, text=True, timeout=10,
            )
            info["memory"] = result.stdout.strip()
        else:
            result = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=10)
            info["memory"] = result.stdout.strip()
    except Exception:
        info["memory"] = "unavailable"

    return "\n".join(f"{k}: {v}" for k, v in info.items())
