# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_creator.py
# @brief      Sprint 4b Phase 3.a — autonomous skill (playbook) generator
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Skill creator — Sprint 4b Phase 3.a.

Reads ``failure_cases`` that haven't been turned into a skill yet,
clusters them by ``pattern_hash``, and asks the tier-S LLM (Opus 4.5
primary, DeepSeek pro fallback) to write a Markdown playbook that
would have prevented each cluster's failure pattern.

Pattern d'inspiration : Hermes ``tools/skill_manager_tool.py`` (action
``create``, SKILL.md format) + the prompt rationale in
``agent/prompt_builder.py:177-183``. Voir
docs/external-references/hermes-skills-self-improvement.md §5 Phase 3.

Public entry point
------------------
``run_skill_creator_batch(user_id, batch_size)`` — picks at most
``batch_size`` clusters of unprocessed failure_cases for ``user_id``,
drafts one ``LearnedSkill`` (status ``candidate``) per cluster, marks
the underlying failure_cases as ``processed_at = now``, and returns a
summary dict for the admin endpoint.

V1 limits (consciously narrow, expanded in Phases 3.b–5)
---------------------------------------------------------
- Only generates Markdown playbooks (not Python tools — V2)
- Does NOT evaluate the playbook (that's Phase 3.b ``skill_eval``)
- Does NOT promote anything to ``active`` (Phase 4 — HITL admin)
- Does NOT inject playbooks into the system prompt (also Phase 4)
- Default LLM is Opus 4.5 via tier S; budget cap from Phase 2 applies

The whole module is best-effort: a generation failure on one cluster
must not abort the batch. We log + skip + move on.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import async_session
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.learning.failure_capture import SIGNAL_TOOL_ABSENT
from app.services.learning.tier_s import (
    estimate_cost_usd,
    get_tier_s_llm,
    record_tier_s_usage,
)

logger = logging.getLogger(__name__)


# ── Prompts ─────────────────────────────────────────────────────────────────

# We split the prompt into a system message (stable, prompt-cacheable for
# Anthropic) and a user message (per-cluster, dynamic). Opus respects this
# split and bills the system portion at ~10 % after the first call.

_SYSTEM_PROMPT = """\
You are ELY's autonomous skill writer. ELY is a sovereign AI agent built
on FastAPI + LangGraph that runs Gmail / Calendar / Drive / Notes /
Tasks / browser tools for self-hosted users.

You are given ONE failure pattern (1 or more concrete failure cases that
share the same fingerprint) where the live agent got something wrong
recently: HITL refused, hallucinated success, or low-quality mission
critique. Your job is to write a SHORT Markdown PLAYBOOK that, if injected
into the agent's system prompt next time this pattern shows up, would
prevent the failure from happening again.

A playbook is procedural memory, not a tool. It tells the agent
"WHEN you see X, DO Y in this order, NEVER do Z". It is NOT code.

Strict output contract
----------------------
Reply with EXACTLY a fenced markdown block starting with `---` (YAML
frontmatter) and finishing with a procedure section. NO other text
before or after the fenced block. Schema:

```
---
name: kebab-case-slug-max-64-chars
description: One sentence ≤200 chars describing when this playbook applies.
tags: [list, of, 1-5, tags]
---

# Title (short noun phrase)

## When this applies
1-3 bullets describing the trigger pattern.

## Procedure
Numbered steps the agent must follow.

## What NOT to do
Bullets of forbidden moves (the actual failure modes from the cases).
```

Quality bar
-----------
- Concrete and actionable: name the EXACT tools from the AVAILABLE
  TOOLS list at the end of the user prompt. NEVER invent a tool name.
  If a needed tool is not in the list, write the procedure without it
  (e.g. "ask the user to do X manually") rather than inventing one.
- Defensive: when in doubt, propose asking the user before acting.
- Tight: < 300 words total. Token economy matters.
- Cite the failure modes verbatim when useful (1 short quote max).
- **Write the playbook in the SAME LANGUAGE as the source failure
  cases (look at quoted user-facing strings in the cases). The agent
  speaks both — match the user's working language.**
"""


def _format_failure_case_for_prompt(fc: FailureCase) -> str:
    """One compact paragraph per failure case for the user prompt."""
    payload = {}
    try:
        payload = json.loads(fc.replay_payload or "{}")
    except Exception:
        pass
    kind = payload.get("signal_kind", fc.signal_table)
    bits = [f"signal={kind}", f"tier_llm={fc.tier_llm or '?'}"]
    if "tool_name" in payload:
        bits.append(f"tool={payload['tool_name']}")
    if "decision" in payload:
        bits.append(f"decision={payload['decision']}")
    if "quality_score" in payload:
        bits.append(f"quality_score={payload['quality_score']}")
    if "honest_completion" in payload:
        bits.append(f"honest={payload['honest_completion']}")
    head = " | ".join(bits)

    extras: list[str] = []
    if payload.get("action_description"):
        extras.append(f"  Action that was refused: {payload['action_description']!r}")
    if payload.get("original_response"):
        extras.append(f"  Agent claimed: {payload['original_response']!r}")
    if payload.get("destructive_tools_invoked") is not None:
        dest = payload["destructive_tools_invoked"]
        dest_str = repr(dest) if dest else "(NONE — that is the failure)"
        extras.append(f"  Destructive tools actually called: {dest_str}")
    if payload.get("main_issue"):
        extras.append(f"  Critic main issue: {payload['main_issue']!r}")

    return f"- [case#{fc.id}] {head}\n" + "\n".join(extras)


def _get_available_tool_names(profile_name: str = "default") -> list[str]:
    """Return the names of every tool that's actually registered AND in
    the given toolset profile. Used to inject a ground-truth list into
    the writer/patcher prompts so the LLM doesn't invent tool names.

    Defensive: any import failure or registry hiccup returns an empty
    list — the writer prompt copes (it'll fall back to vague verbs,
    not crash).
    """
    try:
        from app.agent.toolset_profiles import (
            get_profile_tool_names,
            DEFAULT_PROFILE,
        )
        from app.skills.registry import get_skill_registry

        profile_names = set(get_profile_tool_names(profile_name or DEFAULT_PROFILE))
        registered_names = get_skill_registry().all_tool_names()
        # Intersection: only tools that are BOTH in the profile AND
        # actually registered. Sorted for prompt stability (cacheable).
        return sorted(profile_names & registered_names)
    except Exception as exc:
        logger.debug("skill_creator: tool names lookup failed (%s)", exc)
        return []


def _format_tool_list_for_prompt(tools: list[str]) -> str:
    """Render the tool names as a compact comma-separated list with a
    rough grouping by prefix so the LLM can spot the right family fast."""
    if not tools:
        return "(no tools available — the agent runs without bindable tools right now)"
    # Group by the first underscore-separated token (gmail_, drive_, etc.)
    groups: dict[str, list[str]] = {}
    for name in tools:
        prefix = name.split("_", 1)[0] if "_" in name else "misc"
        groups.setdefault(prefix, []).append(name)
    lines = [
        f"  {prefix}: {', '.join(sorted(names))}"
        for prefix, names in sorted(groups.items())
    ]
    return "\n".join(lines)


def _compose_user_prompt(cluster: list[FailureCase]) -> str:
    """User message for one cluster of similar failures."""
    head = f"Failure pattern (cluster fingerprint = {cluster[0].pattern_hash})\n"
    head += f"Number of cases in this cluster: {len(cluster)}\n\n"
    head += "Cases:\n"
    body = "\n\n".join(_format_failure_case_for_prompt(fc) for fc in cluster)

    tools = _get_available_tool_names()
    tool_section = (
        "\n\nAVAILABLE TOOLS (use ONLY these names in the playbook; "
        "inventing tool names is forbidden):\n"
        + _format_tool_list_for_prompt(tools)
    )
    tail = (
        "\n\nWrite the playbook now. Remember: ONLY the fenced markdown "
        "block with YAML frontmatter, no other text. Use only the tools "
        "in the AVAILABLE TOOLS list above. Write in the same language "
        "as the quoted strings in the failure cases."
    )
    return head + body + tool_section + tail


# ── Output parser ───────────────────────────────────────────────────────────


def parse_playbook_response(raw: str) -> dict[str, Any] | None:
    """Parse the tier-S response into (frontmatter dict, body markdown).

    Tolerant: accepts the playbook with or without surrounding fences,
    with or without a leading prose paragraph (we strip up to the first
    ``---``). Returns None on shape failure — the caller logs + skips.
    """
    if not raw:
        return None
    text = raw.strip()

    # Strip ```markdown / ``` fences if present
    if text.startswith("```"):
        # take everything between the first and last fence
        first_nl = text.find("\n")
        if first_nl < 0:
            return None
        text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()

    if not text.startswith("---"):
        # Maybe the model wrapped it in prose — find the frontmatter start
        idx = text.find("\n---\n")
        if idx < 0:
            idx = text.find("---")
            if idx < 0:
                return None
            text = text[idx:]
        else:
            text = text[idx + 1:]

    # Split frontmatter from body
    after = text[3:]  # strip leading ---
    end = after.find("\n---")
    if end < 0:
        return None
    fm_block = after[:end].strip()
    body = after[end + 4:].lstrip("\n").strip()

    # Parse frontmatter — accept YAML via yaml lib OR fall back to k:v
    try:
        import yaml  # type: ignore
        fm = yaml.safe_load(fm_block) or {}
        if not isinstance(fm, dict):
            return None
    except ImportError:
        fm = {}
        for line in fm_block.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()

    name = str(fm.get("name", "")).strip()
    description = str(fm.get("description", "")).strip()
    if not name or not description:
        return None

    return {
        "name": name[:64],
        "description": description[:1024],
        "frontmatter": fm,
        "body": body,
    }


# ── Public API ──────────────────────────────────────────────────────────────


def _motif_deja_pourvu(user_id: str):
    """EXISTS corrélé : une procédure interdit déjà d'en écrire une pour ce motif.

    Miroir exact des deux gardes (``procedure_perimee_pour_ce_motif`` et
    ``candidate_en_attente_pour_ce_motif``), écrit en une sous-requête pour
    que le lot puisse écarter ces motifs SANS les charger.
    """
    procedure = aliased(LearnedSkill)
    source = aliased(FailureCase)
    return (
        select(1)
        .select_from(source)
        .join(procedure, source.learned_skill_id == procedure.id)
        .where(
            source.pattern_hash == FailureCase.pattern_hash,
            procedure.user_id == user_id,
            or_(
                procedure.status == SkillStatus.CANDIDATE,
                and_(
                    procedure.status.in_({SkillStatus.STALE, SkillStatus.ARCHIVED}),
                    procedure.use_count == 0,
                    procedure.pinned.is_(False),
                ),
            ),
        )
        .correlate(FailureCase)
        .exists()
    )


async def _fetch_unprocessed_cases(
    db: AsyncSession, user_id: str, batch_size: int,
) -> list[list[FailureCase]]:
    """Pick top N clusters of unprocessed failure_cases for the user.

    Sorting heuristic V1 : the cluster with the MOST recent activity
    first, then by case count. Cap at ``batch_size`` clusters.

    ⚠️ LES MANQUES DÉJÀ POURVUS N'ENTRENT PAS (02/09/2026). Un
    ``tool_absent`` dont le motif a déjà une procédure ne peut rien produire
    ici — et le lot ne peut pas non plus le classer (ce serait le sortir de
    « Capacités manquantes » sans rien écrire en échange, cf.
    ``_classer_sans_rediger``). Laissé dans la fenêtre, il occuperait une des
    N places à chaque tick de ``learned_skills_autocreate``, toutes les
    30 minutes, pour toujours. On l'écarte à la source.
    """
    result = await db.execute(
        select(FailureCase)
        .where(
            FailureCase.user_id == user_id,
            FailureCase.processed_at.is_(None),
            FailureCase.pattern_hash.is_not(None),
            or_(
                FailureCase.signal_table != SIGNAL_TOOL_ABSENT,
                ~_motif_deja_pourvu(user_id),
            ),
        )
        .order_by(FailureCase.created_at.desc())
        .limit(200)  # window — never more than 200 rows
    )
    rows = result.scalars().all()
    if not rows:
        return []

    # Group by pattern_hash, preserving insertion order
    clusters: dict[str, list[FailureCase]] = {}
    for fc in rows:
        clusters.setdefault(fc.pattern_hash, []).append(fc)

    # Sort clusters: by latest case timestamp desc, then by size desc
    sorted_clusters = sorted(
        clusters.values(),
        key=lambda c: (max(fc.created_at for fc in c), len(c)),
        reverse=True,
    )
    return sorted_clusters[:batch_size]


async def _draft_skill_for_cluster(
    cluster: list[FailureCase],
    user_id: str,
) -> tuple[LearnedSkill | None, dict[str, Any]]:
    """Ask tier-S to write a playbook for one cluster of cases.

    Returns ``(skill_row, info_dict)``. ``skill_row`` is the unflushed
    ``LearnedSkill`` object ready to ``db.add``; None on any failure.
    ``info_dict`` carries the picked provider, raw response (truncated),
    and a status string for the admin endpoint's response.
    """
    info: dict[str, Any] = {
        "cluster_size": len(cluster),
        "pattern_hash": cluster[0].pattern_hash,
        "case_ids": [fc.id for fc in cluster],
        "status": "pending",
    }

    llm, pick = await get_tier_s_llm()
    if llm is None or pick == "none":
        info["status"] = "no_provider"
        info["error"] = "No tier-S provider configured (Anthropic + DeepSeek both absent)."
        return None, info
    info["provider_pick"] = pick

    # Call the LLM
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        user_prompt = _compose_user_prompt(cluster)
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = await llm.ainvoke(messages)
        raw = getattr(response, "content", "") or ""
    except Exception as exc:
        info["status"] = "llm_call_failed"
        info["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "skill_creator: tier-S call failed (%s): %s",
            info["pattern_hash"], exc,
        )
        return None, info

    # Best-effort usage accounting — read .usage_metadata when present
    in_tokens = out_tokens = 0
    model_name = ""
    try:
        usage_meta = getattr(response, "usage_metadata", None) or {}
        in_tokens = int(usage_meta.get("input_tokens") or 0)
        out_tokens = int(usage_meta.get("output_tokens") or 0)
        model_name = getattr(response, "response_metadata", {}).get("model_name") or ""
        if not model_name:
            model_name = (
                getattr(llm, "model", None)
                or getattr(llm, "model_name", None)
                or "tier-s"
            )
    except Exception:
        pass

    if in_tokens or out_tokens:
        await record_tier_s_usage(
            user_id=user_id,
            model=model_name,
            # Backlog #19 : `pick` is now the canonical provider name
            # ("anthropic" / "mistral" / "deepseek"), pass through.
            provider=pick,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            purpose="skill_creator",
        )
        info["tokens_in"] = in_tokens
        info["tokens_out"] = out_tokens
        info["estimated_cost_usd"] = estimate_cost_usd(model_name, in_tokens, out_tokens)

    # Parse response
    parsed = parse_playbook_response(raw)
    if parsed is None:
        info["status"] = "parse_failed"
        info["raw_excerpt"] = raw[:300]
        logger.warning(
            "skill_creator: tier-S response did not parse — pattern_hash=%s "
            "first 200 chars: %s",
            info["pattern_hash"], raw[:200],
        )
        return None, info

    # Build the LearnedSkill row (NOT committed here — caller commits)
    skill = LearnedSkill(
        user_id=user_id,
        name=parsed["name"],
        description=parsed["description"],
        content=parsed["body"],
        frontmatter_json=json.dumps(parsed["frontmatter"], ensure_ascii=False),
        status=SkillStatus.CANDIDATE,
        source=SkillSource.AUTO_GENERATED,
        iteration_count=1,
        from_failure_case_ids=json.dumps(
            info["case_ids"], ensure_ascii=False,
        ),
        rationale=(
            f"Auto-generated by skill_creator from {len(cluster)} failure cases "
            f"(pattern {info['pattern_hash']}). Cases: {info['case_ids']}."
        ),
    )
    info["status"] = "drafted"
    info["skill_name"] = parsed["name"]
    return skill, info


async def procedure_perimee_pour_ce_motif(
    db: AsyncSession, user_id: str, pattern_hash: str | None,
) -> str | None:
    """Nom d'une procédure déjà écrite pour ce motif, morte SANS avoir servi.

    ⚠️ LA BOUCLE QUI A PRODUIT LE STOCK (audit 02/09/2026).

        98 compétences apprises — dont 43 PÉRIMÉES, 13 archivées

    Le curateur fait passer ``active → stale → archived`` ce qui ne sert pas,
    mais rien n'empêchait le rédacteur de réécrire, pour le MÊME
    ``pattern_hash``, la jumelle de celle qui venait de périmer sans avoir
    servi une seule fois. Un motif qui se reproduit relançait donc la roue :
    nouveau cas → nouveau lot → nouvelle procédure → nouvelle péremption, et
    du tier-S dépensé à chaque tour.

    ``use_count > 0`` désarme le garde : une procédure périmée APRÈS avoir
    servi prouve que le motif se couvre par un document — elle mérite d'être
    réécrite. ``pinned`` aussi : l'utilisateur a dit de la garder.

    Ne supprime rien : les procédures périmées appartiennent à l'utilisateur.
    """
    if not pattern_hash:
        return None
    return (await db.execute(
        select(LearnedSkill.name)
        .join(FailureCase, FailureCase.learned_skill_id == LearnedSkill.id)
        .where(
            FailureCase.pattern_hash == pattern_hash,
            LearnedSkill.user_id == user_id,
            LearnedSkill.status.in_({SkillStatus.STALE, SkillStatus.ARCHIVED}),
            LearnedSkill.use_count == 0,
            LearnedSkill.pinned.is_(False),
        )
        .limit(1)
    )).scalar_one_or_none()


async def candidate_en_attente_pour_ce_motif(
    db: AsyncSession, user_id: str, pattern_hash: str | None,
) -> str | None:
    """Nom d'une procédure CANDIDATE déjà écrite pour ce motif, non tranchée.

    ⚠️ LE TROU QUE LE GARDE « PÉRIMÉE » LAISSAIT OUVERT (02/09/2026).

    ``procedure_perimee_pour_ce_motif`` ne voit que ``stale`` et ``archived``,
    et ``skill_curator`` ne fait transiter que ``active → stale → archived`` :
    une CANDIDATE jamais validée ne devient donc JAMAIS périmée. Or la
    fabrique gelée écrit une candidate à chaque manque et pose
    ``processed_at`` — à la récurrence suivante, ``record_tool_absent`` (qui
    ne dédoublonne que sur les cas NON traités) consigne un cas neuf, et une
    seconde procédure partait pour le même motif sans qu'aucun garde ne la
    voie. Tant que l'humain ne tranchait pas, geler la fabrique MULTIPLIAIT
    les procédures au lieu de les remplacer.

    Pas de seuil d'âge : ce qui bloque n'est pas l'ancienneté, c'est la
    décision qui manque. ``rejected`` ne bloque pas (le motif redevient
    rédigeable), ``active`` non plus (le motif est couvert et servi).
    """
    if not pattern_hash:
        return None
    return (await db.execute(
        select(LearnedSkill.name)
        .join(FailureCase, FailureCase.learned_skill_id == LearnedSkill.id)
        .where(
            FailureCase.pattern_hash == pattern_hash,
            LearnedSkill.user_id == user_id,
            LearnedSkill.status == SkillStatus.CANDIDATE,
        )
        .limit(1)
    )).scalar_one_or_none()


async def _classer_sans_rediger(cluster: list[FailureCase], motif: str) -> list[int]:
    """Marque des cas traités sans écrire de procédure. Rend les cas classés.

    Sans ce marquage, le lot représenterait le même motif à chaque tick et
    occuperait la place d'un motif jamais vu (le lot prend les N grappes les
    plus récentes).

    ⚠️ JAMAIS UN ``tool_absent`` (02/09/2026). Les lignes de cette famille
    SONT la vue « Capacités manquantes » (``signal_table == 'tool_absent'``
    + ``processed_at IS NULL``, cf. ``routers/learning_skills.py``) : les
    classer les sortirait de l'écran où l'utilisateur garde la main, sans
    rien écrire en échange — ni procédure, ni ``learned_skill_id``, ni motif.
    C'est la règle déjà tenue par ``draft_playbook_for_gap`` ; le lot
    nocturne la partage, et ``_fetch_unprocessed_cases`` les écarte à la
    source pour qu'ils n'occupent pas non plus une place.

    ⚠️ Ce filtre DOUBLE celui de la source : aujourd'hui aucune grappe du lot
    ne peut plus contenir un ``tool_absent`` pourvu. Ne pas le lire comme du
    code mort — les deux gardes se masquaient mutuellement, et retirer l'un
    laissait la suite verte. ``test_le_classement_nocturne_epargne_un_manque_
    dans_une_grappe_mixte`` exerce celui-ci directement, pour qu'il ne parte
    pas sans qu'un test le dise.
    """
    case_ids = [fc.id for fc in cluster if fc.signal_table != SIGNAL_TOOL_ABSENT]
    if not case_ids:
        return []
    async with async_session() as db:
        await db.execute(
            update(FailureCase)
            .where(FailureCase.id.in_(case_ids))
            .values(processed_at=datetime.now(timezone.utc))
        )
        await db.commit()
    logger.info(
        "skill_creator: motif déjà couvert par la procédure %r — "
        "%d cas classés sans réécriture", motif, len(case_ids),
    )
    return case_ids


async def draft_playbook_for_gap(case_id: int, user_id: str) -> dict[str, Any]:
    """Un playbook pour CE manque précis, tout de suite.

    ⚠️ LA BRANCHE MORTE DE L'AIGUILLAGE (24/08).

    `auto_tool_generation` pose la bonne question depuis le 29/07 — règle de
    Franck : « soit la demande peut être réglée par un modèle et dans ce cas
    ce n'est pas un outil qu'il faut mais une skill ; soit elle nécessite une
    ou plusieurs ACTIONS et là il faut un outil. » Le juge `needs_a_tool`
    tranche correctement.

    Mais quand il répondait « compétence », la fonction faisait `return None`.
    **Elle ne créait rien.** Le manque restait consigné dans « Capacités
    manquantes » et personne n'écrivait la procédure qui l'aurait comblé. La
    moitié « outil » de l'aiguillage était branchée ; la moitié « compétence »
    ne menait nulle part.

    C'est précisément le modèle d'Hermes appliqué à Ely : une capacité
    nouvelle devient un **document** (`markdown_playbook`, format `SKILL.md`),
    pas un outil. Un playbook coûte des caractères de prompt, plafonnés par
    `PLAYBOOK_CONTENT_BUDGET_CHARS` ; un outil coûte un schéma JSON à CHAQUE
    tour, pour toujours. C'est la différence entre une croissance bornée et
    une croissance linéaire.

    ⚠️ Chemin distinct de `run_skill_creator_batch`, qui regroupe les cas par
    `pattern_hash` et tourne en lot. Ici on tient un cas unique et fraîchement
    consigné : on le traite en grappe de un, avec le MÊME rédacteur et la même
    persistance — pas un second prompt qui dériverait du premier.

    Ne lève jamais : un playbook non écrit ne doit pas casser le tour qui l'a
    révélé.
    """
    info: dict[str, Any] = {"case_id": case_id, "status": "pending"}
    if not case_id or not user_id:
        info["status"] = "invalid_input"
        return info

    try:
        async with async_session() as db:
            fc = (await db.execute(
                select(FailureCase).where(
                    FailureCase.id == case_id,
                    FailureCase.user_id == user_id,
                )
            )).scalar_one_or_none()

        if fc is None:
            info["status"] = "case_not_found"
            return info
        if fc.processed_at is not None:
            # Déjà couvert par le lot nocturne ou par un tour précédent.
            # Réécrire produirait un doublon que le curateur devrait trier.
            info["status"] = "already_processed"
            return info

        async with async_session() as db:
            perimee = await procedure_perimee_pour_ce_motif(
                db, user_id, fc.pattern_hash,
            )
        if perimee:
            # ⚠️ ON NE CLASSE PAS LE CAS ICI (02/09/2026).
            #
            # Le classement sert au lot NOCTURNE : il l'empêche de re-occuper
            # une de ses N places avec le même motif. Sur le chemin du manque,
            # il n'y a pas de place à protéger — et il coûtait cher : le cas
            # sortait de la vue par défaut des « Capacités manquantes »
            # (`processed_at IS NULL`) sans qu'aucune procédure ne le comble.
            # Le manque disparaissait de l'écran où l'utilisateur garde la
            # main, définitivement : un motif dont la première procédure est
            # morte à zéro usage ne serait plus jamais ni rédigé ni montré.
            #
            # Les reprises sont déjà bornées ailleurs : `record_tool_absent`
            # dédoublonne sur les cas NON traités (le même manque rend le même
            # `case_id`) et `_attempted_cases` interdit une seconde tentative
            # dans le même boot.
            logger.info(
                "skill_creator: manque #%s — motif déjà couvert par la "
                "procédure périmée %r, pas de réécriture ; le cas reste "
                "ouvert dans « Capacités manquantes »", case_id, perimee,
            )
            info["status"] = "deja_perimee"
            info["procedure_perimee"] = perimee
            return info

        async with async_session() as db:
            en_attente = await candidate_en_attente_pour_ce_motif(
                db, user_id, fc.pattern_hash,
            )
        if en_attente:
            # Une procédure attend déjà une décision humaine pour ce motif :
            # en écrire une seconde ne comble rien, ça ajoute une ligne de
            # plus à trancher. Le cas reste ouvert — la main est à l'humain,
            # et c'est en validant la candidate qu'il la lui rend.
            logger.info(
                "skill_creator: manque #%s — la procédure %r attend déjà une "
                "décision pour ce motif, pas de seconde rédaction",
                case_id, en_attente,
            )
            info["status"] = "candidate_en_attente"
            info["procedure_en_attente"] = en_attente
            return info

        skill, draft = await _draft_skill_for_cluster([fc], user_id)
        info.update(draft)
        if skill is None:
            return info

        now = datetime.now(timezone.utc)
        async with async_session() as db:
            db.add(skill)
            await db.flush()
            await db.execute(
                update(FailureCase)
                .where(FailureCase.id == case_id)
                .values(processed_at=now, learned_skill_id=skill.id)
            )
            await db.commit()
            info["learned_skill_id"] = skill.id
            info["skill_name"] = skill.name
            info["status"] = "drafted"
            logger.info(
                "skill_creator: playbook candidate %s (%s) écrit pour le manque #%s",
                skill.id, skill.name, case_id,
            )
        return info
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning(
            "skill_creator: playbook non écrit pour le manque #%s (%s)", case_id, exc,
        )
        info["status"] = "error"
        info["error"] = str(exc)[:200]
        return info


async def run_skill_creator_batch(
    *,
    user_id: str,
    batch_size: int = 3,
) -> dict[str, Any]:
    """Run one batch of skill generation for ``user_id``.

    Returns ::

        {
          "user_id": "...",
          "batch_size": 3,
          "clusters_processed": 2,
          "drafts": [
            {"status": "drafted", "skill_name": "...", ...},
            {"status": "parse_failed", "raw_excerpt": "...", ...},
          ],
          "skills_created": 1,
        }

    Best-effort: a per-cluster failure logs + moves on, never aborts the
    batch. Empty input → empty result with zero counts.
    """
    if not user_id:
        return {"error": "user_id is required", "skills_created": 0, "drafts": []}
    batch_size = max(1, min(int(batch_size or 1), 10))

    summary: dict[str, Any] = {
        "user_id": user_id,
        "batch_size": batch_size,
        "clusters_processed": 0,
        "drafts": [],
        "skills_created": 0,
    }

    async with async_session() as db:
        clusters = await _fetch_unprocessed_cases(db, user_id, batch_size)

    if not clusters:
        return summary

    now = datetime.now(timezone.utc)
    for cluster in clusters:
        summary["clusters_processed"] += 1

        # Ce motif a-t-il déjà une procédure qui interdit d'en écrire une
        # seconde ? (02/09) Deux formes : morte sans avoir servi, ou candidate
        # qui attend encore une décision humaine.
        async with async_session() as db:
            perimee = await procedure_perimee_pour_ce_motif(
                db, user_id, cluster[0].pattern_hash,
            )
            en_attente = (
                None if perimee
                else await candidate_en_attente_pour_ce_motif(
                    db, user_id, cluster[0].pattern_hash,
                )
            )
        if perimee or en_attente:
            await _classer_sans_rediger(cluster, perimee or en_attente)
            summary["drafts"].append({
                "status": "deja_perimee" if perimee else "candidate_en_attente",
                "pattern_hash": cluster[0].pattern_hash,
                "case_ids": [fc.id for fc in cluster],
                ("procedure_perimee" if perimee else "procedure_en_attente"):
                    perimee or en_attente,
            })
            continue

        skill, info = await _draft_skill_for_cluster(cluster, user_id)
        summary["drafts"].append(info)
        if skill is None:
            continue

        # Persist the skill + mark its source failure_cases processed
        async with async_session() as db:
            db.add(skill)
            await db.flush()  # populate skill.id
            await db.execute(
                update(FailureCase)
                .where(FailureCase.id.in_(info["case_ids"]))
                .values(processed_at=now, learned_skill_id=skill.id)
            )
            await db.commit()
            summary["skills_created"] += 1
            info["learned_skill_id"] = skill.id
            logger.info(
                "skill_creator: created candidate skill %s (%s) from %d cases",
                skill.id, skill.name, len(info["case_ids"]),
            )

    return summary
