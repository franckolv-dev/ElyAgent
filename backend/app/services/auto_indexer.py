# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/auto_indexer.py
# @brief      Auto-indexer for watched local folders → RAG knowledge base
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Auto-indexer service — scans WatchedFolder rows and ingests files into RAG.

Pipeline (per folder) :
  1. Ask the user's ELY Desktop daemon to list each folder (list_dir)
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
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import select

from app.database import async_session
from app.models.watched_folder import WatchedFolder
from app.services import desktop_registry
from app.services.rag_service import get_rag_service

logger = logging.getLogger(__name__)

# Per-folder mutex so two cron ticks (or cron + manual scan) can't run
# the same folder concurrently. Keys are folder.id, values are bools.
_running_scans: set[str] = set()

# Cap new files per scan, after excluding already indexed documents.
_MAX_FILES_PER_SCAN = 500
_MAX_DIRECTORIES_PER_SCAN = 10_000

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

def _lisible_localement(folder: str) -> bool:
    """Le dossier est-il visible depuis le conteneur ?

    Vrai quand l'utilisateur a monté son dossier dans `docker-compose.yml`
    (cf. `ELY_INDEX_PATH` dans `.env.example`). Le montage se fait au MÊME
    chemin absolu des deux côtés, donc `/Users/franck/Documents` existe tel
    quel ici — aucune traduction, et les citations RAG restent vraies.
    """
    try:
        p = Path(folder)
        return p.is_dir() and os.access(p, os.R_OK)
    except Exception:  # noqa: BLE001 — un chemin exotique ne casse pas le scan
        return False


def _mode_de_lecture(user_id: str, folder: str) -> str:
    """``"local"`` | ``"daemon"`` | ``"offline"`` — qui va lire les fichiers.

    Le LOCAL prime, et pas par préférence esthétique : il ne demande aucun
    processus à l'utilisateur, il survit aux redémarrages du backend (le
    registre des démons vit en mémoire), et le montage est en lecture seule —
    donc plus étroit que le démon, qui peut lire tout ce que le compte peut
    lire.

    Le démon reste le chemin des dossiers NON montés : en ajouter un ne
    demande alors ni édition de `docker-compose.yml` ni redémarrage.
    """
    if _lisible_localement(folder):
        return "local"
    if desktop_registry.is_connected(user_id):
        return "daemon"
    return "offline"


async def _local_walk(folder: str, recursive: bool) -> list[str]:
    """Marche dans un dossier MONTÉ dans le conteneur. Chemins absolus.

    ⚠️ Passe par un thread : `rglob` sur une arborescence de plusieurs
    milliers d'entrées bloque, et bloquer ici gèlerait tout le backend —
    le cron tourne dans la même boucle que les conversations.
    """
    def _marcher() -> list[str]:
        base = Path(folder)
        it = base.rglob("*") if recursive else base.glob("*")
        out: list[str] = []
        for p in it:
            try:
                if p.is_file():
                    out.append(str(p))
            except OSError:
                continue    # lien cassé, permission refusée : on passe
        return out

    return await asyncio.to_thread(_marcher)


async def _local_read(path: str) -> tuple[bytes, str]:
    """Lit un fichier monté. Même contrat que `_daemon_read`."""
    def _lire() -> bytes:
        p = Path(path)
        taille = p.stat().st_size
        if taille > _MAX_FILE_BYTES_AUTO:
            raise ValueError(
                f"file exceeds auto-index size cap ({taille} > {_MAX_FILE_BYTES_AUTO})"
            )
        return p.read_bytes()

    return await asyncio.to_thread(_lire), "binary"


