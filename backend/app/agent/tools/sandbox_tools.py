"""Reusable, user-owned computation tools, always executed in a subprocess.

The agent writes a run(arguments) function and examples with expected results.
Only tested versions are saved, immutably. Nothing is imported into the server
or given credentials. New I/O integrations still use the existing codegen gates.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool
from sqlalchemy import select

from app.agent.tools.python_tool import python_execute
from app.agent.tool_failure import dit_un_echec
from app.database import async_session
from app.models.learned_skill import LearnedSkill, SkillContentFormat, SkillSource, SkillStatus
from app.services.learning.code_guard import FORBIDDEN_CALLS, check_tool_source

_IMPORTS = frozenset({"math", "json", "re", "datetime", "statistics", "itertools", "collections", "decimal", "fractions", "functools", "string"})


def validate_program(source: str) -> str | None:
    if not source.strip() or len(source) > 12000:
        return "Le programme doit contenir de 1 à 12 000 caractères."
    report = check_tool_source(source, allowed_import_roots=_IMPORTS, allowed_import_exact=frozenset())
    if not report.ok:
        return report.summary()
    tree = ast.parse(source)
    # Reject aliases of dangerous builtins and traversal through stdlib
    # implementation details, not just direct calls such as open(...).
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            return f"Référence interdite : {node.id}."
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("_") or node.attr in FORBIDDEN_CALLS - {"compile"}
            or node.attr in {"os", "sys", "builtins", "modules", "import_module"}
        ):
            return f"Accès interdit : .{node.attr}."
        if isinstance(node, ast.Import) and any("." in alias.name for alias in node.names):
            return "Importe uniquement les modules publics autorisés."
        if isinstance(node, ast.ImportFrom) and (
            node.module not in _IMPORTS or any(alias.name.startswith("_") for alias in node.names)
        ):
            return "Import privé ou sous-module interdit."
    entry = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run"]
    if len(entry) != 1 or entry[0].decorator_list:
        return "Définis une fonction sans décorateur : run(arguments: dict), qui renvoie un résultat JSON."
    return None


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@tool
async def sandbox_save_tool(
    name: str, description: str, source: str, tests_json: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Créer, tester et mémoriser un outil de calcul immédiatement réutilisable.

    Écris une fonction Python run(arguments: dict) qui RENVOIE un résultat
    JSON. Aucun réseau, fichier ou appel d'outil : seulement calculs et
    transformations en mémoire. tests_json est une liste de 1 à 5 cas
    {"input": {...}, "expected": ...}, comprenant si possible un cas limite.
    L'outil est sauvegardé uniquement si tous les tests passent. Le nom
    versionné retourné s'utilise avec sandbox_run_tool. Pour agir sur Google,
    le navigateur ou le disque, compose ensuite les outils dédiés.
    """
    if not user_id:
        return "Erreur : utilisateur absent."
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,39}", name):
        return "Erreur : nom attendu en minuscules, 3 à 40 caractères (lettres, chiffres, _ ou -)."
    if not description.strip() or len(description) > 700:
        return "Erreur : description attendue, au maximum 700 caractères."
    error = validate_program(source)
    if error:
        return f"Erreur : programme refusé. {error}"
    try:
        if len(tests_json) > 16000:
            raise ValueError("tests trop volumineux")
        tests = json.loads(tests_json)
        if not isinstance(tests, list) or not 1 <= len(tests) <= 5:
            raise ValueError("1 à 5 tests requis")
        for case in tests:
            if not isinstance(case, dict) or not isinstance(case.get("input"), dict) or "expected" not in case:
                raise ValueError("chaque test contient input (objet) et expected")
        encoded = _json(tests)
    except (ValueError, TypeError) as exc:
        return f"Erreur : tests invalides ({exc})."
    marker = "ELY_TEST_OK_" + uuid.uuid4().hex
    harness = (
        source + "\nimport json as _ely_json\n"
        f"for _ely_case in _ely_json.loads({encoded!r}):\n"
        "    _ely_result = run(_ely_case['input'])\n"
        "    assert _ely_json.loads(_ely_json.dumps(_ely_result, allow_nan=False)) == _ely_case['expected'], 'Résultat différent du résultat attendu'\n"
        f"print({marker!r})\n"
    )
    result = await python_execute.ainvoke({"code": harness})
    if dit_un_echec(result) or marker not in result:
        return "Erreur : tests non validés, outil non enregistré. Corrige le programme.\n" + result[:3000]
    digest = hashlib.sha256((source + encoded).encode()).hexdigest()[:10]
    versioned = f"{name}-{digest}"
    async with async_session() as db:
        existing = (await db.execute(select(LearnedSkill.id).where(
            LearnedSkill.user_id == user_id, LearnedSkill.name == versioned,
        ))).first()
        if not existing:
            db.add(LearnedSkill(
                user_id=user_id, name=versioned,
                description=f"{description} — appeler sandbox_run_tool(name='{versioned}', arguments_json=...).",
                content=source, content_format=SkillContentFormat.SANDBOX_PROGRAM,
                status=SkillStatus.ACTIVE, source=SkillSource.AUTO_GENERATED,
                promoted_at=datetime.now(timezone.utc),
                validation_report_json=_json({"tests": tests, "passed": len(tests), "runtime": "sandbox"}),
            ))
            await db.commit()
    from app.agent.discovered_tools import add_discovered
    from app.agent.tool_context import CURRENT_CONVERSATION_ID
    add_discovered(CURRENT_CONVERSATION_ID.get(), ["sandbox_run_tool"])
    return f"Outil {versioned} enregistré pour cet utilisateur ; {len(tests)} test(s) réussi(s). Appelle sandbox_run_tool avec ce nom et tes arguments JSON."


