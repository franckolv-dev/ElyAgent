# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/compensation_registry.py
# @brief      Registre des compensations — l'exécuteur derrière le champ
#             `CapabilityManifest.compensation` (jusqu'ici une simple string).
# @license    Elastic License 2.0
# =============================================================================
"""Registre de compensations du Reversible Action Journal (substrat / J1).

Le manifeste d'une capacité déclare une *référence* de compensation (ex.
``"restore_from_trash"``). Ce module résout cette référence vers du code réel :

* ``capture(args, result)`` — extrait le MINIMUM nécessaire à l'annulation
  (des identifiants, jamais un secret ni un corps de message) au moment où
  l'action réussit ;
* ``revert(compensation_args, user_id)`` — exécute l'opération inverse à la
  demande d'annulation, en re-résolvant les droits de l'utilisateur (les creds
  ne transitent jamais par le journal).

V1 : une seule famille, l'**opération inverse** (sans snapshot préalable) — la
corbeille Drive EST le snapshot. La compensation par snapshot (update/rename)
viendra en J3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Compensation:
    name: str
    revert: Callable[[dict, str], Awaitable[None]]    # (comp_args, user_id) -> exécute l'inverse
    # Mode « opération inverse » (J1) : capture l'état utile APRÈS succès (ids only).
    capture: Optional[Callable[[dict, str], dict]] = None        # (args, result) -> comp_args
    # (J4) Confirme que l'annulation a RÉELLEMENT pris (ex. fichier hors corbeille).
    # Optionnel, best-effort : (comp_args, user_id) -> True si vérifié.
    verify: Optional[Callable[[dict, str], Awaitable[bool]]] = None
    # (J3) Mode « snapshot » : capture l'état AVANT exécution (rename/move…, où
    # l'état d'avant est perdu après l'action). (args, user_id) -> snapshot dict.
    # Exclusif de `capture` : si `snapshot` est présent, c'est lui qui alimente
    # compensation_args (pré-exécution), via le hook de tool_node.
    snapshot: Optional[Callable[[dict, str], Awaitable[dict]]] = None


async def _creds_for_user(user_id: str) -> str:
    """Creds Google de l'utilisateur, par user_id (même chemin que tool_node).

    Le journal ne stocke jamais de creds : on les re-résout à l'annulation.
    """
    from app.services.credential_store import get_credential_store

    store = get_credential_store()
    creds = store.get(user_id) or ""
    if not creds and user_id:
        try:
            from app.database import async_session
            from app.models.user import User
            async with async_session() as db:
                u = await db.get(User, user_id)
                if u and getattr(u, "google_credentials", None):
                    creds = u.google_credentials
                    store.set(user_id, creds)
        except Exception as exc:  # pragma: no cover — défensif
            logger.debug("creds DB fallback failed for %s: %s", (user_id or "")[:8], exc)
    return creds


async def _drive_untrash(comp_args: dict, user_id: str) -> None:
    """Opération inverse de ``drive_delete_file`` : sortir le fichier de la
    corbeille (``trashed=False``). ``drive_delete_file`` ne fait que trasher
    (``trashed=True``), donc le fichier est récupérable tant que la corbeille
    n'a pas été purgée."""
    file_id = (comp_args or {}).get("file_id")
    if not file_id:
        raise ValueError("compensation_args sans file_id")
    creds = await _creds_for_user(user_id)
    from app.agent.tools.drive_tool import _get_drive_service

    service = await _get_drive_service(creds)
    if not service:
        raise RuntimeError("Google non connecté — restauration impossible")
    # .execute() est bloquant (client Google sync) — on suit le pattern des
    # autres outils Drive (drive_tool.py appelle .execute() de la même façon).
    service.files().update(fileId=file_id, body={"trashed": False}).execute()


async def _drive_is_untrashed(comp_args: dict, user_id: str) -> bool:
    """(J4) Vérifie que le fichier est bien ressorti de la corbeille (trashed=False).

    Best-effort : si on ne peut pas lire l'état, on renvoie False (= non confirmé,
    pas une erreur) plutôt que de prétendre que tout va bien."""
    file_id = (comp_args or {}).get("file_id")
    if not file_id:
        return False
    creds = await _creds_for_user(user_id)
    from app.agent.tools.drive_tool import _get_drive_service

    service = await _get_drive_service(creds)
    if not service:
        return False
    meta = service.files().get(fileId=file_id, fields="trashed").execute()
    return meta.get("trashed") is False


