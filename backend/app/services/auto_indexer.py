# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/auto_indexer.py
# @brief      Auto-indexer for watched local folders → RAG knowledge base
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Auto-indexer service — scans WatchedFolder rows and ingests files into RAG.

Pipeline (per folder) :
  1. Ask the user's ELY Desktop daemon to walk the folder (search_files)
  2. Filter by allowed extensions + excluded path substrings
  3. For each candidate file, check if it's already ingested
     (matching ``source_file`` in the user's knowledge collection)
  4. Read the file content via the daemon (read_file) — handles base64 binary
  5. Drop a temporary file on the backend's filesystem
  6. Hand it to ``rag_service.ingest_document`` (existing pipeline :
     extract → chunk → embed → upsert into Qdrant)
  7. Cleanup temp file, update WatchedFolder.last_scan_*

Concurrency is intentionally serial per folder — RAG embedding is the slow
step (CPU-bound on fastembed). Folders of different users CAN run in
parallel since the cron just iterates the table.

Failure modes are recorded in WatchedFolder.last_scan_status :
  - "ok"      : full scan completed, all candidate files indexed or skipped
  - "partial" : some files failed (read error, extract error)
  - "error"   : the scan itself crashed (walk failed, …)
  - "offline" : ELY Desktop n'est pas connecté — rien n'a pu être tenté
  - "running" : a scan is currently in progress (mutex)
  - "pending" : never scanned yet

⚠️ Cette liste était un MENSONGE jusqu'au 21/08 : les deux échecs les plus
fréquents sortaient par `return` avant le bloc de persistance, et la ligne
restait bloquée sur « running ». Toute sortie passe désormais par
`_consigner`. Le contrat que cette docstring décrit est le seul que le code
ait jamais prétendu tenir ; il le tient maintenant.

⚠️ TOUT DÉPEND DU DÉMON. Ce module ne lit pas le système de fichiers du
conteneur — il demande à ELY Desktop, sur la machine de l'utilisateur, de
marcher dans le dossier et de lire les fichiers. Sans démon connecté, aucun
scan n'est possible, et le registre des connexions vit EN MÉMOIRE : un
redémarrage du backend la coupe jusqu'à ce que le démon reprenne la main.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.database import async_session
from app.models.watched_folder import WatchedFolder
from app.services import desktop_registry
from app.services.rag_service import get_rag_service

logger = logging.getLogger(__name__)

# Per-folder mutex so two cron ticks (or cron + manual scan) can't run
# the same folder concurrently. Keys are folder.id, values are bools.
_running_scans: set[str] = set()

# Cap to keep a single scan bounded — the daemon's search_files already
# truncates at 50 by default, but a user might have a custom build.
_MAX_FILES_PER_SCAN = 500

# Per-file size cap to skip huge files that would clobber the embedder
# and bloat Qdrant. RAG handles up to 50 MB but for auto-index we're more
# conservative — large files should be ingested manually if needed.
_MAX_FILE_BYTES_AUTO = 10 * 1024 * 1024  # 10 MB


def _normalize_extensions(raw: str) -> set[str]:
    """Parse ``include_extensions`` field into a lowercase set without dots."""
    return {
        ext.strip().lstrip(".").lower()
        for ext in (raw or "").split(",")
        if ext.strip()
    }


def _parse_excludes(raw: str) -> list[str]:
    """Parse ``exclude_paths`` field into a list of lowercase substrings."""
    return [s.strip().lower() for s in (raw or "").split(",") if s.strip()]


def _file_excluded(path: str, excludes: list[str]) -> bool:
    """Return True if `path` matches any exclude substring."""
    p = path.lower()
    return any(token in p for token in excludes)


def _ext_of(path: str) -> str:
    """Return the lowercase extension of `path` without dot, or ''."""
    return Path(path).suffix.lstrip(".").lower()


# ──────────────────────────────────────────────────────────────────────────────
# Daemon helpers (thin wrappers — the real work is in desktop_registry)
# ──────────────────────────────────────────────────────────────────────────────

async def _daemon_walk(user_id: str, folder: str, recursive: bool) -> list[str]:
    """Ask the daemon to list every file in *folder*. Returns absolute paths.

    Uses the existing `search_files` daemon command with a permissive
    pattern. Recursive is implemented client-side by recursing on dir
    entries returned by `list_dir` if `recursive=True` and `search_files`
    doesn't support recursive globs on this daemon version.
    """
    pattern = "**/*" if recursive else "*"
    try:
        result = await desktop_registry.send_command(
            user_id, "search_files", {"directory": folder, "pattern": pattern}
        )
        matches = result.get("matches", [])
        return [m for m in matches if isinstance(m, str)]
    except Exception as exc:
        logger.warning("auto_indexer: walk failed for %s: %s", folder, exc)
        raise


async def _daemon_read(user_id: str, path: str) -> tuple[bytes, str]:
    """Read a file via the daemon. Returns (raw_bytes, declared_encoding).

    Encoding is "utf-8" for text or "base64" for binary. We always return
    raw bytes so the rag_service text extractors can handle them
    consistently.
    """
    import base64
    result = await desktop_registry.send_command(
        user_id, "read_file", {"path": path}
    )
    content = result.get("content", "")
    encoding = result.get("encoding", "utf-8")
    size = int(result.get("size", 0))
    if size > _MAX_FILE_BYTES_AUTO:
        raise ValueError(f"file exceeds auto-index size cap ({size} > {_MAX_FILE_BYTES_AUTO})")
    if encoding == "base64":
        return base64.b64decode(content), encoding
    return content.encode("utf-8", errors="ignore"), encoding


# ──────────────────────────────────────────────────────────────────────────────
# Scan one folder
# ──────────────────────────────────────────────────────────────────────────────

async def _consigner(folder_id: str, statut: str, message: str,
                     indexes: int = 0, *, seulement_si_change: bool = False) -> None:
    """Écrit l'issue d'un scan sur la ligne du dossier.

    **Le défaut qu'elle corrige (21/08).** `scan_folder` posait
    ``last_scan_status = "running"`` puis SORTAIT par `return` sur ses deux
    échecs les plus fréquents — démon absent, marche impossible — sans jamais
    atteindre le bloc de persistance, tout en bas. La ligne restait donc à
    « running / Scan en cours… » indéfiniment.

    Franck l'a vu sur un dossier surveillé depuis des mois : badge `running`,
    « Scan en cours... », **0 fichier indexé**. L'interface annonçait un
    travail qui n'avait jamais commencé — c'est l'invariant 5 du dépôt, une
    fausse déclaration d'action, avec en prime la docstring de ce module qui
    promettait que ``last_scan_status`` enregistre les modes d'échec.

    ``seulement_si_change`` sert au cron horaire : réécrire la même ligne
    toutes les heures ferait battre ``last_scan_at`` et donnerait l'illusion
    d'un scan qui tourne. On ne touche la ligne que quand l'état bouge.
    """
    try:
        async with async_session() as db:
            folder = await db.get(WatchedFolder, folder_id)
            if folder is None:
                return
            if seulement_si_change and folder.last_scan_status == statut:
                return
            folder.last_scan_at = datetime.now(timezone.utc)
            folder.last_scan_status = statut
            folder.last_scan_message = message
            if indexes:
                folder.files_indexed = (folder.files_indexed or 0) + indexes
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — consigner ne casse pas un scan
        logger.warning("auto_indexer: état non consigné pour %s : %s", folder_id, exc)


async def scan_folder(folder_id: str) -> dict:
    """Scan a single WatchedFolder and ingest new files.

    Returns a summary dict ``{indexed: int, skipped: int, errors: int,
    status: str, message: str}``.

    ⚠️ CHAQUE sortie consigne son issue sur la ligne — voir `_consigner`. Un
    `return` qui saute la persistance laisse le dossier bloqué sur « running »
    pour toujours ; c'est le défaut qui a rendu cette fonctionnalité muette
    pendant des mois.
    """
    if folder_id in _running_scans:
        return {"status": "running", "message": "Scan already in progress"}

    _running_scans.add(folder_id)
    summary = {"indexed": 0, "skipped": 0, "errors": 0, "status": "ok", "message": ""}

    try:
        async with async_session() as db:
            folder = await db.get(WatchedFolder, folder_id)
            if folder is None:
                summary["status"] = "error"
                summary["message"] = "Dossier surveillé introuvable"
                # Rien à écrire — la ligne n'existe pas, `_consigner` le voit
                # et ne fait rien. On l'appelle quand même : « toute sortie
                # consigne » sans exception se vérifie et se relit ; une règle
                # à un cas particulier se re-justifie à chaque lecture, et
                # c'est comme ça qu'on finit par en ajouter un second.
                await _consigner(folder_id, summary["status"], summary["message"])
                return summary
            user_id = folder.user_id
            allowed_ext = _normalize_extensions(folder.include_extensions)
            excludes = _parse_excludes(folder.exclude_paths)
            recursive = folder.recursive
            path = folder.path

            # Mark as running so the UI shows progress
            folder.last_scan_status = "running"
            folder.last_scan_message = "Scan en cours…"
            await db.commit()

        # ── 1. Daemon walk ────────────────────────────────────────────────
        # `offline` et non `error` : rien n'a échoué, il n'y a simplement
        # personne au bout du fil. Le geste attendu n'est pas le même — on
        # lance ELY Desktop, on ne cherche pas une panne. Le registre des
        # démons est EN MÉMOIRE : un redémarrage du backend suffit à couper
        # la connexion tant que le démon n'a pas repris la main.
        if not desktop_registry.is_connected(user_id):
            summary["status"] = "offline"
            summary["message"] = (
                "ELY Desktop n'est pas connecté — l'indexation lit les fichiers "
                "par le démon, elle ne peut rien faire sans lui."
            )
            await _consigner(folder_id, summary["status"], summary["message"])
            return summary

        try:
            all_paths = await _daemon_walk(user_id, path, recursive)
        except Exception as exc:
            summary["status"] = "error"
            summary["message"] = f"Parcours du dossier impossible : {exc}"
            await _consigner(folder_id, summary["status"], summary["message"])
            return summary

        # ── 2. Filter ─────────────────────────────────────────────────────
        candidates = [
            p for p in all_paths
            if _ext_of(p) in allowed_ext
            and not _file_excluded(p, excludes)
        ][:_MAX_FILES_PER_SCAN]

        # ── 3. Dedup against current RAG knowledge for this user ──────────
        rag = get_rag_service()
        try:
            existing_docs = await rag.list_documents(user_id)
            existing_sources = {d.get("source_file", "") for d in existing_docs}
        except Exception:
            existing_sources = set()

        # ── 4. Ingest new ─────────────────────────────────────────────────
        for fpath in candidates:
            fname = Path(fpath).name
            if fpath in existing_sources or fname in existing_sources:
                summary["skipped"] += 1
                continue
            try:
                raw_bytes, _enc = await _daemon_read(user_id, fpath)
            except Exception as exc:
                logger.info("auto_indexer: skip %s (read error: %s)", fpath, exc)
                summary["errors"] += 1
                continue

            # Drop to temp file so rag_service can read with its existing
            # extractors (PDF/DOCX/XLSX need a Path, not in-memory bytes).
            ext = _ext_of(fpath) or "txt"
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=f".{ext}", prefix="ely-autoidx-"
            ) as tmp:
                tmp.write(raw_bytes)
                tmp_path = Path(tmp.name)

            try:
                # Use the original filename + path as source so the RAG
                # answer can cite it ("found in /Users/.../foo.pdf").
                await rag.ingest_document(
                    file_path=tmp_path,
                    user_id=user_id,
                    title=fname,
                    source_file=fpath,
                )
                summary["indexed"] += 1
            except Exception as exc:
                logger.info("auto_indexer: ingest failed for %s: %s", fpath, exc)
                summary["errors"] += 1
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

        # ── 5. Compute status + persist ───────────────────────────────────
        if summary["errors"] > 0 and summary["indexed"] == 0:
            summary["status"] = "error"
        elif summary["errors"] > 0:
            summary["status"] = "partial"
        else:
            summary["status"] = "ok"

        summary["message"] = (
            f"Indexé {summary['indexed']}, ignoré {summary['skipped']}, "
            f"erreurs {summary['errors']}"
        )

        await _consigner(
            folder_id, summary["status"], summary["message"], summary["indexed"],
        )
        return summary
    finally:
        _running_scans.discard(folder_id)


