from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.models.user import User
from app.services.ssh_manager import load_host_config

router = APIRouter()


@router.get("/")
async def list_hosts(user: User = Depends(get_current_user)):
    config = load_host_config()
    hosts = config.get("hosts", {})
    return {
        name: {
            "hostname": h.get("hostname"),
            "port": h.get("port", 22),
            "username": h.get("username"),
            "allowed_commands": h.get("allowed_commands", []),
        }
        for name, h in hosts.items()
    }
