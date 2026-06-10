# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/graduation_codegen.py
# @brief      Sprint 4d (V4) J4 — codegen de graduation : learned python_tool
#             → fichier core + test pytest + manifest, prêts pour la PR (J5).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Codegen de graduation — design note Sprint 4d §4.3.

Produit des CONTENUS (chemins + sources), jamais de fichiers : le backend
tourne en Docker sans checkout git, la matérialisation se fait par la PR
GitHub (J5) ou l'export. Trois artefacts :

1. ``app/agent/tools/graduated/<name>_tool.py`` — la source du learned tool
   INCHANGÉE (le scaffold V2 ``@register + @tool`` est déjà le format
   auto-discovery du Sprint 2 — choix de design qui paie ici), précédée de
   l'en-tête licence du projet + un bloc de PROVENANCE (skill_id, stats au
   moment T, validation). ``pkgutil.walk_packages`` étant récursif, le
   sous-package est découvert au boot sans câblage.
2. ``tests/test_graduated_<name>.py`` — pin minimal : l'import marche, le
   tool est bindable, le nom et la docstring sont stables ; + une
   invocation réelle quand l'admin fournit des ``smoke_kwargs``.
3. ``grad_manifest`` (dict) — la photo des preuves, embarquée dans le corps
   de la PR : c'est elle que Franck review.

Le dry-run rejoue la validation 7 étages sur le content (un outil promu il
y a des semaines doit repasser les gates du jour) et vérifie les
dépendances de composition (chaque ``call_tool("x")`` doit viser un tool
core existant et composable — jamais un autre learned tool).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Racine (relative au repo) du package des tools gradués.
GRADUATED_PKG_DIR = "backend/app/agent/tools/graduated"

# call_tool("nom", …) / call_tool('nom', …) — les compositions n'utilisent
# que des littéraux (imposé par le prompt du générateur V2).
_CALL_TOOL_RE = re.compile(r"""call_tool\(\s*["']([A-Za-z0-9_]+)["']""")

_INIT_PY = '''\
"""Tools gradués — générés par Ely (Sprint 4d V4), revus et mergés par PR.

Chaque module de ce package est un learned python_tool qui a fait ses
preuves à l'usage (gates de graduation) puis a été converti en code core.
La provenance complète est dans l'en-tête de chaque fichier ; la row
``learned_skills`` d'origine est conservée en base (status='graduated').
"""
'''


def _slug(name: str) -> str:
    """Nom de module sûr — le nom d'un tool est déjà un identifiant Python
    (imposé par le générateur), ceinture-bretelles quand même."""
    slug = re.sub(r"[^a-z0-9_]", "_", (name or "tool").lower()).strip("_")
    return slug or "tool"


def graduated_tool_path(tool_name: str) -> str:
    return f"{GRADUATED_PKG_DIR}/{_slug(tool_name)}_tool.py"


def graduated_test_path(tool_name: str) -> str:
    return f"backend/tests/test_graduated_{_slug(tool_name)}.py"


# ─────────────────────────────────────────────────────────────────────────
# Artefacts
# ─────────────────────────────────────────────────────────────────────────


def build_manifest(skill: Any, stats: dict[str, Any]) -> dict[str, Any]:
    """La photo des preuves au moment de la graduation — corps de PR (J5)
    et bloc de provenance du fichier. Aucune PII : l'user est tronqué."""
    return {
        "learned_skill_id": skill.id,
        "tool_name": skill.name,
        "tool_profile": getattr(skill, "tool_profile", "pure") or "pure",
        "origin_user": (skill.user_id or "")[:8],
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "graduated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": stats.get("stats", {}),
        "thresholds": stats.get("thresholds", {}),
        "gates": [
            {"key": g["key"], "ok": g["ok"], "value": g["value"]}
            for g in stats.get("gates", [])
        ],
        "rationale": (skill.rationale or "")[:500],
    }


def build_tool_file(skill: Any, manifest: dict[str, Any]) -> tuple[str, str]:
    """(chemin, contenu) du fichier core. Le content du skill est repris
    À L'IDENTIQUE — c'est la version éprouvée à l'usage qui gradue, pas
    une réécriture. Toute retouche se fait dans la PR, sous revue."""
    provenance = json.dumps(
        {k: manifest[k] for k in (
            "learned_skill_id", "origin_user", "graduated_at", "stats",
        )},
        ensure_ascii=False, indent=2,
    )
    provenance_block = "\n".join(
        f"# {line}" for line in provenance.splitlines()
    )
    header = (
        "# =============================================================================\n"
        "# @project    ELY — Exactly Like You\n"
        f"# @file       {graduated_tool_path(skill.name)[len('backend/'):]}\n"
        f"# @brief      Tool gradué — généré par Ely, éprouvé à l'usage, converti\n"
        "#             en code core par le pipeline de graduation (Sprint 4d V4).\n"
        "#\n"
        "# @author     Ely (auto-developing agent) — revue humaine via PR\n"
        "# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved\n"
        "# @license    Elastic License 2.0\n"
        "#\n"
        "# PROVENANCE (gates au moment de la graduation) :\n"
        f"{provenance_block}\n"
        "# =============================================================================\n"
    )
    content = (skill.content or "").lstrip("\n")
    return graduated_tool_path(skill.name), f"{header}{content}\n"