# ──────────────────────────────────────────────────────────────────────────────
# Periodic cron entry point
# ──────────────────────────────────────────────────────────────────────────────

async def scan_all_enabled() -> dict:
    """Iterate every enabled WatchedFolder and scan it.

    Designed to be called by APScheduler. Returns a per-user summary dict
    that can be logged but isn't persisted (per-folder rows ARE updated).
    """
    async with async_session() as db:
        result = await db.execute(
            select(WatchedFolder).where(WatchedFolder.enabled == True)  # noqa: E712
        )
        folders = list(result.scalars())

    overall = {"folders_scanned": 0, "total_indexed": 0, "total_errors": 0,
               "folders_offline": 0}
    for f in folders:
        # ⚠️ Ce `continue` était MUET, et c'est ce qui a rendu la
        # fonctionnalité invisible. Le cron tournait toutes les heures,
        # trouvait le dossier, constatait le démon absent, passait — sans une
        # ligne de log ni un mot sur la ligne du dossier. Pendant des mois,
        # côté écran, rien ne distinguait « ça marche » de « ça n'a jamais
        # démarré ». Le commentaire d'origine disait « no point trying », ce
        # qui est vrai : le défaut n'était pas de sauter, c'était de le taire.
        #
        # `seulement_si_change` : on ne réécrit pas la ligne à chaque heure,
        # sinon `last_scan_at` battrait et donnerait l'illusion d'un scan.
        if not desktop_registry.is_connected(f.user_id):
            overall["folders_offline"] += 1
            await _consigner(
                f.id, "offline",
                "ELY Desktop n'est pas connecté — scan horaire sans effet.",
                seulement_si_change=True,
            )
            continue
        try:
            s = await scan_folder(f.id)
            overall["folders_scanned"] += 1
            overall["total_indexed"] += s.get("indexed", 0)
            overall["total_errors"] += s.get("errors", 0)
        except Exception as exc:
            logger.warning("auto_indexer cron: folder %s crashed: %s", f.id, exc)
            overall["total_errors"] += 1
    return overall
