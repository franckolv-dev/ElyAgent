# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_workspace.py
# @brief      Missions autonomes J4 — workspace de mission : artefacts,
#             journal JSONL (rotation), CARNET.md (mémoire de travail).
# @license    MIT
# =============================================================================
"""Workspace d'une mission autonome (cadrage D5).

``data/missions/<mission_id>/`` :
  - ``artefacts/``     — fichiers produits par la mission ;
  - ``journal.jsonl``  — flux append-only des actions (outil, ok, durée,
    résumé tronqué — PAS les args bruts), rotation à ``MISSIONS_JOURNAL_MAX_BYTES`` ;
  - ``CARNET.md``      — carnet de bord : Objectif, Mandat, Leçons, Pause.
    Relu en tête de prompt à chaque planification/replanification — c'est la
    mémoire de travail longue durée de la mission. Écriture ATOMIQUE
    (tmp + os.replace), plafond 64 Ko (la fin — le récent — prime).

Sécurité : ``mission_id`` est validé par regex stricte AVANT toute
construction de chemin (anti-traversal). Tous les appelants utilisent ce
module en best-effort : un disque plein ne tue jamais une mission.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Optional

if TYPE_CHECKING:
    from app.services.mission_spec import MissionMandate

logger = logging.getLogger(__name__)

# uuid4 passe ; refuse séparateurs, points cachés, espaces, longueurs absurdes.
_ID_RE: Final[re.Pattern] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$")

# Défaut = volume data/ monté par docker-compose (même convention que
# agent/missions/checkpointer.py). Overridable pour les tests et le dev hôte.
_DEFAULT_BASE: Final[str] = "/app/data/missions"

_CARNET_MAX_BYTES: Final[int] = 64 * 1024
_JOURNAL_ARCHIVE: Final[str] = "journal.1.jsonl"
_SUMMARY_MAX: Final[int] = 300


def _base_dir() -> Path:
    return Path(os.environ.get("MISSIONS_WORKSPACE_DIR", _DEFAULT_BASE))


def workspace_dir(mission_id: str) -> Path:
    """Chemin du workspace (SANS le créer). Lève ValueError si l'id est
    invalide — la validation précède toute construction de chemin."""
    if not isinstance(mission_id, str) or not _ID_RE.match(mission_id):
        raise ValueError(f"mission_id invalide pour un workspace : {mission_id!r}")
    return _base_dir() / mission_id


def ensure_workspace(mission_id: str) -> Path:
    """Crée (idempotent) ``<base>/<id>/artefacts/`` et renvoie le workspace."""
    ws = workspace_dir(mission_id)
    (ws / "artefacts").mkdir(parents=True, exist_ok=True)
    return ws


# ── Journal JSONL ────────────────────────────────────────────────────────────


def _journal_max_bytes() -> int:
    try:
        return int(os.environ.get("MISSIONS_JOURNAL_MAX_BYTES", 2 * 1024 * 1024))
    except ValueError:
        return 2 * 1024 * 1024


def journal_append(mission_id: str, entry: dict[str, Any]) -> None:
    """Ajoute une ligne au journal (horodatée) avec rotation simple : quand
    ``journal.jsonl`` dépasse le plafond, il devient ``journal.1.jsonl``
    (l'archive précédente est écrasée) et un fichier neuf démarre."""
    ws = ensure_workspace(mission_id)
    path = ws / "journal.jsonl"
    if path.exists() and path.stat().st_size >= _journal_max_bytes():
        os.replace(path, ws / _JOURNAL_ARCHIVE)
    line = dict(entry)
    line.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def read_journal_tail(mission_id: str, n: int = 20) -> list[dict[str, Any]]:
    """Les ``n`` dernières entrées du journal courant (liste vide si aucun)."""
    path = workspace_dir(mission_id) / "journal.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def summarize_result(result: Any) -> str:
    """Résumé sobre d'un résultat d'outil pour le journal (300 car. max)."""
    s = str(result).replace("\n", " ").strip()
    return s[:_SUMMARY_MAX] + ("…" if len(s) > _SUMMARY_MAX else "")


# ── CARNET.md ────────────────────────────────────────────────────────────────


def _carnet_path(mission_id: str) -> Path:
    return workspace_dir(mission_id) / "CARNET.md"


def read_carnet(mission_id: str) -> Optional[str]:
    path = _carnet_path(mission_id)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_carnet(mission_id: str, content: str) -> None:
    """Écriture atomique (tmp + os.replace). Au-delà de 64 Ko, tronque par la
    TÊTE : le récent (fin du carnet) prime sur l'ancien."""
    raw = content.encode("utf-8")
    if len(raw) > _CARNET_MAX_BYTES:
        kept = raw[-_CARNET_MAX_BYTES:].decode("utf-8", "ignore")
        content = "# Carnet de bord (tronqué — début archivé par la limite 64 Ko)\n\n" + kept
    ws = ensure_workspace(mission_id)
    tmp = ws / "CARNET.md.tmp"
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, ws / "CARNET.md")