# ── Compensations par SNAPSHOT (J3) : capturer l'état AVANT, restaurer après ──
# Pour rename/move, l'état d'avant (nom / dossier parent) est PERDU après
# l'action → on le lit juste avant l'exécution (hook tool_node) et on le rejoue.


async def _drive_service(user_id: str):
    """Service Drive de l'utilisateur (creds re-résolus par user_id), ou None."""
    creds = await _creds_for_user(user_id)
    from app.agent.tools.drive_tool import _get_drive_service
    return await _get_drive_service(creds)


# --- drive_rename_file : snapshot = ancien nom ---
async def _drive_snapshot_name(args: dict, user_id: str) -> dict:
    file_id = (args or {}).get("file_id")
    if not file_id:
        return {}
    service = await _drive_service(user_id)
    if not service:
        return {}
    meta = service.files().get(fileId=file_id, fields="name").execute()
    return {"file_id": file_id, "name": meta.get("name")}


async def _drive_restore_name(snap: dict, user_id: str) -> None:
    file_id = (snap or {}).get("file_id")
    name = (snap or {}).get("name")
    if not file_id or name is None:
        raise ValueError("snapshot incomplet (file_id/name)")
    service = await _drive_service(user_id)
    if not service:
        raise RuntimeError("Google non connecté — restauration impossible")
    service.files().update(fileId=file_id, body={"name": name}).execute()


async def _drive_verify_name(snap: dict, user_id: str) -> bool:
    file_id = (snap or {}).get("file_id")
    if not file_id:
        return False
    service = await _drive_service(user_id)
    if not service:
        return False
    meta = service.files().get(fileId=file_id, fields="name").execute()
    return meta.get("name") == (snap or {}).get("name")


# --- drive_move_file : snapshot = anciens parents ---
async def _drive_snapshot_parents(args: dict, user_id: str) -> dict:
    file_id = (args or {}).get("file_id")
    if not file_id:
        return {}
    service = await _drive_service(user_id)
    if not service:
        return {}
    meta = service.files().get(fileId=file_id, fields="parents").execute()
    return {"file_id": file_id, "parents": meta.get("parents", [])}


async def _drive_restore_parents(snap: dict, user_id: str) -> None:
    file_id = (snap or {}).get("file_id")
    old = (snap or {}).get("parents") or []
    if not file_id or not old:
        raise ValueError("snapshot incomplet (file_id/parents)")
    service = await _drive_service(user_id)
    if not service:
        raise RuntimeError("Google non connecté — restauration impossible")
    cur = service.files().get(fileId=file_id, fields="parents").execute().get("parents", [])
    service.files().update(
        fileId=file_id,
        addParents=",".join(old),
        removeParents=",".join(cur),
        fields="id,parents",
    ).execute()


async def _drive_verify_parents(snap: dict, user_id: str) -> bool:
    file_id = (snap or {}).get("file_id")
    if not file_id:
        return False
    service = await _drive_service(user_id)
    if not service:
        return False
    cur = set(service.files().get(fileId=file_id, fields="parents").execute().get("parents", []))
    return cur == set((snap or {}).get("parents") or [])


_REGISTRY: dict[str, Compensation] = {
    "restore_from_trash": Compensation(
        name="restore_from_trash",
        # On ne retient QUE l'id du fichier (minimisation — pas de PII/secret).
        capture=lambda args, result: {"file_id": (args or {}).get("file_id")},
        revert=_drive_untrash,
        verify=_drive_is_untrashed,
    ),
    "restore_name": Compensation(
        name="restore_name",
        snapshot=_drive_snapshot_name,     # capture l'ancien nom AVANT le rename
        revert=_drive_restore_name,
        verify=_drive_verify_name,
    ),
    "restore_parents": Compensation(
        name="restore_parents",
        snapshot=_drive_snapshot_parents,  # capture les anciens parents AVANT le move
        revert=_drive_restore_parents,
        verify=_drive_verify_parents,
    ),
}


def get_compensation(name: str | None) -> Optional[Compensation]:
    """Compensation enregistrée pour ``name`` (None si inconnue/absente)."""
    if not name:
        return None
    return _REGISTRY.get(name)
