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
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.models.user import User
from app.services.ssh_manager import load_host_config

router = APIRouter()


@router.get("/")
async def list_hosts(user: User = Depends(get_current_user)):
    config = load_host_config()
    hosts = config.get("hosts") or {}
    return {
        name: {
            "hostname": h.get("hostname"),
            "port": h.get("port", 22),
            "username": h.get("username"),
            "allowed_commands": h.get("allowed_commands", []),
        }
        for name, h in hosts.items()
    }
