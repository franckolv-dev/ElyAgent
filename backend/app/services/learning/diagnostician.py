# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/diagnostician.py
# @brief      Boucle d'auto-diagnostic J3 — maillon 2 : diagnostiqueur LLM-juge
#             (étend mission_critic) qui formule une cause + une catégorie pour
#             une exécution douteuse / échouée, à partir des TRACES.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.5.0
# =============================================================================
"""Diagnostiqueur d'exécution — boucle d'auto-diagnostic, jalon J3.

Maillon 2 de la design note §4. Sur une exécution ``dubious`` / ``failed``
(posée par J1+J2), il lit les SIGNAUX CORRÉLÉS de la fenêtre
(provider_switches, error_log, hitl_refusals, hallucination_blocks) + les
signaux faibles de l'outcome, et produit une **hypothèse de cause** (langage
naturel) + une **catégorie** (gap_tool / binding / config_tier / prompt /
code_core / user_interaction / unknown).

Trois garde-fous de la design note (§4 / §8) :
  1. Raisonne sur les **traces**, jamais sur le code source (qu'il n'a pas) —
     sinon hallucination assurée. Le prompt ne contient QUE des traces.
  2. Ne valide PAS ses propres hypothèses : il produit ``status="open"`` ;
     l'humain tranche (J4). Pas de boucle qui se félicite.
  3. Dégradé gracieux : si le LLM est indisponible, un classifieur À RÈGLES
     (déterministe, sur les mêmes signaux) produit quand même une diagnose —
     mieux vaut une catégorie honnête « à confirmer » que rien.

Env :
  DIAGNOSTICIAN_DISABLED=true     → court-circuite le cron.
  DIAGNOSTICIAN_TIER (défaut "C") → tier LLM du diagnostiqueur.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.execution_diagnosis import (
    DIAGNOSIS_CATEGORIES,
    DIAGNOSIS_CONFIDENCES,
    ExecutionDiagnosis,
)
from app.models.execution_outcome import ExecutionOutcome
from app.models.proposed_patch import ProposedPatch
from app.services.learning.prompt_version import prompt_hash
from app.services.learning.signals import OUTCOME_DUBIOUS, OUTCOME_FAILED

logger = logging.getLogger(__name__)

# Fenêtre de corrélation temporelle (signaux sans clé directe vers l'exécution).
_CORRELATION_WINDOW = timedelta(hours=2)
# Bornes anti-explosion du prompt.
_MAX_SAMPLES = 5
_MAX_FIELD_CHARS = 300


# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────


def _is_disabled() -> bool:
    return os.environ.get("DIAGNOSTICIAN_DISABLED", "").lower() in (
        "1", "true", "yes", "on",
    )


def _tier_label() -> str:
    raw = os.environ.get("DIAGNOSTICIAN_TIER", "C").strip().upper()
    return raw if raw in ("A", "B", "C", "IMG", "MAINTENANCE") else "C"


# ─────────────────────────────────────────────────────────────────────────
# Évidence corrélée (lecture des tables de signaux)
# ─────────────────────────────────────────────────────────────────────────


async def gather_evidence(outcome: ExecutionOutcome) -> dict:
    """Rassemble les signaux corrélés à une exécution. Best-effort : toute
    requête qui échoue laisse son compteur à 0 plutôt que de casser."""
    created = outcome.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    win_start = created - _CORRELATION_WINDOW
    win_end = created + timedelta(minutes=5)
    conv_id = outcome.conversation_id
    mission_id = outcome.mission_id
    uid = outcome.user_id

    evidence: dict = {
        "outcome": outcome.outcome,
        "declared_status": outcome.declared_status,
        "source": outcome.source,
        "tier_llm": outcome.tier_llm,
        "model_used": outcome.model_used,
        "channel": outcome.channel,
        "reason": (outcome.reason or "")[:_MAX_FIELD_CHARS] or None,
        "signals": _safe_json_list(outcome.signals),
        "provider_switches": {"count": 0, "reasons": [], "transitions": []},
        "tool_errors": {"count": 0, "samples": [], "origins": []},
        "hitl_refusals": {"count": 0, "tools": []},
        "hallucination_blocks": {"count": 0},
    }

    async with async_session() as db:
        # provider_switches : conv_id (tâche) sinon user+fenêtre (mission)
        try:
            from app.models.provider_switch import ProviderSwitch
            q = select(ProviderSwitch)
            if conv_id:
                q = q.where(ProviderSwitch.conversation_id == conv_id)
            else:
                q = q.where(
                    ProviderSwitch.user_id == uid,
                    ProviderSwitch.created_at >= win_start,
                    ProviderSwitch.created_at <= win_end,
                )
            rows = (await db.execute(q.limit(50))).scalars().all()
            evidence["provider_switches"]["count"] = len(rows)
            evidence["provider_switches"]["reasons"] = sorted(
                {r.reason for r in rows if r.reason}
            )
            evidence["provider_switches"]["transitions"] = sorted(
                {f"{r.from_provider}→{r.to_provider}" for r in rows}
            )[:_MAX_SAMPLES]
        except Exception as exc:
            logger.debug("evidence provider_switches failed: %s", exc)

        # error_log : mission_id (mission) sinon user+fenêtre (tâche)
        try:
            from app.models.error_log import ErrorLog
            q = select(ErrorLog)
            if mission_id:
                q = q.where(ErrorLog.mission_id == mission_id)
            else:
                q = q.where(
                    ErrorLog.user_id == uid,
                    ErrorLog.created_at >= win_start,
                    ErrorLog.created_at <= win_end,
                )
            rows = (await db.execute(q.limit(50))).scalars().all()
            evidence["tool_errors"]["count"] = len(rows)
            evidence["tool_errors"]["origins"] = sorted(
                {r.tool_origin for r in rows if r.tool_origin}
            )
            evidence["tool_errors"]["samples"] = [
                {
                    "tool": r.tool_name,
                    "type": r.error_type,
                    "msg": (r.error_msg or "")[:_MAX_FIELD_CHARS],
                    "recovered": bool(r.recovered),
                }
                for r in rows[:_MAX_SAMPLES]
            ]
        except Exception as exc:
            logger.debug("evidence error_log failed: %s", exc)

        # hitl_refusals : mission_id sinon conv_id
        try:
            from app.models.hitl_refusal import HitlRefusal
            q = select(HitlRefusal)
            if mission_id:
                q = q.where(HitlRefusal.mission_id == mission_id)
            elif conv_id:
                q = q.where(HitlRefusal.conversation_id == conv_id)
            else:
                q = q.where(
                    HitlRefusal.user_id == uid,
                    HitlRefusal.created_at >= win_start,
                    HitlRefusal.created_at <= win_end,
                )
            rows = (await db.execute(q.limit(50))).scalars().all()
            evidence["hitl_refusals"]["count"] = len(rows)
            evidence["hitl_refusals"]["tools"] = sorted(
                {r.tool_name for r in rows if r.tool_name}
            )[:_MAX_SAMPLES]
        except Exception as exc:
            logger.debug("evidence hitl_refusals failed: %s", exc)

        # hallucination_blocks : mission_id sinon conv_id
        try:
            from app.models.hallucination_block import HallucinationBlock
            q = select(HallucinationBlock)
            if mission_id:
                q = q.where(HallucinationBlock.mission_id == mission_id)
            elif conv_id:
                q = q.where(HallucinationBlock.conversation_id == conv_id)
            else:
                q = q.where(
                    HallucinationBlock.user_id == uid,
                    HallucinationBlock.created_at >= win_start,
                    HallucinationBlock.created_at <= win_end,
                )
            rows = (await db.execute(q.limit(50))).scalars().all()
            evidence["hallucination_blocks"]["count"] = len(rows)
        except Exception as exc:
            logger.debug("evidence hallucination_blocks failed: %s", exc)

    return evidence


def _safe_json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────
# Classifieur à règles (hint pour le LLM + repli déterministe sans LLM)
# ─────────────────────────────────────────────────────────────────────────


def rule_based_diagnosis(evidence: dict) -> tuple[str, str, str]:
    """(catégorie, confiance, hypothèse) déterministe à partir des signaux.

    Sert de SOCLE : c'est le hint donné au LLM, et le repli si le LLM est
    indisponible. Volontairement prudent sur la confiance.
    """
    signals = set(evidence.get("signals") or [])
    ps = evidence.get("provider_switches", {})
    te = evidence.get("tool_errors", {})
    origins = set(te.get("origins") or [])

    # 1. Faux « pas d'outil » → presque toujours un trou de binding (leçon
    #    find_tool : l'outil existe mais n'a pas été lié à ce tour).
    if "claimed_no_tool" in signals:
        return (
            "binding",
            "medium",
            "L'agent a affirmé ne pas disposer d'outil ; d'après l'historique "
            "c'est vraisemblablement un trou de binding (l'outil existe mais "
            "n'a pas été lié à ce tour), pas une capacité réellement absente.",
        )

    # 2. Erreurs d'outils APPRIS → capacité générée fragile.
    if "learned" in origins:
        return (
            "gap_tool",
            "medium",
            "Des erreurs proviennent d'un outil appris (généré) ; la capacité "
            "existe mais semble fragile / mal calibrée.",
        )

    # 3. Fallback répété → tier LLM instable (cas typique d'un changement d'infra).
    if "fallback" in signals:
        count = int(ps.get("count") or 0)
        if count >= 2:
            return (
                "config_tier",
                "high",
                "Plusieurs bascules de provider sur cette exécution : le tier "
                f"LLM configuré paraît instable ({count} fallbacks, raisons "
                f"{ps.get('reasons') or '—'}).",
            )
        return (
            "config_tier",
            "medium",
            "Un fallback de provider a eu lieu : le tier primaire a échoué et "
            "la chaîne a basculé — à corréler avec un éventuel changement d'infra.",
        )

    # 4. Réussi sans effet observable → l'agent n'a pas agi (plan/prompt).
    if "no_write_effect" in signals:
        return (
            "prompt",
            "medium",
            "L'exécution se déclare réussie sans qu'aucun outil d'écriture "
            "n'ait tourné alors que l'objectif demandait une mutation : l'agent "
            "n'a probablement pas agi (instruction trop molle / planification).",
        )

    # 5. Délégation suspecte.
    if "suspicious_delegation" in signals:
        return (
            "prompt",
            "medium",
            "L'agent a créé une tâche planifiée au lieu d'agir alors que rien "
            "ne le demandait : à reformuler en exécution immédiate.",
        )

    # 6. Erreurs d'outils cœur (builtin) → possible bug, faible confiance.
    if int(te.get("count") or 0) > 0:
        return (
            "code_core",
            "low",
            "Des erreurs d'outils intégrés sont survenues ; cause exacte "
            "indéterminée sur les seules traces — à investiguer côté code.",
        )

    return (
        "unknown",
        "low",
        "Échec/doute sans signal corrélé tranchant ; cause indéterminée sur "
        "les traces disponibles.",
    )


# ─────────────────────────────────────────────────────────────────────────
# Prompt + parsing LLM
# ─────────────────────────────────────────────────────────────────────────


_DIAG_PROMPT = """\
Tu es un diagnostiqueur d'agents IA. Une exécution automatique vient de se \
terminer avec un verdict « douteux » ou « échoué ». À partir UNIQUEMENT des \
TRACES ci-dessous (tu n'as PAS accès au code source — n'invente aucune \
référence de code), formule la cause la plus probable.

