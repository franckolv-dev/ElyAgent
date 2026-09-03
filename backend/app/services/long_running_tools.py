# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/long_running_tools.py
# @brief      Garde-fou « outil long » — un outil ne monopolise plus un tour
#             de chat : il bascule en tâche de fond et son résultat est livré.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Bascule des outils longs en tâche de fond (générique, toutes surfaces).

Incident fondateur (24/07/2026) : une traduction de PDF (395 pages) a tourné
**2 h 52 dans un tour de chat**. L'utilisatrice n'a rien vu passer, sa
WebSocket est morte bien avant la fin, et le travail — pourtant réussi — n'a
jamais été livré. Le tour de chat est le mauvais endroit pour un job long :
personne ne reste trois heures devant un curseur qui tourne.

Ce que fait ce module, au point de passage UNIQUE de tous les outils
(``tool_gateway.execute_tool_call``, donc aussi bien les outils natifs que
ceux exposés par n'importe quel serveur MCP) :

1. l'outil démarre normalement ; s'il rend la main dans le budget imparti
   (``LONG_TOOL_SOFT_DEADLINE_S``), **rien ne change** — c'est le cas de 99 %
   des appels ;
2. sinon, on **détache** l'exécution — on ne l'annule surtout pas, c'est ce
   qui distingue ce garde-fou d'un timeout — et on rend immédiatement au
   modèle un accusé qui lui dit quoi répondre à l'utilisateur ;
3. à l'arrivée du résultat (succès **ou** échec — le silence est le pire des
   cas), on le livre : message persisté dans la conversation, notification
   push, puis une **reprise du raisonnement** pour que la demande initiale
   aille à son terme (dans l'incident : la conversion DOCX qui suivait la
   traduction).

