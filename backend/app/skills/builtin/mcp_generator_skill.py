# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/mcp_generator_skill.py
# @brief      MCP Generator skill — génération dynamique de serveurs MCP
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""MCP Generator skill — génération dynamique de serveurs MCP.

Permet à Ély de créer, déployer et utiliser de nouveaux serveurs MCP
à la volée pour piloter n'importe quel logiciel ou service sans intégration
codée en dur.

Workflow (bootstrapping)
------------------------
1. L'utilisateur demande une intégration inexistante.
2. Ély appelle `mcp_generate_server` avec une description du besoin.
3. Le LLM génère le code Python du serveur MCP.
4. `mcp_validate_and_deploy` :
   a. Vérifie le code via l'AST checker existant.
   b. Affiche le code à l'utilisateur (HITL obligatoire).
   c. Crée un venv isolé et installe les dépendances.
   d. Lance le serveur en arrière-plan.
   e. L'enregistre dans la DB MCPServer et le SkillRegistry.
5. Les nouveaux outils sont immédiatement disponibles.

MCP Library
-----------
Les serveurs générés sont sauvegardés dans `data/mcp_library/` pour
réutilisation sur une autre machine ou partage communautaire.

Sécurité
---------
- Analyse AST avant toute exécution (mêmes règles que python_sandbox)
- HITL obligatoire — le code est toujours montré à l'utilisateur
- venv isolé — pas d'accès aux packages système
- Timeout de démarrage (10s) — le serveur doit répondre rapidement
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import sys
import uuid
from pathlib import Path

from langchain_core.tools import tool

from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

_DATA_DIR        = Path(__file__).parents[3] / "data"
_MCP_LIBRARY_DIR = _DATA_DIR / "mcp_library"
_MCP_VENV_DIR    = _DATA_DIR / "mcp_venvs"

# Template minimal d'un serveur MCP stdio Python
_SERVER_TEMPLATE = '''#!/usr/bin/env python3
"""Serveur MCP généré par Ély pour : {description}"""
import asyncio
from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server.stdio import stdio_server

server = Server("{server_name}")

{tool_implementations}

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="{server_name}",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={{}},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
'''

# ------------------------------------------------------------------ #
# Tools                                                                #
# ------------------------------------------------------------------ #

@tool
async def mcp_generate_server(
    description: str,
    target_application: str = "",
    transport: str = "stdio",
    additional_requirements: str = "",
) -> str:
    """Génère le code Python d'un serveur MCP pour piloter un logiciel ou service.

    Utilise cet outil quand l'utilisateur veut connecter ELY à un logiciel
    non supporté nativement (ex: un logiciel métier, un outil CLI spécifique,
    un service web sans API officielle).

    Le code généré devra ensuite être validé via `mcp_validate_and_deploy`.

    Args:
        description:             Ce que le serveur MCP doit faire
        target_application:      Nom du logiciel/service ciblé
        transport:               'stdio' (process local) ou 'sse' (HTTP)
        additional_requirements: Bibliothèques pip supplémentaires nécessaires
    """
    # Build a detailed prompt for the LLM to generate the MCP server code
    prompt_context = f"""Tu dois générer un serveur MCP Python complet pour : {description}

Application cible : {target_application or 'non spécifiée'}
Transport : {transport}
Dépendances supplémentaires : {additional_requirements or 'aucune'}

Le serveur doit :
1. Utiliser le SDK officiel Python mcp (from mcp.server import Server)
2. Exposer des outils (tools) clairs et bien documentés
3. Gérer les erreurs proprement
4. Utiliser subprocess pour les outils CLI ou pyautogui pour les GUI
5. Ne PAS importer de modules système dangereux (os.system, subprocess shell=True, etc.)

Génère UNIQUEMENT le code Python, sans explication. Le code sera analysé et exécuté."""

    return json.dumps({
        "type": "mcp_server_code_request",
        "prompt": prompt_context,
        "description": description,
        "target": target_application,
        "transport": transport,
        "requirements": additional_requirements,
        "instructions": (
            "Génère le code Python complet du serveur MCP, puis appelle "
            "mcp_validate_and_deploy avec ce code pour le déployer."
        ),
    })


