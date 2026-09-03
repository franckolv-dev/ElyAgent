# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/qdrant_backup.py
# @brief      Qdrant snapshot backup service — per-collection REST snapshots with rotation.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Qdrant snapshot backup service.

Takes a snapshot of every Qdrant collection via the REST API, downloads
it to /backups/qdrant/ on the host, and rotates old files.

This runs as a background APScheduler job — zero impact on latency or UX.

Workflow per collection:
  1. POST /collections/{name}/snapshots  → Qdrant creates snapshot
  2. GET  /collections/{name}/snapshots/{file} → stream to local disk
  3. DELETE /collections/{name}/snapshots/{file} → clean up Qdrant side
  4. Rotate: keep only the last KEEP_LAST snapshots on disk
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Collections that must be backed up (mirrors memory_manager.py constants)
_COLLECTIONS = [
    "memories",
    "security_constraints",
    "interactions",
    "user_profile",
    "knowledge",
]

KEEP_LAST = int(os.environ.get("QDRANT_BACKUP_KEEP", "7"))
BACKUP_DIR = Path(os.environ.get("QDRANT_BACKUP_DIR", "/backups/qdrant"))


async def run_backup() -> None:
    """Create and download snapshots for all collections.

    Errors per collection are logged but do not abort the others.
    """
    qdrant_url = _qdrant_base_url()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("[qdrant-backup] starting backup — %d collections", len(_COLLECTIONS))

    async with httpx.AsyncClient(timeout=120.0) as client:
        for collection in _COLLECTIONS:
            try:
                await _backup_collection(client, qdrant_url, collection, timestamp)
            except Exception:
                logger.exception("[qdrant-backup] failed for collection '%s'", collection)

    logger.info("[qdrant-backup] done")


async def _backup_collection(
    client: httpx.AsyncClient,
    qdrant_url: str,
    collection: str,
    timestamp: str,
) -> None:
    col_dir = BACKUP_DIR / collection
    col_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create snapshot
    resp = await client.post(f"{qdrant_url}/collections/{collection}/snapshots")
    resp.raise_for_status()
    snapshot_name: str = resp.json()["result"]["name"]
    logger.debug("[qdrant-backup] snapshot created: %s / %s", collection, snapshot_name)

    # 2. Download snapshot to local disk
    local_path = col_dir / f"{timestamp}_{snapshot_name}"
    dl = await client.get(
        f"{qdrant_url}/collections/{collection}/snapshots/{snapshot_name}"
    )
    dl.raise_for_status()
    local_path.write_bytes(dl.content)
    size_kb = len(dl.content) // 1024
    logger.info(
        "[qdrant-backup] ✓ %s → %s (%d KB)", collection, local_path.name, size_kb
    )

    # 3. Delete snapshot from Qdrant (avoid accumulation on the server side)
    del_resp = await client.delete(
        f"{qdrant_url}/collections/{collection}/snapshots/{snapshot_name}"
    )
    if del_resp.status_code not in (200, 404):
        logger.warning(
            "[qdrant-backup] could not delete server-side snapshot %s: %s",
            snapshot_name, del_resp.status_code,
        )

    # 4. Rotate old backups — keep only the last KEEP_LAST files
    _rotate(col_dir)


def _rotate(col_dir: Path) -> None:
    """Delete oldest snapshot files, keeping at most KEEP_LAST."""
    snapshots = sorted(col_dir.glob("*.snapshot"), key=lambda p: p.stat().st_mtime)
    to_delete = snapshots[:-KEEP_LAST] if len(snapshots) > KEEP_LAST else []
    for old in to_delete:
        old.unlink(missing_ok=True)
        logger.debug("[qdrant-backup] rotated %s", old.name)


def _qdrant_base_url() -> str:
    from app.config import get_settings
    return get_settings().qdrant_url.rstrip("/")
