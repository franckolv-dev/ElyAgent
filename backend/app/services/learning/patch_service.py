# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/patch_service.py
# @brief      Boucle d'auto-diagnostic J5 — propose / applique / annule un
#             correctif de prompt de tâche planifiée (voie C).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# @version    1.5.0
# =============================================================================
"""Correctifs validables (voie C) — boucle d'auto-diagnostic, jalon J5.

Trois opérations, toutes déclenchées par l'humain (rien d'auto) :

  - :func:`propose_patch` — génère (LLM) une réécriture du prompt d'une tâche
    planifiée à partir du diagnostic, et la persiste en ``status="proposed"``.
    NE TOUCHE PAS la tâche.
  - :func:`apply_patch` — applique le correctif : snapshot de la valeur
    courante (pour un revert exact) puis écriture de la nouvelle valeur.
  - :func:`revert_patch` — restaure la valeur d'avant application.

Périmètre v1 : ``kind="prompt"`` / ``target_type="scheduled_task"`` /
``field="prompt"`` (réversible, scopé au user, zéro infra partagée).

Best-effort sur la génération (LLM) ; l'application/le revert sont des
écritures DB déterministes (jamais de LLM).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.execution_diagnosis import ExecutionDiagnosis
from app.models.execution_outcome import ExecutionOutcome
from app.models.proposed_patch import ProposedPatch
from app.models.scheduled_task import ScheduledTask
from app.services.learning.prompt_version import prompt_hash

logger = logging.getLogger(__name__)


_PATCH_PROMPT = """\
Tu améliores le PROMPT d'une tâche planifiée d'Ely qui n'a pas vraiment abouti.
But : corriger la cause diagnostiquée SANS changer l'intention d'origine de la
tâche. Rends le prompt impératif et explicite (étapes claires, noms d'outils
corrects, livrable attendu nommé), pour qu'une exécution automatique non
supervisée aboutisse.

Cause diagnostiquée : {hypothesis}
Catégorie          : {category}
Signaux faibles    : {signals}

Prompt actuel de la tâche :
\"\"\"
{old_prompt}
\"\"\"

