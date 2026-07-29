# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tool_creator.py
# @brief      Sprint 4b V2 J6c — generate→validate→iterate→persist loop for
#             auto-developed Python @tool skills.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""The V2 analog of ``skill_creator`` (design note J0).

Ties the generator (``tool_generator``) and the validation chain
(``tool_orchestrator``) into one self-correcting loop:

    generate → validate (5 stages) → if it fails, feed the exact failure
    back into the generator → retry, up to ``max_iterations`` → on success,
    persist a ``LearnedSkill(content_format=python_tool, status=candidate)``
    carrying the full validation report.

It NEVER auto-activates anything: the output is always a ``candidate``
awaiting HITL admin promotion (which, plus the live bind, is J7). The
tier-S model is whatever the ``skill`` tier of the admin routing config
selects (Paramètres → Routage, niveau « S » — see tool_generator).

``smoke_kwargs`` is an optional sample input for stage 4; when absent the
smoke stage is skipped (we can't call the function without arguments).
The trigger source (a failure_case / admin request) should supply one.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update

from app.database import async_session
from app.models.failure_case import FailureCase
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
from app.services.learning.tool_generator import generate_tool_source
from app.services.learning.tool_orchestrator import validate_tool_source

logger = logging.getLogger(__name__)

# Generator statuses that won't improve on retry — stop the loop.
_TERMINAL_GEN_STATUSES = {"no_provider", "llm_call_failed"}


def _existing_tool_names() -> set[str]:
    """Names of all registered tools — for the collision check. Best-effort."""
    try:
        from app.skills.registry import get_skill_registry

        return set(get_skill_registry().all_tool_names())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("tool_creator: registry name lookup failed (%s)", exc)
        return set()


async def _vault_labels_best_effort(user_id: str) -> list[str]:
    """Labels Vault du user pour le prompt io (J7). [] sur toute erreur —
    le prompt dégrade en « aucun label provisionné »."""
    try:
        from app.services.vault_service import get_vault_service
        entries = await get_vault_service().list_secrets(user_id)
        return sorted({
            (e.get("label") if isinstance(e, dict) else getattr(e, "label", None))
            for e in entries
        } - {None})
    except Exception as exc:  # noqa: BLE001
        logger.debug("tool_creator: vault labels unavailable (%s)", exc)
        return []


async def _mark_failure_cases_processed(
    case_ids: list[int] | None,
    skill_id: str,
) -> None:
    """C4-3.4 — close the loop: a successful generation stamps its source
    failure_cases ``processed_at`` + ``learned_skill_id`` (they otherwise
    linger « open » in Capacités manquantes forever — gaps #101/#102).

    Separate best-effort transaction AFTER the candidate commit: a marking
    failure must never lose the generated skill (worst case the gap stays
    open, which is the pre-C4-3 status quo). Never raises.
    """
    if not case_ids or not skill_id:
        return
    try:
        async with async_session() as db:
            result = await db.execute(
                update(FailureCase)
                .where(
                    FailureCase.id.in_(case_ids),
                    FailureCase.processed_at.is_(None),
                )
                .values(
                    processed_at=datetime.now(timezone.utc),
                    learned_skill_id=skill_id,
                )
            )
            await db.commit()
        logger.info(
            "tool_creator: marked %d failure_case(s) processed → skill %s",
            result.rowcount, skill_id,
        )
    except Exception as exc:  # noqa: BLE001 — le marquage est best-effort
        logger.warning(
            "tool_creator: failed to mark failure_cases %s processed (%s)",
            case_ids, exc,
        )


async def generate_and_persist_tool(
    *,
    task_description: str,
    user_id: str,
    smoke_kwargs: dict | None = None,
    max_iterations: int = 3,
    existing_names: set[str] | None = None,
    from_failure_case_ids: list[int] | None = None,
    profile: str = "pure",
) -> dict[str, Any]:
    """Run the generate→validate→iterate→persist loop once.

    Returns a summary dict ::

        {
          "status": "created" | "validation_failed" | "no_provider" | "error",
          "tool_name": "...",            # when created
          "learned_skill_id": "...",     # when created
          "iterations": 2,
          "attempts": [ {iteration, gen_status, validation} , ... ],
        }

    Best-effort: never raises. On success, persists a candidate skill.
    """
    if not user_id:
        return {"status": "error", "error": "user_id is required", "attempts": []}

    if profile not in ("pure", "io"):
        return {
            "status": "error",
            "error": f"unknown profile {profile!r} (pure | io)",
            "attempts": [],
        }

    max_iterations = max(1, min(int(max_iterations or 1), 5))
    names = existing_names if existing_names is not None else _existing_tool_names()
    run_smoke = smoke_kwargs is not None

    # Contexte io (J7) : la source de vérité egress (Squid) + les labels
    # Vault réellement provisionnés pour ce user — le modèle ne déclare
    # que ce qui existe.
    allowed_egress: list[str] | None = None
    secret_labels: list[str] | None = None
    if profile == "io":
        from app.services.learning.v3_declarations import squid_allowed_domains
        allowed_egress = squid_allowed_domains()
        secret_labels = await _vault_labels_best_effort(user_id)

    attempts: list[dict[str, Any]] = []
    prior_errors: str | None = None

    # Les passes locales d'abord, puis UNE seule au repli cloud du niveau S.
    #
    # Règle de Franck (29/07/2026) : « le modèle local crée l'outil, Ely le
    # teste et s'il est fonctionnel on s'arrête ; s'il ne l'est pas, là on fait
    # appel au fallback du tier S qui est kimi-k3 ».
    #
    # Avant ce lot, les trois itérations tournaient toutes sur le MÊME modèle
    # local, et on abandonnait — alors que `kimi-k3` était configuré juste
    # derrière lui et n'était jamais sollicité.
    #
    # Une seule passe cloud : si trois passes locales n'ont pas produit un
    # outil valide, une quatrième locale ne le ferait pas davantage — mais
    # payer plusieurs passes cloud non plus.
    passes = [False] * max_iterations + [True]

    for i, use_fallback in enumerate(passes, start=1):
        source, gen_info = await generate_tool_source(
            task_description=task_description,
            user_id=user_id,
            prior_errors=prior_errors,
            profile=profile,
            allowed_egress=allowed_egress,
            available_secret_labels=secret_labels,
            force_fallback=use_fallback,
        )
        attempt: dict[str, Any] = {"iteration": i, "gen_status": gen_info.get("status")}

        if source is None:
            attempt["error"] = gen_info.get("error") or gen_info.get("raw_excerpt", "")
            attempts.append(attempt)
            if gen_info.get("status") in _TERMINAL_GEN_STATUSES:
                return {
                    "status": gen_info.get("status"),
                    "iterations": i,
                    "attempts": attempts,
                }
            # parse failure → nudge and retry
            prior_errors = "Your reply did not contain a valid Python code block."
            continue

        report = validate_tool_source(
            source,
            existing_names=names,
            smoke_kwargs=smoke_kwargs,
            run_smoke=run_smoke,
            profile=profile,
        )
        attempt["validation"] = report.summary()
        attempt["tool_name"] = report.tool_name
        attempts.append(attempt)

        if not report.ok:
            prior_errors = report.summary()
            continue

        # ── Gate secrets async (J7) — hors chaîne sync de J5 ───────────
        # Un label déclaré mais non provisionné n'est PAS réparable par le
        # modèle (c'est un acte admin) : on retente UNE reformulation en
        # listant les labels réellement disponibles, et si le besoin
        # persiste on persiste quand même le candidat — la revue J8
        # affiche les labels manquants et le bind-time gate (J6.c.1)
        # tiendra l'outil hors du LLM tant que le Vault n'est pas prêt.
        if profile == "io":
            from app.services.learning.v3_declarations import (
                check_secrets_exist,
                parse_v3_declarations,
            )
            decls = parse_v3_declarations(source)
            gate = await check_secrets_exist(decls, user_id=user_id)
            attempt["secrets_gate"] = gate.summary()
            if not gate.ok and i < max_iterations:
                prior_errors = (
                    f"requires_secrets references unprovisioned Vault labels "
                    f"({gate.summary()}). Use ONLY labels from the AVAILABLE "
                    f"VAULT SECRET LABELS list, or drop the secret if the API "
                    f"works without it."
                )
                continue

        # ── success → persist a candidate ──────────────────────────────
        from app.models.learned_skill import SkillToolProfile
        skill = LearnedSkill(
            user_id=user_id,
            name=(report.tool_name or "generated_tool")[:64],
            description=task_description.strip()[:1024],
            content=source,
            content_format=SkillContentFormat.PYTHON_TOOL,
            tool_profile=(
                SkillToolProfile.IO if profile == "io" else SkillToolProfile.PURE
            ),
            frontmatter_json=json.dumps(
                {"tool_name": report.tool_name, "provider": gen_info.get("provider_pick")},
                ensure_ascii=False,
            ),
            validation_report_json=report.to_json(),
            status=SkillStatus.CANDIDATE,
            source=SkillSource.AUTO_GENERATED,
            iteration_count=i,
            from_failure_case_ids=json.dumps(from_failure_case_ids or [], ensure_ascii=False),
            rationale=(
                f"Auto-generated python_tool for: {task_description.strip()[:300]} "
                f"(validated through {i} iteration(s), provider={gen_info.get('provider_pick')})."
            ),
        )
        async with async_session() as db:
            db.add(skill)
            await db.flush()
            skill_id = skill.id
            await db.commit()
        logger.info(
            "tool_creator: created candidate python_tool %s (%s) in %d iteration(s)",
            skill_id, report.tool_name, i,
        )
        await _mark_failure_cases_processed(from_failure_case_ids, skill_id)
        return {
            "status": "created",
            "tool_name": report.tool_name,
            "learned_skill_id": skill_id,
            "iterations": i,
            "attempts": attempts,
        }

    # exhausted without a passing candidate
    return {
        "status": "validation_failed",
        "iterations": len(attempts),
        "attempts": attempts,
    }