def carnet_append_section(mission_id: str, section: str, line: str) -> None:
    """Ajoute ``line`` sous ``## <section>`` (créée en fin de carnet si
    absente). Crée un carnet minimal si aucun n'existe."""
    content = read_carnet(mission_id) or "# Carnet de bord\n"
    header = f"## {section}"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"{line}  _({stamp})_"
    if header in content:
        # insérer juste avant la section suivante (ou en fin de fichier)
        idx = content.index(header) + len(header)
        nxt = content.find("\n## ", idx)
        if nxt == -1:
            content = content.rstrip("\n") + f"\n{entry}\n"
        else:
            content = content[:nxt].rstrip("\n") + f"\n{entry}\n" + content[nxt:]
    else:
        content = content.rstrip("\n") + f"\n\n{header}\n{entry}\n"
    write_carnet(mission_id, content)


def init_carnet(
    mission_id: str,
    title: str,
    goal: str,
    mandate: "MissionMandate | None",
) -> None:
    """Squelette initial du carnet — idempotent : ne touche JAMAIS un carnet
    existant (les leçons accumulées priment sur le squelette)."""
    if read_carnet(mission_id) is not None:
        return
    fams = ", ".join(mandate.tools_allow) if mandate is not None else "—"
    mode = (mandate.on_unforeseen if mandate is not None else "supervisé")
    write_carnet(mission_id, (
        f"# Carnet de bord — {title}\n\n"
        f"## Objectif\n{goal}\n\n"
        f"## Mandat\nFamilles autorisées : {fams}. Hors mandat : {mode}.\n\n"
        f"## Leçons\n\n"
        f"## Pause\n"
    ))


def extract_section(mission_id: str, section: str) -> str:
    """Le contenu (sans le titre) de ``## <section>``, chaîne vide sinon."""
    content = read_carnet(mission_id) or ""
    header = f"## {section}"
    if header not in content:
        return ""
    idx = content.index(header) + len(header)
    nxt = content.find("\n## ", idx)
    chunk = content[idx:] if nxt == -1 else content[idx:nxt]
    return chunk.strip()


def carnet_context_block(mission_id: str, max_chars: int = 4000) -> Optional[str]:
    """Le carnet formaté pour le prompt du planner/replan, ou None s'il
    n'existe pas. Troncature par la tête : l'état récent survit."""
    content = read_carnet(mission_id)
    if not content:
        return None
    header = (
        "── CARNET DE BORD DE LA MISSION (mémoire de travail — relis-le avant "
        "de planifier ; consigne tes leçons durables dedans) ──\n"
    )
    budget = max(200, max_chars - len(header))   # le plafond borne le bloc TOTAL
    if len(content) > budget:
        marker = "[…début du carnet tronqué…]\n"
        content = marker + content[-(budget - len(marker)):]
    return header + content