Réponds UNIQUEMENT avec un objet JSON STRICT :
{{
  "new_prompt": "le prompt réécrit, prêt à l'emploi",
  "rationale": "1 phrase : ce que tu as changé et pourquoi"
}}
"""


def _strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    return raw.strip()


def parse_patch(raw: str) -> dict | None:
    """Parse le JSON {new_prompt, rationale}. None si illisible/vide."""
    text = _strip_json_fences(raw or "")
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("patch_service: invalid JSON: %.200s", text)
        return None
    if not isinstance(data, dict):
        return None
    new_prompt = str(data.get("new_prompt", "") or "").strip()
    if not new_prompt:
        return None
    rationale = str(data.get("rationale", "") or "").strip()[:1000] or None
    return {"new_prompt": new_prompt[:8000], "rationale": rationale}


async def _call_patch_llm(prompt: str, user_id: str | None = None) -> tuple[str, str]:
    """Lance le LLM (tier diagnostiqueur). Retourne (raw, model_name).
    Wrappé pour monkeypatch en test."""
    from app.services.learning.diagnostician import _tier_label
    from app.services.llm_provider import ComplexityTier, get_llm_for_tier

    tier_enum = {
        "A": ComplexityTier.SIMPLE,
        "B": ComplexityTier.MEDIUM,
        "C": ComplexityTier.COMPLEX,
        "IMG": ComplexityTier.IMAGE,
        "MAINTENANCE": ComplexityTier.MAINTENANCE,
    }.get(_tier_label(), ComplexityTier.COMPLEX)

    llm = get_llm_for_tier(tier_enum)
    model_name = getattr(llm, "model", None) or getattr(llm, "model_name", None) or "unknown"
    response = await llm.ainvoke(
        [{"role": "user", "content": prompt}], config={"callbacks": []},
    )
    # content_to_text : sur les tiers à blocs (Responses API / codex, modèles à
    # « reasoning », Anthropic), ``response.content`` est une LISTE de blocs, pas
    # une str. Sans coercition, ``parse_patch`` plante (``list.strip``) HORS du
    # try → HTTP 500. Helper partagé, comme mission_critic / mission_spec_runtime.
    from app.agent.helpers.message_content import content_to_text
    raw = content_to_text(getattr(response, "content", "") or "")
    if user_id:
        try:
            from app.services.analytics_service import log_response_usage
            await log_response_usage(
                user_id, response, model=str(model_name), skill_used="patch_proposer",
            )
        except Exception:
            pass
    return raw, str(model_name)


class PatchError(Exception):
    """Erreur métier (cible non patchable, état invalide…) — mappée en HTTP."""


class PatchTargetGone(PatchError):
    """La tâche planifiée visée n'existe plus. L'incident est CLASSÉ, pas juste
    refusé.

    **Le défaut qu'elle corrige (21/08).** On levait un `PatchError` sec :
    « tâche planifiée introuvable (supprimée ?) ». L'incident restait « open »,
    et TOUTE action sur lui rejouait la même erreur — il n'existait aucun
    chemin pour le faire sortir de la liste. Franck en avait accumulé plusieurs,
    dont trois identiques, qu'il ne pouvait ni traiter ni écarter honnêtement.

    Le rejeter à la main aurait été faux : « rejeté » veut dire « l'hypothèse
    est mauvaise ». Ici l'hypothèse était peut-être excellente — sa cible a
    simplement disparu. D'où `obsolete`, posé par le service au moment où il
    constate la disparition, et pas par l'humain.
    """


async def _classer_obsolete(diagnosis_id: int, motif: str) -> None:
    """Ferme un incident dont la cible n'existe plus. Ne lève jamais : c'est
    un rangement, il ne doit pas masquer l'erreur qu'il accompagne."""
    try:
        async with async_session() as db:
            diag = (await db.execute(
                select(ExecutionDiagnosis).where(
                    ExecutionDiagnosis.id == diagnosis_id
                )
            )).scalar_one_or_none()
            if diag is None or diag.status != "open":
                return
            diag.status = "obsolete"
            diag.resolution = motif[:2000]
            diag.processed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("incident %s classé obsolete : %s", diagnosis_id, motif)
    except Exception as exc:  # noqa: BLE001
        logger.warning("classement obsolete impossible pour %s : %s",
                       diagnosis_id, exc)


async def propose_patch(diagnosis_id: int) -> ProposedPatch | None:
    """Génère un correctif de prompt pour l'incident donné. Retourne le
    ProposedPatch (status=proposed), ou lève PatchError si non applicable.

    v1 : seulement les incidents d'une tâche planifiée (source=scheduled) dont
    on retrouve la tâche. La catégorie n'est pas imposée (l'humain décide), mais
    l'UI ne propose le bouton que pour la voie C.
    """
    async with async_session() as db:
        diag = (await db.execute(
            select(ExecutionDiagnosis).where(ExecutionDiagnosis.id == diagnosis_id)
        )).scalar_one_or_none()
        if diag is None:
            raise PatchError("incident introuvable")
        outcome = (await db.execute(
            select(ExecutionOutcome).where(
                ExecutionOutcome.id == diag.execution_outcome_id
            )
        )).scalar_one_or_none()
        if outcome is None or outcome.source != "scheduled" or not outcome.source_id:
            raise PatchError("la voie C v1 ne patche que les tâches planifiées")
        task = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == outcome.source_id)
        )).scalar_one_or_none()
        if task is None:
            await _classer_obsolete(
                diagnosis_id,
                "Tâche planifiée supprimée — l'incident n'a plus de cible.",
            )
            raise PatchTargetGone(
                "La tâche planifiée visée n'existe plus : l'incident est classé "
                "sans suite (l'hypothèse n'est pas rejetée, elle est sans objet)."
            )
        old_prompt = task.prompt or ""
        hypothesis = diag.hypothesis
        category = diag.category
        user_id = str(diag.user_id)
        target_id = str(outcome.source_id)
        signals = outcome.signals or "[]"

    # Génération LLM (PII : le prompt de la tâche est du texte user → anonymisé
    # avant le tier cloud, dé-anonymisé au retour).
    from app.services.security_filter import SecurityFilter
    sf = SecurityFilter()
    try:
        sig_list = ", ".join(json.loads(signals)) if signals else ""
    except Exception:
        sig_list = ""
    prompt = _PATCH_PROMPT.format(
        hypothesis=hypothesis, category=category,
        signals=sig_list or "(aucun)", old_prompt=old_prompt[:4000],
    )
    prompt = sf.anonymize(prompt, ner_detection=False)
    try:
        raw, model_name = await _call_patch_llm(prompt, user_id=user_id)
        raw = sf.deanonymize(raw)
    except Exception as exc:
        logger.warning("propose_patch: LLM failed for diag=%s : %s", diagnosis_id, exc)
        raise PatchError("la génération du correctif a échoué (LLM indisponible)")

    parsed = parse_patch(raw)
    if parsed is None:
        raise PatchError("le correctif généré est illisible")

    async with async_session() as db:
        row = ProposedPatch(
            execution_diagnosis_id=diagnosis_id,
            user_id=user_id,
            kind="prompt",
            target_type="scheduled_task",
            target_id=target_id,
            field="prompt",
            old_value=old_prompt,
            new_value=parsed["new_prompt"],
            rationale=parsed["rationale"],
            status="proposed",
            critic_model=model_name,
            prompt_version=prompt_hash(_PATCH_PROMPT),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("propose_patch: diag=%s task=%s patch=%s",
                    diagnosis_id, row.target_id, row.id)
        return row


async def apply_patch(patch_id: int) -> ProposedPatch:
    """Applique un correctif proposé. Snapshot de la valeur courante (revert
    exact) puis écriture. Idempotent-safe : refuse si pas en ``proposed``."""
    async with async_session() as db:
        patch = (await db.execute(
            select(ProposedPatch).where(ProposedPatch.id == patch_id)
        )).scalar_one_or_none()
        if patch is None:
            raise PatchError("correctif introuvable")
        if patch.status != "proposed":
            raise PatchError(f"correctif déjà {patch.status} — non applicable")
        if patch.target_type != "scheduled_task" or patch.field != "prompt":
            raise PatchError("cible non supportée (v1 : prompt de tâche planifiée)")
        task = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == patch.target_id)
        )).scalar_one_or_none()
        if task is None:
            # Même impasse, un clic plus tard : le correctif a été proposé, puis
            # la tâche a été supprimée avant qu'on l'applique. Sans ce
            # classement, l'incident restait « open » avec un correctif
            # inapplicable — encore moins traitable que sans.
            await _classer_obsolete(
                patch.execution_diagnosis_id,
                "Tâche planifiée supprimée avant application du correctif.",
            )
            raise PatchTargetGone(
                "La tâche planifiée visée n'existe plus : le correctif est "
                "caduc et l'incident est classé sans suite."
            )
        # Snapshot de la valeur RÉELLE au moment d'appliquer (revert exact même
        # si la tâche a changé depuis la proposition).
        patch.old_value = task.prompt
        task.prompt = patch.new_value
        patch.status = "applied"
        patch.applied_at = datetime.now(timezone.utc)
        # Appliquer un correctif résout l'incident → diagnose "actioned".
        diag = (await db.execute(
            select(ExecutionDiagnosis).where(
                ExecutionDiagnosis.id == patch.execution_diagnosis_id
            )
        )).scalar_one_or_none()
        if diag is not None and diag.status == "open":
            diag.status = "actioned"
            diag.processed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(patch)
        logger.info("apply_patch: patch=%s task=%s appliqué", patch.id, task.id)
        return patch


async def revert_patch(patch_id: int) -> ProposedPatch:
    """Annule un correctif appliqué : restaure la valeur d'avant application."""
    async with async_session() as db:
        patch = (await db.execute(
            select(ProposedPatch).where(ProposedPatch.id == patch_id)
        )).scalar_one_or_none()
        if patch is None:
            raise PatchError("correctif introuvable")
        if patch.status != "applied":
            raise PatchError(f"correctif {patch.status} — rien à annuler")
        task = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == patch.target_id)
        )).scalar_one_or_none()
        if task is None:
            raise PatchError("tâche planifiée introuvable (supprimée ?)")
        task.prompt = patch.old_value or ""
        patch.status = "reverted"
        await db.commit()
        await db.refresh(patch)
        logger.info("revert_patch: patch=%s task=%s annulé", patch.id, task.id)
        return patch


async def reject_patch(patch_id: int) -> ProposedPatch:
    """Rejette un correctif proposé (sans l'appliquer)."""
    async with async_session() as db:
        patch = (await db.execute(
            select(ProposedPatch).where(ProposedPatch.id == patch_id)
        )).scalar_one_or_none()
        if patch is None:
            raise PatchError("correctif introuvable")
        if patch.status != "proposed":
            raise PatchError(f"correctif déjà {patch.status}")
        patch.status = "rejected"
        await db.commit()
        await db.refresh(patch)
        return patch


async def latest_patch_for(diagnosis_id: int) -> ProposedPatch | None:
    """Le correctif le plus récent attaché à un incident (pour l'UI)."""
    async with async_session() as db:
        return (await db.execute(
            select(ProposedPatch)
            .where(ProposedPatch.execution_diagnosis_id == diagnosis_id)
            .order_by(ProposedPatch.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
