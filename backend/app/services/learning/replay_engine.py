# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/replay_engine.py
# @brief      C4-4 — moteur de replay SHADOW : rejoue le tour d'un
#             failure_case avec/sans le skill appris, sans JAMAIS
#             ré-exécuter un outil réel.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Replay shadow — C4-4 (arbitrage 19/07 : shadow STRICT).

La boucle d'apprentissage produit des playbooks/outils mais ne MESURE pas
leur effet (« replay = Phase 6+ », skill_eval = juge statique posé à la
création). Ce moteur referme la mesure : le tour qui a produit un
failure_case est rejoué deux fois — sans (A) puis avec (B) le skill lié
injecté — et le détecteur qui avait produit le signal tranche : le
pattern re-déclenche-t-il ?

Invariants :

- **Aucun outil réel n'est exécuté.** La passerelle est mise en mode
  shadow (``GatewayContext.shadow_results``, court-circuit total en tête
  d'``execute_tool_call``) et re-sert les ToolMessages ENREGISTRÉS au
  moment du signal (``replay_payload.tool_trace``). Un outil hors trace
  reçoit une notice — jamais d'exécution (fail-closed).
- **Le seul écart entre A et B est le bloc <learned_skills>.** Les deux
  runs reçoivent un snapshot mémoire PRÉ-SEEDÉ (``frozen_memory.preseed``)
  identique ± le bloc du skill testé — pas de drift Qdrant, déterminisme.
- **Frontière PII intacte.** L'historique (DB, en clair) est anonymisé
  par un filtre NEUF dédié à la conversation synthétique du run ; la
  trace re-servie est stockée telle que le LLM d'origine l'a vue
  (placeholders) — aucune PII en clair ne repart vers le cloud.
- **Déclenchement humain uniquement** (bench ``--case N``) : coût borné,
  pas de cron, pas de chemin automatique en V1.

Limites V1 assumées : graphe SIMPLE (flat) même si le tour d'origine est
passé par le superviseur — biais constant entre A et B ; base mémoire
vide (le snapshot du tour d'origine n'est pas stocké) ; famille
``user_feedback`` jugée par skill_eval seulement (le « détecteur » de
cette famille est un humain).
"""
from __future__ import annotations

import json
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from app.database import async_session
from app.models.conversation import Message
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill
from app.services.learning.failure_capture import (
    SIGNAL_HALLUCINATION,
    SIGNAL_USER_FEEDBACK,
)

logger = logging.getLogger(__name__)


# ── Session shadow (consommée par la passerelle, duck-typed) ────────────────


class ShadowSession:
    """File de résultats enregistrés, servie par (tool_name, ordre).

    ``serve(name)`` rend le prochain contenu enregistré pour CE nom, ou
    None (épuisé / jamais enregistré) — la passerelle transforme None en
    notice « outil non enregistré ». ``served`` / ``misses`` nourrissent
    le rapport A/B.
    """

    def __init__(self, tool_trace: list[dict] | None):
        self._queues: dict[str, deque[str]] = {}
        for entry in (tool_trace or []):
            try:
                name = str(entry.get("tool") or "")
                if not name:
                    continue
                self._queues.setdefault(name, deque()).append(
                    str(entry.get("content") or "")
                )
            except Exception:  # noqa: BLE001 — entrée pourrie ignorée
                continue
        self.served: list[str] = []
        self.misses: list[str] = []

    def serve(self, tool_name: str) -> str | None:
        q = self._queues.get(tool_name)
        if not q:
            self.misses.append(tool_name)
            return None
        self.served.append(tool_name)
        return q.popleft()


# Registre par conversation synthétique — tool_node le consulte (best-effort)
# et pose la session sur le GatewayContext. Les conv_id sont préfixés
# ``replay-shadow-`` : aucune vraie conversation ne peut matcher.
_SHADOW_SESSIONS: dict[str, ShadowSession] = {}


def register_shadow_session(conversation_id: str, session: ShadowSession) -> None:
    _SHADOW_SESSIONS[conversation_id] = session


def get_shadow_session(conversation_id: str) -> ShadowSession | None:
    return _SHADOW_SESSIONS.get(conversation_id or "")


def pop_shadow_session(conversation_id: str) -> None:
    _SHADOW_SESSIONS.pop(conversation_id or "", None)


# ── Contexte de cas ─────────────────────────────────────────────────────────


@dataclass
class CaseContext:
    """Tout ce qu'il faut pour rejouer le tour d'un failure_case."""

    case_id: int
    user_id: str
    conversation_id: str
    signal_table: str
    history: list[dict] = field(default_factory=list)   # [{role, content}]
    tool_trace: list[dict] = field(default_factory=list)
    learned_skill_id: str | None = None
    user_message: str = ""
    original_response: str = ""


def _as_naive_utc(dt: datetime) -> datetime:
    """SQLite stocke naïf — comparer en naïf UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def load_case_context(case_id: int) -> CaseContext | None:
    """Charge le failure_case + l'historique conversationnel du tour.

    L'historique = les messages user/assistant de la conversation
    antérieurs au signal (marge 60 s pour la course persistance/capture),
    TRONQUÉS au dernier message *user* : le replay repart de l'état juste
    avant la réponse fautive. La table ``messages`` ne contient pas les
    ToolMessages (vérifié) — ils viennent de ``payload.tool_trace``.
    """
    try:
        async with async_session() as db:
            case = (await db.execute(
                select(FailureCase).where(FailureCase.id == case_id)
            )).scalar_one_or_none()
            if case is None:
                return None
            payload: dict = {}
            try:
                payload = json.loads(case.replay_payload or "{}")
            except Exception:  # noqa: BLE001
                payload = {}

            history: list[dict] = []
            if case.conversation_id:
                cutoff = _as_naive_utc(case.created_at) + timedelta(seconds=60)
                rows = (await db.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == case.conversation_id,
                        Message.created_at <= cutoff,
                    )
                    .order_by(Message.created_at.asc())
                )).scalars().all()
                msgs = [
                    {"role": m.role, "content": m.content or ""}
                    for m in rows
                    if m.role in ("user", "assistant")
                ]
                # Tronquer au dernier message user — on rejoue AVANT la
                # réponse fautive (qui peut déjà être persistée, course).
                last_user = max(
                    (i for i, m in enumerate(msgs) if m["role"] == "user"),
                    default=None,
                )
                history = msgs[: last_user + 1] if last_user is not None else []

        if not history:
            # Fallback (ex. user_feedback sur conversation purgée) : le
            # message utilisateur du payload suffit pour un run minimal.
            um = str(payload.get("user_message") or "")
            if um:
                history = [{"role": "user", "content": um}]

        return CaseContext(
            case_id=case.id,
            user_id=case.user_id,
            conversation_id=case.conversation_id or "",
            signal_table=case.signal_table,
            history=history,
            tool_trace=list(payload.get("tool_trace") or []),
            learned_skill_id=case.learned_skill_id,
            user_message=(history[-1]["content"] if history else ""),
            original_response=str(payload.get("original_response") or ""),
        )
    except Exception as exc:  # noqa: BLE001 — moteur best-effort, jamais raise
        logger.warning("load_case_context(%s) failed: %s", case_id, exc)
        return None