Périmètre : uniquement les surfaces **interactives** (le chat). Les missions
et les tâches planifiées ont le droit d'attendre — elles sont faites pour ça
et portent leurs propres budgets.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Marqueur présent dans tout accusé de bascule — permet aux surfaces (et aux
# tests) de reconnaître un « ce n'est pas un résultat, c'est une promesse ».
HANDOFF_NOTICE_MARKER = "[tâche de fond]"

# Borne de sécurité : au-delà, on considère le job perdu et on livre un échec
# honnête plutôt que de laisser une promesse ouverte indéfiniment.
MAX_BACKGROUND_SECONDS = 6 * 3600


@dataclass
class BackgroundJob:
    """Un outil parti en tâche de fond, et ce qu'il faut pour le livrer."""

    job_id: str
    tool_name: str
    conversation_id: str
    user_id: str
    user_request: str
    started_at: float
    fingerprint: str
    task: Any = None
    ok: bool | None = None
    result: Any = None
    error: str | None = None
    delivered: bool = False
    # Ce que la passerelle veut faire du résultat s'il arrive (journal
    # d'annulation) : une action partie en fond n'était jamais journalisée
    # (trou n°1, fermé le 03/09/2026).
    on_success: Any = None
    _extra: dict = field(default_factory=dict)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at


# job_id → BackgroundJob (en cours seulement ; purgé à la livraison)
_JOBS: dict[str, BackgroundJob] = {}


def _settings():
    from app.config import get_settings
    return get_settings()


def _handoff_enabled() -> bool:
    return bool(getattr(_settings(), "long_tool_handoff_enabled", True))


def _soft_deadline_s() -> float:
    try:
        return float(getattr(_settings(), "long_tool_soft_deadline_s", 90.0))
    except (TypeError, ValueError):
        return 90.0


def _fingerprint(tool_name: str, args: dict, conversation_id: str) -> str:
    """Empreinte d'un appel — sert l'anti-doublon (un modèle qui relance le
    même appel pendant que le job tourne ne doit pas déclencher 3 h de plus)."""
    try:
        payload = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — args exotiques
        payload = repr(sorted(args)) if isinstance(args, dict) else repr(args)
    raw = f"{conversation_id}|{tool_name}|{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def pending_jobs_for_conversation(conversation_id: str) -> list[BackgroundJob]:
    """Les travaux encore en cours pour cette conversation (ordre de départ)."""
    return sorted(
        (j for j in _JOBS.values()
         if j.conversation_id == conversation_id and j.ok is None),
        key=lambda j: j.started_at,
    )


def describe_pending_job(job: BackgroundJob) -> str:
    """Une ligne lisible par le modèle ET par l'utilisateur."""
    return (
        f"`{job.tool_name}` — lancé il y a {int(job.elapsed_s // 60)} min "
        f"(réf. {job.job_id})"
    )


def _handoff_notice(job: BackgroundJob, *, already_running: bool = False) -> str:
    """L'accusé rendu au modèle à la place du résultat.

    Il est rédigé pour être ACTIONNABLE : le modèle doit comprendre qu'il n'a
    pas échoué, qu'il ne doit pas relancer, et quoi dire à l'utilisateur.
    """
    head = (
        f"{HANDOFF_NOTICE_MARKER} `{job.tool_name}` tourne DÉJÀ en arrière-plan "
        f"(lancé il y a {int(job.elapsed_s)} s, réf. {job.job_id})."
        if already_running else
        f"{HANDOFF_NOTICE_MARKER} `{job.tool_name}` prend plus de temps que ne "
        f"le permet une conversation : l'opération CONTINUE en arrière-plan "
        f"(réf. {job.job_id}). Rien n'est perdu, rien n'est annulé."
    )
    return (
        f"{head}\n"
        "Ne relance PAS cet outil et n'invente aucun résultat. Dis simplement "
        "à l'utilisateur que le travail est lancé, qu'il peut fermer la "
        "conversation, et qu'il sera prévenu dès que ce sera prêt — le "
        "résultat arrivera ici même et par notification."
    )


async def invoke_with_handoff(
    ctx: Any,
    tool_name: str,
    tool: Any,
    args: dict,
    *,
    on_success: Any = None,
) -> tuple[Any, str | None]:
    """Exécute ``tool`` ; bascule en tâche de fond au-delà du budget.

    Retourne ``(result, None)`` dans le cas normal — le résultat est celui de
    l'outil, inchangé. Retourne ``(None, notice)`` quand l'appel a basculé :
    l'appelant doit alors rendre ``notice`` au modèle comme résultat d'outil.

    Les exceptions de l'outil sont propagées telles quelles dans le cas
    normal (l'appelant a déjà sa gestion d'erreur) ; en tâche de fond, elles
    sont capturées et livrées.
    """
    interactive = bool(getattr(ctx, "interactive", False))
    if not interactive or not _handoff_enabled():
        return await tool.ainvoke(args), None

    conversation_id = getattr(ctx, "conversation_id", "") or ""
    fp = _fingerprint(tool_name, args if isinstance(args, dict) else {}, conversation_id)

    # Anti-doublon : ce même appel tourne-t-il déjà ?
    for job in _JOBS.values():
        if job.fingerprint == fp and job.ok is None:
            return None, _handoff_notice(job, already_running=True)

    task = asyncio.create_task(tool.ainvoke(args))
    done, _pending = await asyncio.wait({task}, timeout=_soft_deadline_s())
    if task in done:
        # Chemin normal (la très grande majorité) — .result() propage
        # l'exception éventuelle, exactement comme un await direct.
        return task.result(), None

    job = BackgroundJob(
        job_id=fp[:8],
        tool_name=tool_name,
        conversation_id=conversation_id,
        user_id=getattr(ctx, "user_id", "") or "",
        user_request=getattr(ctx, "user_request", "") or "",
        started_at=time.monotonic(),
        fingerprint=fp,
        task=task,
        on_success=on_success,
    )
    _JOBS[job.job_id] = job
    logger.warning(
        "[long_tool] %s dépasse %.0fs — bascule en tâche de fond (job=%s conv=%s)",
        tool_name, _soft_deadline_s(), job.job_id, conversation_id[:8],
    )
    task.add_done_callback(lambda t, j=job: _on_job_done(j, t))
    return None, _handoff_notice(job)


def _on_job_done(job: BackgroundJob, task: Any) -> None:
    """Callback de fin de tâche — collecte le verdict puis lance la livraison."""
    try:
        if task.cancelled():
            job.ok, job.error = False, "opération annulée"
        elif task.exception() is not None:
            job.ok, job.error = False, str(task.exception())[:500]
        else:
            job.ok, job.result = True, task.result()
    except Exception as exc:  # noqa: BLE001 — un callback ne doit jamais lever
        job.ok, job.error = False, f"verdict illisible : {exc}"
    logger.warning(
        "[long_tool] job=%s (%s) terminé en %.0fs — ok=%s",
        job.job_id, job.tool_name, job.elapsed_s, job.ok,
    )
    if job.ok and job.on_success is not None:
        try:
            from app.services.background_tasks import spawn as _spawn
            _spawn(job.on_success(job.result), label=f"long-tool-journal-{job.job_id}")
        except Exception as exc:  # noqa: BLE001 — journaliser ne bloque pas la livraison
            logger.warning("[long_tool] suite du succès non planifiée (job=%s) : %s",
                           job.job_id, exc)
    try:
        from app.services.background_tasks import spawn
        # Contexte détaché : la livraison fait ses PROPRES appels LLM (reprise
        # du raisonnement) — sans ça, l'arbre de callbacks LangChain hérité
        # ferait fuir ses tokens dans le stream d'un autre tour (leçon C4-2d).
        spawn(_deliver_result(job), label=f"long-tool-deliver-{job.job_id}",
              detach_context=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[long_tool] livraison non planifiée (job=%s) : %s",
                       job.job_id, exc)
    finally:
        _JOBS.pop(job.job_id, None)


def _summarize(job: BackgroundJob, limit: int = 2000) -> str:
    if job.ok:
        text = str(job.result if job.result is not None else "")
        return text[:limit] if text else "(aucune sortie)"
    return f"ÉCHEC : {job.error or 'raison inconnue'}"


async def _deliver_result(job: BackgroundJob) -> None:
    """Livre le résultat d'un job : reprise du raisonnement, persistance, push.

    Chaque étape est best-effort et indépendante : une notification qui échoue
    ne doit pas empêcher le message d'atterrir dans la conversation, et une
    reprise qui échoue ne doit pas faire perdre le résultat brut.
    """
    if job.delivered:
        return
    job.delivered = True

    final_text = await _resume_reasoning(job)
    if not final_text:
        # Reprise impossible (flag, erreur, pas de conversation) : on livre au
        # moins le résultat brut — mieux vaut une sortie technique que rien.
        verdict = "terminée" if job.ok else "en échec"
        final_text = (
            f"⏱ L'opération `{job.tool_name}` lancée en arrière-plan est "
            f"{verdict}.\n\n{_summarize(job)}"
        )

    await _persist_assistant_message(job, final_text)
    await _notify(job, final_text)


async def _resume_reasoning(job: BackgroundJob) -> str:
    """Rejoue un tour d'agent avec le résultat en main pour FINIR la demande.

    C'est ce qui rend la bascule transparente : dans l'incident fondateur, la
    conversion DOCX demandée après la traduction n'a jamais eu lieu parce que
    le tour était mort. Ici, l'agent reprend là où il s'était arrêté.
    Best-effort : rend "" si quoi que ce soit empêche la reprise.
    """
    if not job.conversation_id or not job.user_id:
        return ""
    try:
        from langchain_core.messages import HumanMessage

        from app.agent.graph import build_simple_agent_graph
        from app.config import get_settings
        from app.services.conversation_filters import get_filter

        pii = get_filter(job.conversation_id)
        prompt = (
            "REPRISE AUTOMATIQUE — une opération lancée en arrière-plan vient "
            f"de se terminer.\n\nDemande initiale de l'utilisateur : "
            f"« {job.user_request or 'non conservée'} »\n"
            f"Outil : {job.tool_name}\n"
            f"Résultat :\n{_summarize(job)}\n\n"
            "Termine maintenant ce qui restait à faire pour satisfaire la "
            "demande initiale (par exemple l'étape suivante de la chaîne), "
            "puis réponds à l'utilisateur en français, brièvement, comme si "
            "tu revenais vers lui : ce qui a été fait, où se trouve le "
            "résultat, et ce qui reste éventuellement à sa main. Ne relance "
            "PAS l'opération qui vient de se terminer."
        )
        agent = build_simple_agent_graph()
        out = await agent.ainvoke(
            {
                "messages": [HumanMessage(content=pii.anonymize(prompt))],
                "user_id": job.user_id,
                "conversation_id": job.conversation_id,
                "automated_task": True,
            },
            config={"recursion_limit": get_settings().scheduler_recursion_limit},
        )
        raw = out["messages"][-1].content if out.get("messages") else ""
        if isinstance(raw, list):  # blocs multimodaux
            raw = " ".join(
                (b.get("text", "") if isinstance(b, dict) else str(b)) for b in raw
            )
        return pii.deanonymize(str(raw or "")).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[long_tool] reprise impossible (job=%s) : %s",
                       job.job_id, exc)
        return ""


