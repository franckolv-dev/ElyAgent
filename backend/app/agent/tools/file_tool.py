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
"""File analysis tool — lecture sécurisée de fichiers avec liste blanche de répertoires.

Seuls les répertoires explicitement autorisés sont accessibles :
  /app/uploads/   — fichiers uploadés par les utilisateurs via l'interface
  /tmp/           — fichiers temporaires du système

Toute tentative de lecture en dehors de ces répertoires est refusée
(LFI / Path Traversal prevention).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from langchain_core.tools import tool

# ── Répertoires autorisés (canoniques) ───────────────────────────────────────
# Seuls des chemins à l'intérieur de ces répertoires peuvent être lus.
# Ajouter ici tout nouveau répertoire jugé nécessaire (jamais la racine /).

_ALLOWED_DIRS: list[Path] = [
    Path("/app/uploads").resolve(),
    Path("/tmp").resolve(),
    Path(tempfile.gettempdir()).resolve(),
]

_MAX_SIZE = 1_000_000  # 1 Mo


def _assert_path_allowed(file_path: str) -> Path:
    """Résout le chemin canonique et vérifie qu'il appartient à un répertoire autorisé.

    Lève PermissionError si le chemin est en dehors de la liste blanche,
    ce qui empêche toute attaque par traversal (../../../etc/passwd, liens symboliques…).
    """
    try:
        resolved = Path(file_path).resolve(strict=False)
    except Exception as exc:
        raise PermissionError(f"Chemin invalide : {file_path}") from exc

    for allowed in _ALLOWED_DIRS:
        try:
            resolved.relative_to(allowed)
            return resolved          # dans la liste blanche → OK
        except ValueError:
            continue

    allowed_display = ", ".join(str(d) for d in _ALLOWED_DIRS)
    raise PermissionError(
        f"Accès refusé : '{file_path}' est en dehors des répertoires autorisés. "
        f"Répertoires accessibles : {allowed_display}"
    )


@tool
def analyze_file(file_path: str) -> str:
    """Read and analyze a file's content.

    Only files located inside /app/uploads/ or /tmp/ can be accessed.
    Attempts to read system files (/etc/passwd, ~/.ssh/id_rsa, .env, etc.)
    will be rejected.

    Args:
        file_path: Absolute path to the file (must be in /app/uploads/ or /tmp/)
    """
    # ── Vérification de sécurité : liste blanche de répertoires ──────────
    try:
        safe_path = _assert_path_allowed(file_path)
    except PermissionError as exc:
        return str(exc)

    if not safe_path.exists():
        return f"Fichier introuvable : {file_path}"
    if not safe_path.is_file():
        return f"N'est pas un fichier : {file_path}"

    size = safe_path.stat().st_size
    if size > _MAX_SIZE:
        return f"Fichier trop volumineux ({size:,} octets — max {_MAX_SIZE:,})."
    if size == 0:
        return f"Fichier vide : {file_path}"

    try:
        content = safe_path.read_text(encoding="utf-8", errors="replace")
        return f"Fichier : {safe_path}\nTaille : {size:,} octets\n\n{content}"
    except Exception as exc:
        return f"Erreur de lecture : {exc}"