# ── Runs shadow ─────────────────────────────────────────────────────────────


async def _forced_skills_block(skill_id: str | None) -> str:
    """Le bloc <learned_skills> du run B — rendu par le VRAI formateur
    (C4-3), pour que le replay teste ce que la prod injecterait."""
    if not skill_id:
        return ""
    try:
        async with async_session() as db:
            skill = (await db.execute(
                select(LearnedSkill).where(LearnedSkill.id == skill_id)
            )).scalar_one_or_none()
        if skill is None:
            return ""
        from app.services.learning.active_skills import format_active_skills_block
        return format_active_skills_block([skill])
    except Exception as exc:  # noqa: BLE001
        logger.warning("forced skills block failed (%s): %s", skill_id, exc)
        return ""


async def run_shadow(case_ctx: CaseContext, *, with_skill: str | None) -> dict[str, Any]:
    """Un run shadow du tour : graphe simple + passerelle en mode shadow.

    Retourne {final_text, served, shadow_misses, conv_id}. Jamais raise.
    """
    conv_id = f"replay-shadow-{uuid.uuid4().hex[:10]}"
    session = ShadowSession(case_ctx.tool_trace)
    from app.services import frozen_memory
    from app.services.conversation_filters import discard_filter, get_filter

    try:
        # 1. Snapshot mémoire forcé — identique entre A et B ± le bloc skill.
        frozen_memory.preseed(conv_id, await _forced_skills_block(with_skill))

        # 2. Frontière PII : filtre NEUF pour la conversation synthétique.
        pii = get_filter(conv_id)
        lc_messages = []
        for m in case_ctx.history:
            content = pii.anonymize(m["content"]) if m["content"] else ""
            if m["role"] == "user":
                lc_messages.append(HumanMessage(content=content))
            else:
                lc_messages.append(AIMessage(content=content))
        if not lc_messages:
            return {"final_text": "", "served": [], "shadow_misses": [],
                    "conv_id": conv_id, "error": "empty history"}

        # 3. Session shadow enregistrée AVANT l'invoke — tool_node la lit.
        register_shadow_session(conv_id, session)

        # 4. Même invocation que le scheduler (unattended → automated_task,
        #    tier cloud fiable, échéances C3d-2 déjà en place).
        from app.agent.graph import build_simple_agent_graph
        from app.config import get_settings
        agent = build_simple_agent_graph()
        result = await agent.ainvoke(
            {
                "messages": lc_messages,
                "user_id": case_ctx.user_id,
                "conversation_id": conv_id,
                "automated_task": True,
            },
            config={"recursion_limit": get_settings().scheduler_recursion_limit},
        )

        raw = result["messages"][-1].content if result.get("messages") else ""
        if isinstance(raw, list):  # blocs multimodaux (pattern scheduler)
            raw = " ".join(
                (b.get("text", "") if isinstance(b, dict) else str(b)) for b in raw
            )
        final_text = pii.deanonymize(str(raw or ""))
        return {
            "final_text": final_text,
            "served": list(session.served),
            "shadow_misses": list(session.misses),
            "conv_id": conv_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("run_shadow(case=%s) failed: %s", case_ctx.case_id, exc)
        return {"final_text": "", "served": list(session.served),
                "shadow_misses": list(session.misses), "conv_id": conv_id,
                "error": str(exc)}
    finally:
        pop_shadow_session(conv_id)
        frozen_memory.discard(conv_id)
        try:
            discard_filter(conv_id)
        except Exception:  # noqa: BLE001
            pass


def _judge(case_ctx: CaseContext, run: dict[str, Any]) -> dict[str, Any]:
    """Le détecteur qui a produit le failure_case re-tourne-t-il ?

    hallucination_blocks → completion_guard réel (record_signal=False : un
    replay ne doit JAMAIS produire un nouveau failure_case).
    user_feedback → pas de détecteur mécanique (le signal d'origine est un
    clic humain) : blocked=False constant, le rapport porte les textes et
    skill_eval fait le 2ᵉ avis.
    """
    if case_ctx.signal_table == SIGNAL_HALLUCINATION:
        from app.services.output_verifier import verify_outcome
        out = verify_outcome(
            run.get("final_text") or "",
            tools_invoked=list(run.get("served") or []),
            surface="replay",
            user_message=case_ctx.user_message or None,
            record_signal=False,
        )
        return {"blocked": bool(out.blocked),
                "reason": getattr(out.verdict, "reason", "")}
    return {"blocked": False, "reason": f"no mechanical detector for {case_ctx.signal_table}"}


async def run_ab(case_id: int, skill_id: str | None = None) -> dict[str, Any]:
    """Le run A/B complet d'un failure_case. Jamais raise.

    A = sans skill ; B = avec le skill (param explicite, sinon
    ``case.learned_skill_id``). Verdict : le détecteur d'origine bloque-t-il
    encore ? ``improved`` (A bloqué, B propre), ``regressed`` (l'inverse),
    ``unchanged`` sinon. Rapport écrit sur le skill
    (``validation_report_json.replay_ab``) + skill_eval en 2ᵉ avis.
    """
    case_ctx = await load_case_context(case_id)
    if case_ctx is None:
        return {"status": "case_not_found", "case_id": case_id}
    skill_id = skill_id or case_ctx.learned_skill_id
    if not skill_id:
        return {"status": "no_skill", "case_id": case_id,
                "hint": "aucun skill lié à ce cas (learned_skill_id) — passe skill_id explicitement"}
    if case_ctx.signal_table not in (SIGNAL_HALLUCINATION, SIGNAL_USER_FEEDBACK):
        return {"status": "unsupported_family", "case_id": case_id,
                "family": case_ctx.signal_table}

    run_a = await run_shadow(case_ctx, with_skill=None)
    run_b = await run_shadow(case_ctx, with_skill=skill_id)
    judge_a = _judge(case_ctx, run_a)
    judge_b = _judge(case_ctx, run_b)

    if judge_a["blocked"] and not judge_b["blocked"]:
        verdict = "improved"
    elif not judge_a["blocked"] and judge_b["blocked"]:
        verdict = "regressed"
    else:
        verdict = "unchanged"

    # 2ᵉ avis LLM-as-judge (best-effort — un échec n'invalide pas l'A/B).
    eval_out: dict[str, Any] | None = None
    try:
        from app.services.learning.skill_eval import evaluate_skill
        eval_out = await evaluate_skill(skill_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("skill_eval second opinion skipped: %s", exc)

    report = {
        "status": "ok",
        "case_id": case_id,
        "skill_id": skill_id,
        "family": case_ctx.signal_table,
        "before": {"final_text": run_a.get("final_text", ""),
                   "blocked": judge_a["blocked"],
                   "shadow_misses": run_a.get("shadow_misses", [])},
        "after": {"final_text": run_b.get("final_text", ""),
                  "blocked": judge_b["blocked"],
                  "shadow_misses": run_b.get("shadow_misses", [])},
        "verdict": verdict,
        "skill_eval": eval_out,
    }

    # Write-back sur le skill — la boucle devient MESURÉE.
    try:
        async with async_session() as db:
            skill = (await db.execute(
                select(LearnedSkill).where(LearnedSkill.id == skill_id)
            )).scalar_one_or_none()
            if skill is not None:
                vr = {}
                try:
                    vr = json.loads(skill.validation_report_json or "{}")
                except Exception:  # noqa: BLE001
                    vr = {}
                vr["replay_ab"] = {
                    "case_id": case_id,
                    "before_blocked": judge_a["blocked"],
                    "after_blocked": judge_b["blocked"],
                    "verdict": verdict,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
                skill.validation_report_json = json.dumps(vr, ensure_ascii=False)
                await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("replay_ab write-back failed (%s): %s", skill_id, exc)

    return report