async def _persist_assistant_message(job: BackgroundJob, text: str) -> None:
    """Écrit la réponse dans la conversation — c'est ce que l'utilisateur
    retrouvera en rouvrant Ely, même s'il a raté la notification."""
    if not job.conversation_id or not text:
        return
    try:
        from datetime import datetime, timezone

        from app.database import async_session
        from app.models.conversation import Conversation, Message

        async with async_session() as db:
            db.add(Message(
                conversation_id=job.conversation_id, role="assistant", content=text,
            ))
            conv = await db.get(Conversation, job.conversation_id)
            if conv is not None:
                conv.updated_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[long_tool] persistance impossible (job=%s) : %s",
                       job.job_id, exc)


async def _notify(job: BackgroundJob, text: str) -> None:
    """Prévient l'utilisateur : WebSocket s'il est revenu, push sinon."""
    # 1. La conversation est peut-être rouverte — pousser le message en direct
    #    sur toutes les sockets du user (fan-out, sockets mortes élaguées).
    try:
        import json as _json
        from datetime import datetime, timezone

        from app.services import ws_registry
        await ws_registry.send_text_all(job.user_id, _json.dumps({
            "type": "message",
            "role": "assistant",
            "content": text,
            "conversation_id": job.conversation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — l'utilisateur est souvent absent
        logger.debug("[long_tool] pas de livraison WS (job=%s) : %s",
                     job.job_id, exc)

    # 2. Push — le canal qui marche quand l'onglet est fermé.
    try:
        from app.services.learning.candidate_notify import _push
        verdict = "est prete" if job.ok else "a echoue"
        await _push(
            f"Ely - ta demande {verdict}",
            " ".join(text.split())[:200],
            tags="white_check_mark" if job.ok else "warning",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[long_tool] push ignoré (job=%s) : %s", job.job_id, exc)