async def _daemon_walk(
    user_id: str, folder: str, recursive: bool, excludes: list[str] | None = None,
) -> list[str]:
    """List files using the Desktop v1 protocol, preserving host path syntax.

    Desktop's search_files matches basenames with Go filepath.Match: **/*
    cannot match, and no matches serialize as null. Its results are relative
    and include directories. list_dir gives explicit types and also reports
    missing/inaccessible directories instead of silently treating them as empty.
    Symlinks are not followed; each visited directory is sandbox-checked by Desktop.
    """
    path_type = PureWindowsPath if PureWindowsPath(folder).is_absolute() else PurePosixPath
    pending = [path_type(folder)]
    visited = set()
    paths: list[str] = []
    while pending:
        directory = pending.pop()
        if directory in visited:
            continue
        if len(visited) >= _MAX_DIRECTORIES_PER_SCAN:
            raise ValueError("Trop de sous-dossiers : choisissez un dossier plus précis.")
        visited.add(directory)
        result = await desktop_registry.send_command(
            user_id, "list_dir", {"path": str(directory)}
        )
        if not isinstance(result, dict) or "entries" not in result:
            raise ValueError("Réponse de parcours invalide reçue d’ELY Desktop.")
        entries = result["entries"]
        if entries is None:  # Go nil slices can be encoded as JSON null.
            entries = []
        if not isinstance(entries, list):
            raise ValueError("Liste de fichiers invalide reçue d’ELY Desktop.")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Entrée de dossier invalide reçue d’ELY Desktop.")
            name = entry.get("name")
            if (not isinstance(name, str) or not name or name in {".", ".."}
                    or path_type(name).anchor or len(path_type(name).parts) != 1):
                raise ValueError("Nom de fichier invalide reçu d’ELY Desktop.")
            child = directory / name
            if _file_excluded(str(child), excludes or []):
                continue
            if entry.get("type") == "file":
                paths.append(str(child))
            elif entry.get("type") == "dir" and recursive:
                pending.append(child)
    return paths


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

        # ── 1. Qui lit ? ──────────────────────────────────────────────────
        mode = _mode_de_lecture(user_id, path)

        # `offline` et non `error` : rien n'a échoué, il n'y a simplement
        # personne au bout du fil et le dossier n'est pas monté. Le geste
        # attendu n'est pas le même — on lance ELY Desktop ou on monte le
        # dossier, on ne cherche pas une panne. Le registre des démons est EN
        # MÉMOIRE : un redémarrage du backend suffit à couper la connexion
        # tant que le démon n'a pas repris la main.
        if mode == "offline":
            summary["status"] = "offline"
            summary["message"] = (
                "Dossier illisible : ni monté dans le conteneur (ELY_INDEX_PATH) "
                "ni servi par ELY Desktop, qui n'est pas connecté."
            )
            await _consigner(folder_id, summary["status"], summary["message"])
            return summary

        try:
            if mode == "local":
                all_paths = await _local_walk(path, recursive)
            else:
                all_paths = await _daemon_walk(user_id, path, recursive, excludes)
        except Exception as exc:
            summary["status"] = "error"
            summary["message"] = f"Parcours du dossier impossible : {exc}"
            await _consigner(folder_id, summary["status"], summary["message"])
            return summary

        # ── 2. Filter ─────────────────────────────────────────────────────
        retenus = [
            p for p in all_paths
            if _ext_of(p) in allowed_ext
            and not _file_excluded(p, excludes)
        ]
        # ── 3. Dedup against current RAG knowledge for this user ──────────
        rag = get_rag_service()
        try:
            existing_docs = await rag.list_documents(user_id)
            existing_sources = {d.get("source_file", "") for d in existing_docs}
        except Exception:
            existing_sources = set()

        # Applying the cap before dedup would revisit the same first 500
        # documents forever, starving every later file on subsequent scans.
        new_paths = [p for p in retenus
                     if p not in existing_sources and Path(p).name not in existing_sources]
        summary["skipped"] = len(retenus) - len(new_paths)
        candidates = new_paths[:_MAX_FILES_PER_SCAN]
        remaining = len(new_paths) - len(candidates)

        # ── 4. Ingest new ─────────────────────────────────────────────────
        for fpath in candidates:
            fname = Path(fpath).name
            try:
                if mode == "local":
                    raw_bytes, _enc = await _local_read(fpath)
                else:
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
        elif summary["errors"] > 0 or remaining:
            summary["status"] = "partial"
        else:
            summary["status"] = "ok"

        # Le MODE figure dans le message : c'est la seule façon pour
        # l'utilisateur de savoir si son montage sert vraiment, ou si tout
        # passe encore par le démon sans qu'il s'en doute.
        _source = "dossier monté" if mode == "local" else "ELY Desktop"
        summary["message"] = (
            f"Indexé {summary['indexed']}, ignoré {summary['skipped']}, "
            f"erreurs {summary['errors']} — via {_source}"
        )
        if remaining:
            summary["message"] += f" — {remaining} fichier(s) restant(s) au prochain scan"

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
        #
        # ⚠️ La condition interroge `_mode_de_lecture` et NON le seul démon.
        # Tester `is_connected` ici écarterait les dossiers MONTÉS, qui n'ont
        # justement pas besoin de lui — le cron horaire n'aurait alors jamais
        # rien indexé pour eux, et on aurait remplacé une dépendance muette
        # par une autre.
        if _mode_de_lecture(f.user_id, f.path) == "offline":
            overall["folders_offline"] += 1
            await _consigner(
                f.id, "offline",
                "Ni monté dans le conteneur, ni servi par ELY Desktop — "
                "scan horaire sans effet.",
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