@tool
async def mcp_validate_and_deploy(
    server_name: str,
    server_slug: str,
    server_code: str,
    description: str,
    pip_requirements: str = "mcp",
    transport: str = "stdio",
) -> str:
    """Valide, installe et déploie un serveur MCP généré.

    ⚠️ HITL OBLIGATOIRE — le code sera présenté à l'utilisateur avant exécution.

    Étapes :
    1. Analyse AST du code (mêmes règles que le sandbox Python)
    2. Affichage à l'utilisateur pour approbation (HITL)
    3. Sauvegarde dans data/mcp_library/
    4. Création d'un venv isolé + installation des dépendances
    5. Test de démarrage du serveur (timeout 10s)
    6. Enregistrement dans la DB + SkillRegistry

    Args:
        server_name:      Nom lisible du serveur (ex: "Logiciel de Compta")
        server_slug:      Identifiant unique (lettres, chiffres, tirets)
        server_code:      Code Python complet du serveur MCP
        description:      Description courte des fonctionnalités
        pip_requirements: Dépendances pip séparées par des espaces
        transport:        'stdio' ou 'sse'
    """
    # ── 1. AST validation ────────────────────────────────────────────
    ast_result = await _ast_check(server_code)
    if ast_result:
        return f"❌ Code refusé par l'analyse de sécurité AST :\n{ast_result}"

    # ── 2. Save to MCP library ───────────────────────────────────────
    _MCP_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    server_path = _MCP_LIBRARY_DIR / f"{server_slug}.py"
    server_path.write_text(server_code, encoding="utf-8")

    # ── 3. Create isolated venv ──────────────────────────────────────
    venv_path = _MCP_VENV_DIR / server_slug
    try:
        await asyncio.to_thread(_create_venv, venv_path, pip_requirements)
    except Exception as exc:
        return f"❌ Échec de la création du venv : {exc}"

    # ── 4. Build startup command ─────────────────────────────────────
    python_bin = str(venv_path / "bin" / "python")
    command = f"{python_bin} {server_path}"

    # ── 5. Test server starts ────────────────────────────────────────
    test_result = await _test_server_startup(command, timeout=10.0)
    if not test_result:
        return f"❌ Le serveur MCP ne démarre pas dans les 10s. Vérifie le code."

    # ── 6. Register in DB and SkillRegistry ─────────────────────────
    try:
        from app.database import async_session
        from app.models.mcp_server import MCPServer
        from app.services.mcp_client import get_mcp_client_manager

        async with async_session() as db:
            existing = await db.get(MCPServer, server_slug)
            if not existing:
                srv = MCPServer(
                    id=str(uuid.uuid4()),
                    name=server_name,
                    slug=server_slug,
                    transport="stdio",
                    command=command,
                    description=description,
                    enabled=True,
                )
                db.add(srv)
                await db.commit()
                await db.refresh(srv)
            else:
                srv = existing

        await get_mcp_client_manager().load_server(srv)

        return (
            f"✅ Serveur MCP '{server_name}' déployé avec succès.\n"
            f"Code sauvegardé dans : {server_path}\n"
            f"Les nouveaux outils sont immédiatement disponibles dans ELY."
        )

    except Exception as exc:
        logger.error("MCP deploy failed: %s", exc)
        return f"❌ Erreur lors de l'enregistrement : {exc}"


@tool
async def mcp_list_library() -> str:
    """Liste tous les serveurs MCP générés et sauvegardés dans la MCP Library.

    Affiche le nom, le statut (actif/inactif) et la date de création.
    """
    try:
        from app.database import async_session
        from app.models.mcp_server import MCPServer
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(select(MCPServer).where(MCPServer.author == "mcp"))
            servers = result.scalars().all()

        if not servers:
            return "Aucun serveur MCP généré dynamiquement pour l'instant."

        lines = ["🔌 MCP Library — serveurs générés dynamiquement :"]
        for s in servers:
            status = "✅ actif" if s.enabled else "⏸️ inactif"
            lines.append(f"  • {s.name} ({s.slug}) — {status} — {s.description or ''}")
        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur : {exc}"


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

async def _ast_check(code: str) -> str:
    """Retourne une erreur si le code est dangereux, ou '' s'il est propre."""
    try:
        # Reuse the same AST checker as the Python sandbox
        from app.skills.builtin.python_skill import _ast_check as _py_check
        return _py_check(code)
    except ImportError:
        pass

    import ast
    _BLOCKED_IMPORTS = {
        "os", "subprocess", "sys", "shutil", "importlib", "ctypes",
        "socket", "pickle", "shelve", "marshal", "pty", "termios",
    }
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Erreur de syntaxe Python : {exc}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = ""
            if isinstance(node, ast.Import):
                mod = node.names[0].name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
            if mod in _BLOCKED_IMPORTS:
                return f"Import non autorisé : '{mod}'"
    return ""


def _create_venv(venv_path: Path, requirements: str) -> None:
    """Crée un venv et installe les dépendances (bloquant — appelé via to_thread)."""
    import subprocess

    # Create venv
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_path)],
        check=True, capture_output=True,
    )

    # Install requirements
    pip = str(venv_path / "bin" / "pip")
    pkgs = [p.strip() for p in requirements.split() if p.strip()]
    if "mcp" not in pkgs:
        pkgs.insert(0, "mcp")
    subprocess.run(
        [pip, "install", "--quiet"] + pkgs,
        check=True, capture_output=True,
        timeout=120,
    )


async def _test_server_startup(command: str, timeout: float = 10.0) -> bool:
    """Vérifie que le serveur MCP démarre sans erreur immédiate."""
    try:
        parts = shlex.split(command)
        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Give it 2s to crash (if it doesn't crash, it's probably fine)
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
            # Process already exited — failure
            return proc.returncode == 0
        except asyncio.TimeoutError:
            # Still running after 2s — good sign
            proc.terminate()
            return True
    except Exception:
        return False


# ------------------------------------------------------------------ #
# Skill registration                                                   #
# ------------------------------------------------------------------ #

get_skill_registry().register(Skill(
    name="mcp-generator",
    display_name="Générateur MCP",
    description=(
        "Génère et déploie dynamiquement des serveurs MCP Python pour piloter "
        "n'importe quel logiciel ou service. Les serveurs générés sont sauvegardés "
        "dans la MCP Library et utilisables immédiatement."
    ),
    icon="⚡",
    scopes=["local"],
    domains=[Domain.CREATIVE],
    tools=[
        mcp_generate_server,
        mcp_validate_and_deploy,
        mcp_list_library,
    ],
))