@tool
async def sandbox_run_tool(
    name: str, arguments_json: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Exécuter un outil de calcul créé avec sandbox_save_tool, dans le bac à sable.

    name est le nom versionné retourné à la création (ou retrouvé avec
    find_tool / skill_view). arguments_json est l'objet JSON passé à run.
    Uniquement les programmes actifs de l'utilisateur courant ; aucune
    intégration externe et aucun secret n'est accessible au programme.
    """
    if not user_id:
        return "Erreur : utilisateur absent."
    try:
        if len(arguments_json) > 32000:
            raise ValueError("arguments trop volumineux")
        args = json.loads(arguments_json)
        if not isinstance(args, dict):
            raise ValueError("un objet JSON est requis")
        encoded = _json(args)
    except (ValueError, TypeError) as exc:
        return f"Erreur : arguments invalides ({exc})."
    async with async_session() as db:
        skill = (await db.execute(select(LearnedSkill).where(
            LearnedSkill.user_id == user_id, LearnedSkill.name == name,
            LearnedSkill.content_format == SkillContentFormat.SANDBOX_PROGRAM,
            LearnedSkill.status == SkillStatus.ACTIVE,
        ).limit(1))).scalar_one_or_none()
        if skill is None:
            return "Erreur : aucun outil de bac à sable actif sous ce nom pour cet utilisateur."
        source, skill_id = skill.content, skill.id
    error = validate_program(source)  # Revalidate even after database edits.
    if error:
        return f"Erreur : programme refusé. {error}"
    marker = "ELY_RESULT_" + uuid.uuid4().hex + ":"
    result = await python_execute.ainvoke({"code": source + (
        "\nimport json as _ely_json\n"
        f"print({marker!r} + _ely_json.dumps(run(_ely_json.loads({encoded!r})), ensure_ascii=False, allow_nan=False))\n"
    )})
    if dit_un_echec(result) or marker not in result:
        return "Erreur : exécution sans résultat exploitable.\n" + result[:3000]
    output = result.split(marker, 1)[1].splitlines()[0]
    try:
        json.loads(output)
    except ValueError:
        return "Erreur : résultat trop volumineux ou incomplet. Réduis le lot de données."
    from app.services.learning.active_skills import bump_skill_usage
    await bump_skill_usage(skill_id)
    return output