def build_test_file(skill: Any, smoke_kwargs: dict | None) -> tuple[str, str]:
    """(chemin, contenu) du test pytest livré dans la MÊME PR — la CI de la
    PR de graduation exécute donc le tool avant tout merge."""
    slug = _slug(skill.name)
    module = f"app.agent.tools.graduated.{slug}_tool"
    invoke_block = ""
    if smoke_kwargs:
        kwargs_repr = json.dumps(smoke_kwargs, ensure_ascii=False)
        invoke_block = f'''

def test_{slug}_smoke_invocation():
    """Invocation réelle avec les smoke kwargs fournis à la graduation —
    le contrat minimal : ne lève pas, retourne une valeur non vide."""
    tool = _load_tool()
    result = tool.invoke(json.loads({kwargs_repr!r}))
    assert result is not None and str(result).strip() != ""
'''
    content = f'''# =============================================================================
# @project    ELY — Exactly Like You
# @file       tests/test_graduated_{slug}.py
# @brief      Pin de graduation — généré avec le tool (Sprint 4d V4).
# @license    Elastic License 2.0
# =============================================================================
"""Pin du tool gradué ``{skill.name}`` : importable, bindable, stable."""
from __future__ import annotations

import importlib
import json


def _load_tool():
    module = importlib.import_module("{module}")
    tool = getattr(module, "{skill.name}", None)
    assert tool is not None, "le module gradué doit exposer le tool"
    return tool


def test_{slug}_is_a_bindable_tool():
    tool = _load_tool()
    # StructuredTool LangChain : nom stable + docstring (le LLM en dépend).
    assert tool.name == "{skill.name}"
    assert (tool.description or "").strip() != ""


def test_{slug}_module_has_provenance_header():
    import inspect
    module = importlib.import_module("{module}")
    source = inspect.getsource(module)
    assert "PROVENANCE" in source and "@register" in source
{invoke_block}'''
    return graduated_test_path(skill.name), content


# ─────────────────────────────────────────────────────────────────────────
# Vérifications dry-run
# ─────────────────────────────────────────────────────────────────────────


def scan_composition_deps(source: str) -> dict[str, Any]:
    """Chaque ``call_tool("x")`` du content doit viser un tool core
    EXISTANT et composable. Un learned tool ne peut pas en appeler un
    autre (call_tool ne résout que le registre core) — donc pas de graphe
    à ordonner en V1 : la gate est une simple vérification d'existence."""
    targets = sorted(set(_CALL_TOOL_RE.findall(source or "")))
    if not targets:
        return {"targets": [], "missing": [], "ok": True}
    try:
        from app.services.learning.learned_tool_dispatch import composable_tool_names
        available = composable_tool_names()
    except Exception:
        available = set()
    missing = [t for t in targets if t not in available]
    return {"targets": targets, "missing": missing, "ok": not missing}


async def dry_run_graduation(
    db: AsyncSession,
    skill: Any,
    *,
    smoke_kwargs: dict | None = None,
) -> dict[str, Any]:
    """Joue TOUTES les gates (J1 + revalidation + composition) et produit
    les artefacts sans rien livrer. C'est l'aperçu que l'UI (J3) montre et
    l'étape obligatoire avant la livraison PR (J5).

    ``ready`` = gates J1 OK + revalidation 7 étages OK + composition OK.
    """
    from app.services.learning.graduation import compute_graduation_stats
    from app.services.learning.tool_orchestrator import validate_tool_source

    stats = await compute_graduation_stats(db, skill)

    # Revalidation du jour — un content validé il y a des semaines doit
    # repasser les étages courants (code_guard durci entre-temps, etc.).
    # existing_names = registre core : le learned tool n'y est pas (il est
    # dynamique), donc pas de fausse collision avec lui-même.
    try:
        from app.skills.registry import get_skill_registry
        existing = frozenset(get_skill_registry().all_tool_names())
    except Exception:
        existing = frozenset()
    report = validate_tool_source(
        skill.content or "",
        existing_names=existing,
        run_smoke=smoke_kwargs is not None,
        smoke_kwargs=smoke_kwargs,
        profile=getattr(skill, "tool_profile", "pure") or "pure",
    )

    composition = scan_composition_deps(skill.content or "")

    manifest = build_manifest(skill, stats)
    tool_path, tool_content = build_tool_file(skill, manifest)
    test_path, test_content = build_test_file(skill, smoke_kwargs)

    files = [
        {"path": f"{GRADUATED_PKG_DIR}/__init__.py", "content": _INIT_PY,
         "create_only": True},  # jamais écrasé s'il existe déjà (J5)
        {"path": tool_path, "content": tool_content, "create_only": False},
        {"path": test_path, "content": test_content, "create_only": False},
    ]

    ready = bool(stats["eligible"]) and bool(report.ok) and composition["ok"]
    return {
        "ready": ready,
        "graduation": stats,
        "revalidation": {
            "ok": bool(report.ok),
            "failed_stage": getattr(report, "failed_stage", None),
        },
        "composition": composition,
        "manifest": manifest,
        "files": files,
    }
