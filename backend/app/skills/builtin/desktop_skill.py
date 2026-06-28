# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/desktop_skill.py
# @brief      ELY Desktop skill — 9 filesystem tools relayed to the local daemon
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""ELY Desktop skill — 9 filesystem tools relayed to the local daemon.

Each tool:
1. Verifies the desktop daemon is connected via desktop_registry.is_connected(user_id)
2. Sends the command via desktop_registry.send_command(user_id, cmd, args)
3. Formats the response as a readable string

Write/move/delete tools are listed in ALWAYS_CRITICAL_TOOLS in security_filter.py
so they trigger HITL validation automatically — no extra confirmation logic here.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
async def desktop_list_dir(path: str, user_id: str = "") -> str:
    """Liste le contenu d'un répertoire sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté. path: chemin absolu dans un répertoire autorisé."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "list_dir", {"path": path}
        )
        entries = result.get("entries", [])
        if not entries:
            return f"Répertoire vide : {path}"
        lines = [f"Contenu de {path} ({len(entries)} entrées) :"]
        for e in entries:
            kind = "📁" if e.get("type") == "dir" else "📄"
            size = e.get("size", 0)
            modified = e.get("modified", "")
            size_str = f"  {size:,} o" if e.get("type") != "dir" else ""
            lines.append(f"  {kind} {e.get('name', '?')}{size_str}  {modified}")
        return "\n".join(lines)
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_read_file(path: str, user_id: str = "") -> str:
    """Lit le contenu d'un fichier sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté. path: chemin absolu dans un répertoire autorisé.
    Limite : 5 Mo. Les fichiers binaires sont encodés en base64."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "read_file", {"path": path}
        )
        content = result.get("content", "")
        encoding = result.get("encoding", "utf-8")
        size = result.get("size", 0)
        if encoding == "base64":
            return f"Fichier binaire ({size:,} octets, base64) :\n{content}"
        return f"Contenu de {path} ({size:,} octets) :\n{content}"
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_write_file(path: str, content: str, user_id: str = "") -> str:
    """Écrit du contenu dans un fichier sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté et validation HITL.
    path: chemin absolu dans un répertoire autorisé.
    content: contenu texte à écrire."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "write_file", {"path": path, "content": content}
        )
        return f"Fichier écrit avec succès : {path} ({result.get('bytes_written', 0):,} octets)"
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_move_file(src: str, dst: str, user_id: str = "") -> str:
    """Déplace ou renomme un fichier/répertoire sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté et validation HITL.
    src: chemin source absolu. dst: chemin destination absolu."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "move_file", {"src": src, "dst": dst}
        )
        return f"Déplacé avec succès : {src} → {dst}"
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_delete_file(path: str, user_id: str = "") -> str:
    """Supprime un fichier ou répertoire sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté et validation HITL obligatoire.
    path: chemin absolu dans un répertoire autorisé."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "delete_file", {"path": path}
        )
        return f"Supprimé avec succès : {path}"
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_create_dir(path: str, user_id: str = "") -> str:
    """Crée un répertoire (et ses parents) sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté. path: chemin absolu dans un répertoire autorisé."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "create_dir", {"path": path}
        )
        return f"Répertoire créé : {path}"
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_stat_file(path: str, user_id: str = "") -> str:
    """Retourne les métadonnées d'un fichier ou répertoire (taille, dates, permissions).
    Requiert ELY Desktop connecté. path: chemin absolu dans un répertoire autorisé."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "stat_file", {"path": path}
        )
        lines = [f"Informations sur : {path}"]
        for k, v in result.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_hash_file(path: str, user_id: str = "") -> str:
    """Calcule le hash SHA-256 d'un fichier sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté. path: chemin absolu dans un répertoire autorisé."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "hash_file", {"path": path}
        )
        sha256 = result.get("sha256", "inconnu")
        size = result.get("size", 0)
        return f"SHA-256 de {path} ({size:,} octets) :\n{sha256}"
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


@tool
async def desktop_search_files(
    directory: str,
    pattern: str,
    user_id: str = "",
) -> str:
    """Recherche des fichiers par motif dans un répertoire sur la machine de l'utilisateur.
    Requiert ELY Desktop connecté.
    directory: répertoire de recherche absolu. pattern: motif glob (ex: *.py, **/*.txt)."""
    from app.services import desktop_registry

    if not desktop_registry.is_connected(user_id):
        return (
            "ELY Desktop n'est pas connecté. "
            "Téléchargez et lancez le daemon depuis Paramètres > ELY Desktop."
        )
    try:
        result = await desktop_registry.send_command(
            user_id, "search_files", {"directory": directory, "pattern": pattern}
        )
        matches = result.get("matches", [])
        if not matches:
            return f"Aucun fichier correspondant à '{pattern}' dans {directory}"
        lines = [f"{len(matches)} fichier(s) correspondant à '{pattern}' dans {directory} :"]
        for m in matches[:50]:  # safety cap
            lines.append(f"  {m}")
        if len(matches) > 50:
            lines.append(f"  ... et {len(matches) - 50} résultats supplémentaires")
        return "\n".join(lines)
    except desktop_registry.DesktopNotConnectedError as exc:
        return f"Desktop non connecté : {exc}"
    except desktop_registry.DesktopCommandError as exc:
        return f"Erreur de commande : {exc}"
    except desktop_registry.DesktopTimeoutError as exc:
        return f"Délai dépassé : {exc}"


# ---------------------------------------------------------------------------
# Skill registration
# ---------------------------------------------------------------------------

def register_desktop_skill() -> None:
    """Register the ELY Desktop skill into the global SkillRegistry."""
    get_skill_registry().register(Skill(
        name="desktop",
        display_name="ELY Desktop",
        description=(
            "Accès au système de fichiers local de l'utilisateur via le daemon ELY Desktop. "
            "Lister, lire, écrire, déplacer, supprimer des fichiers et répertoires. "
            "Requiert l'installation et le lancement du daemon ELY Desktop."
        ),
        icon="💻",
        scopes=[],
        domains=[Domain.DESKTOP],
        tools=[
            desktop_list_dir,
            desktop_read_file,
            desktop_write_file,
            desktop_move_file,
            desktop_delete_file,
            desktop_create_dir,
            desktop_stat_file,
            desktop_hash_file,
            desktop_search_files,
        ],
    ))