Verdict           : {outcome}  (statut déclaré : {declared_status})
Source            : {source}   (tier LLM : {tier_llm}, modèle : {model_used})
Signaux faibles   : {signals}
Raison brute      : {reason}

Signaux corrélés (fenêtre de l'exécution) :
- Bascules provider : {ps}
- Erreurs d'outils  : {te}
- Refus HITL        : {hitl}
- Blocages hallucination : {hallu}

Hint d'un classifieur à règles (à confirmer ou corriger) : catégorie \
« {rule_category} » — {rule_hypothesis}

Choisis une catégorie dans CET ensemble EXACT :
  gap_tool          : capacité réellement absente du registre
  binding           : l'outil existe mais n'a pas été lié à ce tour
  config_tier       : tier/provider LLM instable ou mal choisi
  prompt            : instruction/planification défaillante (agent n'agit pas)
  code_core         : bug probable dans le code cœur (→ ticket humain)
  user_interaction  : l'exécution attendait l'utilisateur (pas un vrai échec)
  unknown           : indéterminable sur les traces

Réponds UNIQUEMENT avec un objet JSON STRICT :
{{
  "category": "binding",
  "confidence": "medium",      // "low" | "medium" | "high"
  "hypothesis": ""             // 1-2 phrases, raisonnées sur les traces
}}
"""


def _fmt_evidence_for_prompt(evidence: dict) -> dict:
    return {
        "outcome": evidence.get("outcome"),
        "declared_status": evidence.get("declared_status"),
        "source": evidence.get("source"),
        "tier_llm": evidence.get("tier_llm") or "?",
        "model_used": evidence.get("model_used") or "?",
        "signals": ", ".join(evidence.get("signals") or []) or "(aucun)",
        "reason": evidence.get("reason") or "(aucune)",
        "ps": json.dumps(evidence.get("provider_switches", {}), ensure_ascii=False),
        "te": json.dumps(evidence.get("tool_errors", {}), ensure_ascii=False),
        "hitl": json.dumps(evidence.get("hitl_refusals", {}), ensure_ascii=False),
        "hallu": json.dumps(evidence.get("hallucination_blocks", {}), ensure_ascii=False),
    }


def compose_prompt(evidence: dict, rule_category: str, rule_hypothesis: str) -> str:
    fields = _fmt_evidence_for_prompt(evidence)
    fields["rule_category"] = rule_category
    fields["rule_hypothesis"] = rule_hypothesis
    return _DIAG_PROMPT.format(**fields)


def _strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    return raw.strip()


def parse_diagnosis(raw: str) -> dict | None:
    """Parse le verdict LLM en {category, confidence, hypothesis} validé,
    ou None si illisible."""
    text = _strip_json_fences(raw or "")
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("diagnostician: invalid JSON: %.200s", text)
        return None
    if not isinstance(data, dict):
        return None
    category = str(data.get("category", "") or "").strip().lower()
    if category not in DIAGNOSIS_CATEGORIES:
        category = "unknown"
    confidence = str(data.get("confidence", "") or "").strip().lower()
    if confidence not in DIAGNOSIS_CONFIDENCES:
        confidence = "medium"
    hypothesis = str(data.get("hypothesis", "") or "").strip()[:2000]
    if not hypothesis:
        return None
    return {"category": category, "confidence": confidence, "hypothesis": hypothesis}


# ─────────────────────────────────────────────────────────────────────────
# Appel LLM (wrappé pour monkeypatch en test)
# ─────────────────────────────────────────────────────────────────────────


async def _call_diagnostician_llm(prompt: str, user_id: str | None = None) -> tuple[str, str]:
    """Lance le LLM diagnostiqueur. Retourne (raw_response, model_name)."""
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
    from app.agent.helpers.message_content import content_to_text
    # Responses API (gpt-5.6) : `content` arrive en LISTE de blocs ;
    # passé tel quel au dé-anonymiseur, `.replace` plantait (03/09/2026).
    raw = content_to_text(getattr(response, "content", "") or "")
    if user_id:
        try:
            from app.services.analytics_service import log_response_usage
            await log_response_usage(
                user_id, response, model=str(model_name), skill_used="diagnostician",
            )
        except Exception:
            pass
    return raw, str(model_name)


def _filter_for(outcome: ExecutionOutcome):
    """Filtre PII : vault de la mission si dispo (cohérence), sinon frais."""
    try:
        if outcome.source == "mission" and outcome.source_id:
            from app.agent.missions.pii import mission_filter
            return mission_filter(outcome.source_id)
    except Exception:
        pass
    from app.services.security_filter import SecurityFilter
    return SecurityFilter()


async def _fold_duplicate(execution_outcome_id: int, user_id: str, source: str,
                          source_id: str | None, rule_cat: str, rule_conf: str,
                          evidence: dict) -> int | None:
    """Garde anti-doublon : replie un run récurrent sur l'incident open existant.

    Clé de récurrence : (user, source, source_id, catégorie à RÈGLES) — la
    catégorie à règles est déterministe, donc stable d'un run à l'autre, et
    disponible AVANT l'appel LLM (un doublon ne re-paye pas le diagnostic).
    En cas de repli : ``occurrences``/``last_seen_at`` cumulés sur le
    canonique (celui qui porte le correctif le plus récent, sinon la première
    occurrence), les autres doublons open passent ``merged``, et un MARQUEUR
    ``merged`` est posé pour CET outcome — sans lui, ``run_pending_diagnoses``
    (qui cherche les outcomes SANS diagnose) re-traiterait le même outcome à
    chaque tick. Retourne l'id du canonique, ou None si pas de doublon.
    """
    async with async_session() as db:
        dups = list((await db.execute(
            select(ExecutionDiagnosis)
            .where(
                ExecutionDiagnosis.user_id == user_id,
                ExecutionDiagnosis.source == source,
                ExecutionDiagnosis.source_id == source_id,
                ExecutionDiagnosis.category == rule_cat,
                ExecutionDiagnosis.status == "open",
            )
            .order_by(ExecutionDiagnosis.created_at.asc(),
                      ExecutionDiagnosis.id.asc())
        )).scalars().all())
        if not dups:
            return None

        # Canonique = l'incident qui porte le correctif le plus récent (ne
        # pas orphaniner un patch déjà proposé), sinon la première occurrence.
        patched_id = (await db.execute(
            select(ProposedPatch.execution_diagnosis_id)
            .where(ProposedPatch.execution_diagnosis_id.in_([d.id for d in dups]))
            .order_by(ProposedPatch.created_at.desc(), ProposedPatch.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        canonical = next((d for d in dups if d.id == patched_id), dups[0])
        canonical_id = canonical.id

        note = f"Doublon de l'incident #{canonical_id} (même tâche, même cause)."
        total = sum((d.occurrences or 1) for d in dups) + 1  # + le run courant
        canonical.occurrences = total
        canonical.last_seen_at = datetime.now(timezone.utc)
        for d in dups:
            if d.id != canonical_id:
                d.status = "merged"
                d.resolution = note

        # Marqueur pour CE run (1 outcome = 1 ligne, UNIQUE respecté).
        db.add(ExecutionDiagnosis(
            execution_outcome_id=execution_outcome_id,
            user_id=user_id, source=source, source_id=source_id,
            category=rule_cat, hypothesis=note, confidence=rule_conf,
            supporting_signals=json.dumps(evidence, ensure_ascii=False, default=str),
            critic_model="dedup", status="merged", resolution=note,
        ))
        try:
            await db.commit()
        except Exception as exc:
            # Collision UNIQUE probable (cron concurrent) — pas une erreur.
            logger.debug("diagnostician: dedup fold skipped for outcome=%s : %s",
                         execution_outcome_id, exc)
            await db.rollback()
            return None
        logger.info("diagnostician: outcome=%s replié sur incident #%s (occurrences=%d)",
                    execution_outcome_id, canonical_id, total)
        return canonical_id


# ─────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────


async def diagnose_execution(execution_outcome_id: int) -> int | None:
    """Diagnostique une exécution douteuse/échouée. Idempotent (UNIQUE sur
    execution_outcome_id) et dédupliqué : un run récurrent (même user/source/
    source_id/catégorie-règles qu'un incident open) est replié sur l'incident
    canonique au lieu d'ouvrir un doublon. Retourne l'id de la diagnose (ou
    du canonique en cas de repli), ou None."""
    if _is_disabled():
        return None

    started = time.monotonic()
    async with async_session() as db:
        outcome = (await db.execute(
            select(ExecutionOutcome).where(ExecutionOutcome.id == execution_outcome_id)
        )).scalar_one_or_none()
        if outcome is None:
            return None
        # On ne diagnostique QUE le douteux / l'échec.
        if outcome.outcome not in (OUTCOME_DUBIOUS, OUTCOME_FAILED):
            return None
        existing = (await db.execute(
            select(ExecutionDiagnosis).where(
                ExecutionDiagnosis.execution_outcome_id == execution_outcome_id
            )
        )).scalar_one_or_none()
        if existing is not None:
            return existing.id
        # Capturer hors-session ce qui sert après commit.
        oc_user = str(outcome.user_id)
        oc_source = outcome.source
        oc_source_id = outcome.source_id
        # `outcome` reste utilisable (expire_on_commit=False) pour gather/filter.
        outcome_ref = outcome

    evidence = await gather_evidence(outcome_ref)
    rule_cat, rule_conf, rule_hyp = rule_based_diagnosis(evidence)

    # Garde anti-doublon — AVANT le LLM : une tâche planifiée qui échoue de
    # la même façon chaque jour cumule sur UN incident open (occurrences) au
    # lieu d'en ouvrir un par run (62+ doublons observés en prod).
    folded = await _fold_duplicate(execution_outcome_id, oc_user, oc_source,
                                   oc_source_id, rule_cat, rule_conf, evidence)
    if folded is not None:
        return folded

    category, confidence, hypothesis, model_name = rule_cat, rule_conf, rule_hyp, "rule-based"

    # LLM (best-effort) — si indisponible, on garde le repli à règles.
    if not _is_disabled():
        try:
            _sf = _filter_for(outcome_ref)
            prompt = compose_prompt(evidence, rule_cat, rule_hyp)
            prompt = _sf.anonymize(prompt, ner_detection=False)
            raw, model_name = await _call_diagnostician_llm(prompt, user_id=oc_user)
            raw = _sf.deanonymize(raw)
            verdict = parse_diagnosis(raw)
            if verdict is not None:
                category = verdict["category"]
                confidence = verdict["confidence"]
                hypothesis = verdict["hypothesis"]
            else:
                model_name = "rule-based"  # LLM illisible → repli
        except Exception as exc:
            logger.warning("diagnostician: LLM failed for outcome=%s : %s",
                           execution_outcome_id, exc)
            model_name = "rule-based"

    duration_ms = int((time.monotonic() - started) * 1000)
    async with async_session() as db:
        row = ExecutionDiagnosis(
            execution_outcome_id=execution_outcome_id,
            user_id=oc_user,
            source=oc_source,
            source_id=oc_source_id,
            category=category,
            hypothesis=hypothesis,
            confidence=confidence,
            supporting_signals=json.dumps(evidence, ensure_ascii=False, default=str),
            critic_model=model_name,
            prompt_version=prompt_hash(_DIAG_PROMPT),
            status="open",
        )
        try:
            db.add(row)
            await db.commit()
            logger.info(
                "diagnostician: outcome=%s category=%s conf=%s model=%s (%dms)",
                execution_outcome_id, category, confidence, model_name, duration_ms,
            )
            return row.id
        except Exception as exc:
            # Collision UNIQUE probable (cron concurrent) — pas une erreur.
            logger.debug("diagnostician: persist skipped for outcome=%s : %s",
                         execution_outcome_id, exc)
            await db.rollback()
            return None


async def run_pending_diagnoses(batch_limit: int = 10) -> int:
    """Cron — diagnostique les exécutions douteuses/échouées sans diagnose."""
    if _is_disabled():
        return 0
    async with async_session() as db:
        diagnosed = select(ExecutionDiagnosis.execution_outcome_id)
        rows = (await db.execute(
            select(ExecutionOutcome.id)
            .where(ExecutionOutcome.outcome.in_([OUTCOME_DUBIOUS, OUTCOME_FAILED]))
            .where(ExecutionOutcome.id.notin_(diagnosed))
            .order_by(ExecutionOutcome.created_at.desc())
            .limit(batch_limit)
        )).all()
        outcome_ids = [r[0] for r in rows]
    persisted = 0
    for oid in outcome_ids:
        if await diagnose_execution(oid) is not None:
            persisted += 1
        await asyncio.sleep(0)
    if outcome_ids:
        logger.info("diagnostician: tick processed %d outcome(s), %d diagnosed",
                    len(outcome_ids), persisted)
    return persisted
