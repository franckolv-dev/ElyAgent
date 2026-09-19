# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/patch_service.py
# @brief      « Améliorer la consigne » d'une tâche planifiée : propose /
#             applique / annule une réécriture, à la demande.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.5.0
# =============================================================================
"""« Améliorer la consigne » d'une tâche planifiée.

19/09/2026 — c'est ce qui reste de la page « Incidents & propositions ». Elle
accumulait 81 cartes depuis juin : « Confirmer » ne faisait rien, un correctif
remplacé par un autre ne pouvait plus jamais être vérifié, et chaque exécution
douteuse coûtait un appel LLM de diagnostic, qu'on s'en serve ou non. La seule
chose dont Franck s'était servi : la réécriture de la consigne d'une tâche
planifiée. Elle se déclenche maintenant depuis la fiche de la tâche, sans
incident ni diagnostic en amont — le contexte vient de la DERNIÈRE exécution.

Quatre opérations, toutes déclenchées par l'humain, toutes bornées au
propriétaire de la tâche :

  - :func:`propose_for_task` — génère (LLM) une réécriture et la persiste en
    ``status="proposed"``. NE TOUCHE PAS la tâche. Rejouée, elle rend la
    proposition en attente au lieu d'en payer une seconde.
  - :func:`apply_patch` — écrit la nouvelle consigne, si elle n'a pas changé
    depuis la proposition.
  - :func:`revert_patch` — restaure l'ancienne, si elle n'a pas été retouchée
    depuis l'application.
  - :func:`reject_patch` — écarte la proposition.

La génération est best-effort ; appliquer et annuler sont des écritures
déterministes, jamais un appel LLM.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.execution_outcome import ExecutionOutcome
from app.models.proposed_patch import ProposedPatch
from app.models.scheduled_task import ScheduledTask
from app.services.learning.prompt_version import prompt_hash

logger = logging.getLogger(__name__)

_PATCH_PROMPT = """\
Tu améliores la CONSIGNE d'une tâche planifiée d'Ely qui n'a pas vraiment abouti.
But : corriger ce qui a fait échouer la dernière exécution SANS changer
l'intention d'origine. Rends la consigne impérative et explicite (étapes
claires, noms d'outils corrects, livrable attendu nommé), pour qu'une exécution
automatique non supervisée aboutisse.

Dernière exécution :
  statut déclaré : {last_status}
  verdict        : {verdict}
  signaux faibles: {signals}
  résultat rendu : {last_result}

Consigne actuelle de la tâche :
\"\"\"
{old_prompt}
\"\"\"

Réponds UNIQUEMENT avec un objet JSON STRICT :
{{
  "new_prompt": "la consigne réécrite, prête à l'emploi",
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
    """Lance le LLM. Retourne (raw, model_name). Wrappé pour monkeypatch en test.

    Niveau C : c'est un acte rare, demandé par l'humain, dont la qualité compte.
    """
    from app.services.llm_provider import ComplexityTier, get_llm_for_tier

    llm = get_llm_for_tier(ComplexityTier.COMPLEX)
    model_name = getattr(llm, "model", None) or getattr(llm, "model_name", None) or "unknown"
    response = await llm.ainvoke(
        [{"role": "user", "content": prompt}], config={"callbacks": []},
    )
    # Sur les tiers à blocs (Responses API, modèles à « reasoning », Anthropic),
    # ``response.content`` est une LISTE, pas une str : sans coercition,
    # ``parse_patch`` plante (``list.strip``) hors du try → HTTP 500.
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
    """Erreur métier (tâche introuvable, état invalide…) — mappée en HTTP."""


async def _tache_de(db, task_id: str, user_id: str) -> ScheduledTask:
    task = await db.get(ScheduledTask, task_id)
    if task is None or task.user_id != user_id:
        raise PatchError("tâche planifiée introuvable")
    return task


async def _correctif_de(db, patch_id: int, user_id: str) -> ProposedPatch:
    patch = await db.get(ProposedPatch, patch_id)
    if (patch is None or patch.user_id != user_id or patch.kind != "prompt"
            or patch.target_type != "scheduled_task"):
        raise PatchError("correctif introuvable")
    return patch


async def propose_for_task(task_id: str, user_id: str) -> ProposedPatch:
    """Propose une réécriture de la consigne. Ne touche pas la tâche."""
    async with async_session() as db:
        task = await _tache_de(db, task_id, user_id)
        en_attente = (await db.execute(
            select(ProposedPatch).where(
                ProposedPatch.user_id == user_id,
                ProposedPatch.target_type == "scheduled_task",
                ProposedPatch.target_id == task_id,
                ProposedPatch.status == "proposed",
            ).order_by(ProposedPatch.id.desc()).limit(1)
        )).scalar_one_or_none()
        if en_attente is not None and en_attente.old_value == task.prompt:
            return en_attente
        dernier = (await db.execute(
            select(ExecutionOutcome).where(
                ExecutionOutcome.user_id == user_id,
                ExecutionOutcome.source == "scheduled",
                ExecutionOutcome.source_id == task_id,
            ).order_by(ExecutionOutcome.created_at.desc(), ExecutionOutcome.id.desc()).limit(1)
        )).scalar_one_or_none()
        old_prompt = task.prompt or ""
        last_status = task.last_status or "(inconnu)"
        last_result = (task.last_result or "(aucun)")[:1500]
        verdict = dernier.outcome if dernier else "(aucune exécution jugée)"
        signaux = (dernier.signals if dernier else None) or "[]"

    try:
        sig_list = ", ".join(json.loads(signaux))
    except Exception:
        sig_list = ""

    # PII : la consigne et le résultat sont du texte utilisateur → anonymisés
    # avant le tier cloud, dé-anonymisés au retour.
    from app.services.security_filter import SecurityFilter
    sf = SecurityFilter()
    prompt = sf.anonymize(_PATCH_PROMPT.format(
        last_status=last_status, verdict=verdict, signals=sig_list or "(aucun)",
        last_result=last_result, old_prompt=old_prompt[:4000],
    ), ner_detection=False)
    try:
        raw, model_name = await _call_patch_llm(prompt, user_id=user_id)
        raw = sf.deanonymize(raw)
    except Exception as exc:
        logger.warning("propose_for_task: LLM failed for task=%s : %s", task_id, exc)
        raise PatchError("la génération a échoué (modèle indisponible)")
    parsed = parse_patch(raw)
    if parsed is None:
        raise PatchError("la réécriture générée est illisible")

    async with async_session() as db:
        row = ProposedPatch(
            execution_diagnosis_id=None, user_id=user_id, kind="prompt",
            target_type="scheduled_task", target_id=task_id, field="prompt",
            old_value=old_prompt, new_value=parsed["new_prompt"],
            rationale=parsed["rationale"], status="proposed",
            critic_model=model_name, prompt_version=prompt_hash(_PATCH_PROMPT),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("propose_for_task: task=%s patch=%s", task_id, row.id)
        return row


async def apply_patch(patch_id: int, user_id: str) -> ProposedPatch:
    """Écrit la nouvelle consigne. Refuse si elle a changé depuis la proposition."""
    async with async_session() as db:
        patch = await _correctif_de(db, patch_id, user_id)
        if patch.status != "proposed":
            raise PatchError(f"correctif déjà {patch.status} — non applicable")
        task = await _tache_de(db, patch.target_id, user_id)
        if task.prompt != patch.old_value:
            raise PatchError("La consigne a changé depuis la proposition : demandez-en une nouvelle.")
        task.prompt = patch.new_value
        patch.status = "applied"
        patch.applied_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(patch)
        logger.info("apply_patch: patch=%s task=%s appliqué", patch.id, task.id)
        return patch


async def revert_patch(patch_id: int, user_id: str) -> ProposedPatch:
    """Restaure la consigne d'avant. Refuse si elle a été retouchée depuis."""
    async with async_session() as db:
        patch = await _correctif_de(db, patch_id, user_id)
        if patch.status != "applied":
            raise PatchError(f"correctif {patch.status} — rien à annuler")
        task = await _tache_de(db, patch.target_id, user_id)
        if task.prompt != patch.new_value:
            raise PatchError("La consigne a été modifiée après ce correctif : annulation refusée pour préserver vos changements.")
        task.prompt = patch.old_value or ""
        patch.status = "reverted"
        await db.commit()
        await db.refresh(patch)
        logger.info("revert_patch: patch=%s task=%s annulé", patch.id, task.id)
        return patch


async def reject_patch(patch_id: int, user_id: str) -> ProposedPatch:
    """Écarte une proposition sans l'appliquer."""
    async with async_session() as db:
        patch = await _correctif_de(db, patch_id, user_id)
        if patch.status != "proposed":
            raise PatchError(f"correctif déjà {patch.status}")
        patch.status = "rejected"
        await db.commit()
        await db.refresh(patch)
        return patch


async def patches_for_tasks(db, user_id: str, task_ids: list[str]) -> dict[str, ProposedPatch]:
    """Le correctif VIVANT de chaque tâche : proposé, ou appliqué et toujours en place.

    Un correctif appliqué dont la consigne a été retouchée depuis n'est plus
    annulable : il sort de la fiche. C'est ce qui empêche les cartes éternelles
    de l'ancienne page — rien ne reste affiché sans action possible.
    """
    if not task_ids:
        return {}
    rows = (await db.execute(
        select(ProposedPatch).where(
            ProposedPatch.user_id == user_id, ProposedPatch.kind == "prompt",
            ProposedPatch.target_type == "scheduled_task",
            ProposedPatch.target_id.in_(task_ids),
            ProposedPatch.status.in_(["proposed", "applied"]),
        ).order_by(ProposedPatch.id.desc())
    )).scalars().all()
    vivants: dict[str, ProposedPatch] = {}
    for p in rows:
        vivants.setdefault(p.target_id, p)
    return vivants
