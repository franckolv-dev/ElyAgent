# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/scheduler.py
# @brief      Task scheduler — runs agent prompts on cron schedules
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Task scheduler — runs agent prompts on cron schedules.

Each task triggers the same LangGraph agent as a regular chat message,
then delivers the result to the specified channel (web push or Telegram).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from app.database import async_session
from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.models.conversation import Conversation, Message

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        # V0-1 — garde-fous EXPLICITES (audit Opus 5 §4.6). Les défauts
        # d'APScheduler sont hostiles à une tâche quotidienne :
        #   - misfire_grace_time = 1 s → la moindre latence perd l'occurrence
        #   - coalesce            → une seule exécution après un retard
        #   - max_instances = 1   → une tâche lente ne se superpose pas
        # Ils sont posés en job_defaults pour couvrir AUSSI les jobs
        # enregistrés ailleurs (crons de maintenance dans main.py).
        _scheduler = AsyncIOScheduler(
            timezone="Europe/Paris",
            job_defaults=_job_defaults(),
        )
    return _scheduler


def _job_defaults() -> dict:
    """Garde-fous appliqués à tout job — voir ``get_scheduler``."""
    from app.config import get_settings as _gs
    return {
        "misfire_grace_time": _gs().scheduler_misfire_grace_seconds,
        "coalesce": True,
        "max_instances": 1,
    }


async def _execute_task(task_id: str) -> None:
    """Execute a scheduled task: invoke agent and deliver result."""
    from app.agent.graph import build_simple_agent_graph
    from langchain_core.messages import HumanMessage

    _is_once = False  # one-shot (@once) → auto-deleted in `finally`
    try:
        async with async_session() as db:
            result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if not task or not task.enabled:
                return
            _is_once = _is_oneshot(task.cron_expression)

            # Get user's google credentials
            u_result = await db.execute(select(User).where(User.id == task.user_id))
            user = u_result.scalar_one_or_none()
            google_credentials = user.google_credentials if user else None

        logger.info("Executing scheduled task '%s' for user %s", task.name, task.user_id)

        # A-6b — budget LLM quotidien du user : une tâche planifiée saute
        # son exécution du jour (la tâche reste programmée, le cron la
        # relancera à la prochaine occurrence).
        from app.services.budget_guard import check_user_budget
        if await check_user_budget(task.user_id):
            logger.warning(
                "Scheduled task '%s' (user %s) skipped — budget LLM "
                "quotidien épuisé", task.name, task.user_id,
            )
            return

        # Indicateur d'état (13/06) : marquer « running » dès le départ pour
        # que l'UI montre une exécution en cours (avant : aucun feedback).
        async with async_session() as db:
            _t0 = (await db.execute(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )).scalar_one_or_none()
            if _t0:
                _t0.last_status = "running"
                _t0.last_run_started_at = datetime.now(timezone.utc)
                await db.commit()

        # Create a conversation for this execution
        async with async_session() as db:
            conv = Conversation(
                user_id=task.user_id,
                title=f"[Planifié] {task.name}"
            )
            db.add(conv)
            await db.flush()
            conv_id = str(conv.id)
            db.add(Message(conversation_id=conv_id, role="user", content=task.prompt))
            await db.commit()

        # Invoke agent. Scheduled tasks run on the FLAT (non-supervisor) graph
        # with ``automated_task=True``. Rationale (2026-05-31) : the supervisor
        # routes a whole prompt to ONE sub-agent, so a multi-domain prompt —
        # e.g. a daily briefing that needs calendar + gmail + system tools —
        # lost every tool outside the chosen sub-agent's domain and reported
        # « outil X non disponible pour cet agent » for the rest. The flat
        # graph binds every tool the prompt names (see create_agent_node's
        # automated_task branch). recursion_limit configurable
        # (scheduler_recursion_limit, défaut 60) — 25 était trop bas pour les
        # tâches multi-étapes qui bouclaient avant d'atteindre leurs écritures
        # (bug terrain 13/06, Prospection). Voir config.py.
        from app.config import get_settings as _get_settings
        _recursion = _get_settings().scheduler_recursion_limit
        # ── PII (C0, audit 16/07 §6.2) : le prompt d'une tâche peut contenir
        # adresse, téléphone ou consigne personnelle → anonymiser AVANT le
        # LLM cloud, avec le filtre PARTAGÉ de la conversation (tool_node
        # ré-anonymise déjà les résultats d'outils via ce même filtre, et les
        # placeholders des tool args y sont restaurés).
        from app.services.conversation_filters import get_filter as _get_conv_filter
        _pii_sf = _get_conv_filter(conv_id)
        agent = build_simple_agent_graph()
        invoke_result = await agent.ainvoke(
            {
                "messages": [HumanMessage(content=_pii_sf.anonymize(task.prompt))],
                "user_id": task.user_id,
                "conversation_id": conv_id,
                "google_credentials": google_credentials or "",
                "automated_task": True,
            },
            config={"recursion_limit": _recursion},
        )

        # `content` can be str OR list[dict] (multimodal blocks). Coerce
        # to string for DB persistence — saving a list to a Text column
        # would trigger an autoflush failure when the next SELECT runs
        # in the same session (observed bug : Telegram task 73994b74
        # crashed at 17:30 with "raised as a result of Query-invoked
        # autoflush"). The list shape happens when an agent emits text+
        # image+text triples (e.g. weather card with icon).
        ai_content_raw = invoke_result["messages"][-1].content
        if isinstance(ai_content_raw, list):
            ai_content = " ".join(
                (b.get("text", "") if isinstance(b, dict) else str(b))
                for b in ai_content_raw
            )
        else:
            ai_content = str(ai_content_raw or "")
        # PII (C0) : restaure les vraies valeurs pour la persistance et la
        # livraison à l'utilisateur (le LLM n'a vu que des placeholders).
        ai_content = _pii_sf.deanonymize(ai_content)

        # ── [SILENT] (J2) ──────────────────────────────────────────────────
        # A monitor task that has nothing new to report replies exactly
        # "[SILENT]". We then suppress BOTH the channel delivery AND the
        # throwaway conversation, so a frequent watch (e.g. every 30 min)
        # doesn't spam the channel or the conversation list. By convention,
        # a real failure still delivers (it lands in the except branch, which
        # never sees this path).
        if ai_content.strip().upper().startswith("[SILENT]"):
            async with async_session() as db:
                _conv = (await db.execute(
                    select(Conversation).where(Conversation.id == conv_id)
                )).scalar_one_or_none()
                if _conv is not None:
                    await db.delete(_conv)  # cascade removes the user message
                _t = (await db.execute(
                    select(ScheduledTask).where(ScheduledTask.id == task_id)
                )).scalar_one_or_none()
                if _t is not None:
                    _t.last_run_at = datetime.now(timezone.utc)
                    _t.last_status = "silent"
                    _t.last_result = "[SILENT] — rien de nouveau à signaler"
                await db.commit()
            logger.info(
                "Scheduled task '%s' silent — delivery + conversation skipped",
                task.name,
            )
            return

        # ── Anti-hallucination completion guard (C3c) ──────────────────────
        # Same verification the web/chat surface runs, before this scheduled
        # result is persisted and delivered to its channel(s). [SILENT] tasks
        # already returned above; here a claimed action with no backing tool
        # this run is replaced by an honest warning (derived tools list, like
        # the facade-detection spawn below). Never breaks the task.
        try:
            from app.services.output_verifier import verify_outcome_from_result
            ai_content = verify_outcome_from_result(
                invoke_result, ai_content,
                surface="scheduler",
                user_message=task.prompt,
                user_id=task.user_id,
                conversation_id=conv_id,
            ).content
        except Exception as _guard_exc:
            logger.warning("completion_guard skipped (scheduler): %s", _guard_exc)

        # Save result. Split into two sessions to avoid autoflush
        # interference between the new Message insert and the subsequent
        # ScheduledTask UPDATE (they touch unrelated tables but share the
        # same Unit-of-Work; an autoflush mid-query has caused failures).
        async with async_session() as db:
            db.add(Message(conversation_id=conv_id, role="assistant", content=ai_content))
            await db.commit()
        async with async_session() as db:
            t_result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )
            t = t_result.scalar_one_or_none()
            if t:
                t.last_run_at = datetime.now(timezone.utc)
                t.last_result = ai_content[:2000]
                t.last_status = "success"
                await db.commit()

        # Boucle d'auto-diagnostic — verdict d'aboutissement réel, à côté du
        # statut déclaré. J2 : on calcule les signaux faibles (réussi sans
        # effet observable, fallback, faux « pas d'outil »…) qui font basculer
        # « success » → « dubious ». Best-effort, fire-and-forget : ne bloque
        # jamais la tâche.
        from app.services.background_tasks import spawn
        from app.services.learning.facade_detection import tools_called_from_messages
        from app.services.learning.outcome_recording import record_scheduled_outcome
        _msgs = invoke_result.get("messages") if isinstance(invoke_result, dict) else None
        spawn(
            record_scheduled_outcome(
                user_id=task.user_id,
                task_id=task_id,
                conversation_id=conv_id,
                channel=task.channel,
                declared_status="success",
                goal=task.prompt,
                final_text=ai_content,
                tools_called=tools_called_from_messages(_msgs),
            ),
            label=f"exec-outcome-{task_id}",
        )

        # Deliver result to all configured channels (email, telegram,
        # whatsapp, discord, slack, ntfy + always-on web fallback).
        await _deliver_result(task, ai_content)

        logger.info("Scheduled task '%s' completed", task.name)

    except Exception as exc:
        logger.exception("Failed to execute scheduled task %s: %s", task_id, exc)
        # Save error — wrapped in its own try-except so a DB failure doesn't hide the original error
        try:
            async with async_session() as db:
                t_result = await db.execute(
                    select(ScheduledTask).where(ScheduledTask.id == task_id)
                )
                t = t_result.scalar_one_or_none()
                if t:
                    t.last_run_at = datetime.now(timezone.utc)
                    t.last_result = f"Erreur: {exc}"
                    t.last_status = "error"
                    await db.commit()
                    # Boucle d'auto-diagnostic J1 — verdict « failed » (échec
                    # franc déclaré). Best-effort, ne masque pas l'erreur d'origine.
                    try:
                        from app.services.background_tasks import spawn
                        from app.services.learning.signals import record_execution_outcome
                        spawn(
                            record_execution_outcome(
                                user_id=t.user_id,
                                source="scheduled",
                                source_id=task_id,
                                channel=t.channel,
                                declared_status="error",
                                reason=str(exc),
                            ),
                            label=f"exec-outcome-{task_id}",
                        )
                    except Exception:
                        pass
        except Exception as db_exc:
            logger.warning("Failed to persist error status for task %s: %s", task_id, db_exc)
    finally:
        # One-shot (@once) runs exactly once, then disappears — drop the row
        # so it can't linger or re-fire on reboot (its DateTrigger is past).
        if _is_once:
            await _delete_oneshot(task_id)


async def _deliver_result(task: ScheduledTask, content: str) -> None:
    """Deliver task result to the configured channel.

    Channels supported : telegram, whatsapp, discord, slack, email, ntfy.
    Default ("web" or unknown) → push via WebSocket if connected, AND
    always persist a Message in a dedicated `[Tâches planifiées]`
    conversation so the user sees the result on next login (mirrors the
    [Missions] Notifications pattern).

    Each channel is attempted independently and errors are logged but
    don't block the others.
    """
    chan = (task.channel or "web").lower()
    header = f"📋 *Tâche planifiée : {task.name}*\n\n"
    full = header + content
    delivered = False

    # ── Telegram ──
    if chan == "telegram":
        try:
            from app.channels.telegram_bot import _bot_app, _linked_users
            if _bot_app:
                tg_id = next((tid for tid, uid in _linked_users.items() if uid == task.user_id), None)
                if tg_id:
                    # parse_mode=None : task name + AI content are user/LLM
                    # text → Markdown injection risk + crashes on stray
                    # `_` `*` characters.
                    for i in range(0, len(full), 4096):
                        await _bot_app.bot.send_message(chat_id=tg_id, text=full[i:i + 4096])
                    delivered = True
                else:
                    logger.warning("Task %s telegram: user %s has no linked TG account", task.id, task.user_id)
            else:
                logger.warning("Task %s telegram: bot not running", task.id)
        except Exception as exc:
            logger.warning("Failed Telegram delivery for task %s: %s", task.id, exc)

    # ── WhatsApp (self-chat via neonize bridge) ──
    elif chan == "whatsapp":
        try:
            from app.channels.whatsapp_web import _sessions as _wa_sessions, send_text
            sess = _wa_sessions.get(task.user_id)
            if sess and sess.get("status") == "linked" and sess.get("phone"):
                ok = await send_text(sess["phone"], full, from_user_id=task.user_id)
                delivered = bool(ok)
            else:
                logger.warning("Task %s whatsapp: no linked WhatsApp Web session", task.id)
        except Exception as exc:
            logger.warning("Failed WhatsApp delivery for task %s: %s", task.id, exc)

    # ── Discord (DM the linked user) ──
    elif chan == "discord":
        try:
            from app.channels import discord_bot as _dc
            if getattr(_dc, "_discord_client", None) and _dc._discord_client.is_ready():
                # Reverse-lookup Discord user_id from ELY user_id
                dc_id = next((did for did, uid in _dc._linked_users.items() if uid == task.user_id), None)
                if dc_id:
                    user = await _dc._discord_client.fetch_user(int(dc_id))
                    for i in range(0, len(full), 2000):  # Discord message cap
                        await user.send(full[i:i + 2000])
                    delivered = True
                else:
                    logger.warning("Task %s discord: user %s has no linked Discord account", task.id, task.user_id)
        except Exception as exc:
            logger.warning("Failed Discord delivery for task %s: %s", task.id, exc)

    # ── Slack (DM the linked user) ──
    elif chan == "slack":
        try:
            from app.channels import slack_bot as _sl
            if getattr(_sl, "_slack_app", None):
                slack_uid = next((sid for sid, uid in _sl._linked_users.items() if uid == task.user_id), None)
                if slack_uid:
                    open_resp = await _sl._slack_app.client.conversations_open(users=slack_uid)
                    chan_id = open_resp["channel"]["id"]
                    for i in range(0, len(full), 4000):
                        await _sl._slack_app.client.chat_postMessage(channel=chan_id, text=full[i:i + 4000])
                    delivered = True
                else:
                    logger.warning("Task %s slack: user %s has no linked Slack account", task.id, task.user_id)
        except Exception as exc:
            logger.warning("Failed Slack delivery for task %s: %s", task.id, exc)

    # ── Email (via user's Gmail OAuth credentials) ──
    elif chan == "email":
        try:
            async with async_session() as db:
                u = (await db.execute(select(User).where(User.id == task.user_id))).scalar_one_or_none()

            # Resolve recipient email. Priority :
            # 1. User.email (if it looks like a real address)
            # 2. UserProfile `primary_email` / `user_email` keys (consolidated from chat)
            # Without this fallback, users created with username==email
            # (common at first sign-up) would silently fail email delivery.
            target_email: Optional[str] = None
            if u:
                if u.email and "@" in u.email:
                    target_email = u.email
                else:
                    try:
                        from app.models.user_memory import UserProfile
                        async with async_session() as db:
                            r = await db.execute(
                                select(UserProfile)
                                .where(UserProfile.user_id == task.user_id)
                                .where(UserProfile.key.in_({"primary_email", "user_email", "email"}))
                                .order_by(UserProfile.confidence.desc())
                                .limit(1)
                            )
                            up = r.scalar_one_or_none()
                            if up and "@" in (up.value or ""):
                                target_email = up.value.strip()
                                logger.info("Task %s email: using UserProfile.%s (%s)", task.id, up.key, target_email)
                    except Exception as exc:
                        logger.debug("UserProfile lookup failed: %s", exc)

            if not u:
                logger.warning("Task %s email: user not found", task.id)
            elif not u.google_credentials:
                logger.warning("Task %s email: user %s has no Google OAuth — connect Google in Settings", task.id, u.username)
            elif not target_email:
                logger.warning("Task %s email: user %s has no valid email anywhere (User.email=%r, UserProfile empty)", task.id, u.username, u.email)
            else:
                # Direct call to the Gmail tool's underlying coroutine. We
                # bypass the LangChain @tool decorator wrapper because we
                # already have the user's credentials in hand and don't
                # need HITL (the user EXPLICITLY scheduled this task).
                from app.agent.tools.gmail_tool import gmail_send_email
                result = await gmail_send_email.ainvoke({
                    "to": target_email,
                    "subject": f"[ELY] Tâche planifiée : {task.name}",
                    "body": content,
                    "user_google_credentials_json": u.google_credentials,
                })
                if isinstance(result, str) and ("envoyé" in result.lower() or "sent" in result.lower() or "id:" in result.lower()):
                    delivered = True
                    logger.info("Task %s email: sent to %s (gmail returned: %s)", task.id, target_email, str(result)[:80])
                else:
                    logger.warning("Task %s email: gmail_send_email returned: %s", task.id, str(result)[:200])
        except Exception as exc:
            logger.warning("Failed email delivery for task %s: %s", task.id, exc)

    # ── ntfy (mobile push) ──
    elif chan == "ntfy":
        import os
        ntfy_url = os.environ.get("NTFY_URL")
        if ntfy_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.post(
                        ntfy_url,
                        headers={
                            "Title": f"Tâche planifiée : {task.name}"[:120],
                            "Tags": "calendar",
                            "Priority": "default",
                        },
                        content=content[:1000].encode("utf-8"),
                    )
                delivered = True
            except Exception as exc:
                logger.warning("Failed ntfy delivery for task %s: %s", task.id, exc)
        else:
            logger.warning("Task %s ntfy: NTFY_URL not configured", task.id)

    # ── WebSocket push (best-effort, runs for ALL channels including unknown) ──
    try:
        from app.services import ws_registry
        if ws_registry.get(task.user_id):
            import json
            await ws_registry.send_text_all(task.user_id, json.dumps({
                "type": "scheduled_task",
                "task_name": task.name,
                "content": content,
            }))
            # Don't set `delivered=True` — WebSocket is a "live" push that
            # only works if the user has the app open. The persisted Message
            # below is what guarantees the user sees it next time.
    except Exception as exc:
        logger.warning("WebSocket push for task %s skipped: %s", task.id, exc)

    # ── ALWAYS persist in [Tâches planifiées] convo as a fallback ──
    # Mirrors the [Missions] Notifications pattern : the user always finds
    # the result in their sidebar even if the channel-specific delivery
    # failed (offline, token rotated, etc.).
    try:
        async with async_session() as db:
            r = await db.execute(
                select(Conversation)
                .where(Conversation.user_id == task.user_id)
                .where(Conversation.title.like("[Tâches planifiées]%"))
                .limit(1)
            )
            conv = r.scalar_one_or_none()
            if not conv:
                conv = Conversation(user_id=task.user_id, title="[Tâches planifiées] Résultats")
                db.add(conv)
                await db.flush()
            db.add(Message(conversation_id=conv.id, role="assistant", content=full))
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to persist task result in [Tâches planifiées] convo: %s", exc)

    if delivered:
        logger.info("Task '%s' delivered via %s", task.name, chan)
    else:
        logger.info("Task '%s' result stored (channel=%s did not deliver — see warnings above)", task.name, chan)


_ONCE_PREFIX = "@once"


def _is_oneshot(expression: str | None) -> bool:
    """True iff the expression is a one-shot (``@once <ISO8601>``)."""
    return bool(expression) and expression.strip().lower().startswith(_ONCE_PREFIX)


# Borne dure du balayage d'occurrences — un cron « toutes les minutes » sur
# un horizon de 24 h en produit 1 440. La borne protège d'une expression
# pathologique, elle n'est pas censée être atteinte.
_CATCHUP_SCAN_LIMIT = 5000


def _as_aware(value: datetime | None) -> datetime | None:
    """Les colonnes ``DateTime`` du modèle sont naïves et portent de l'UTC
    (écrites depuis ``datetime.now(timezone.utc)``). On rend l'instant
    explicite plutôt que de laisser la comparaison exploser."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def compute_catchup_run(
    cron_expression: str,
    last_run_at: datetime | None,
    *,
    now: datetime | None = None,
    created_at: datetime | None = None,
    max_age: timedelta | None = None,
) -> datetime | None:
    """Occurrence manquée à rattraper, ou ``None``.

    Répond à une seule question : *depuis la dernière exécution connue, une
    occurrence était-elle due, et est-elle encore assez fraîche pour valoir
    le coup ?* S'il y en a plusieurs, on ne rend que **la plus récente** —
    c'est le `coalesce` appliqué au redémarrage : trois jours d'arrêt
    produisent un briefing, pas trois.

    Le plancher est ``last_run_at``, ou ``created_at`` pour une tâche jamais
    exécutée (on ne rattrape pas ce qui précède la création de la tâche).

    ⚠️ Pourquoi ce calcul explicite plutôt qu'un jobstore APScheduler
    persistant : ``BaseScheduler._real_add_job`` recalcule ``next_run_time``
    depuis l'instant présent dès que le job n'en porte pas, puis
    ``update_job`` écrase la ligne persistée. Comme
    ``load_and_schedule_tasks`` ré-enregistre chaque tâche à chaque boot avec
    ``replace_existing=True``, le ``next_run_time`` passé — celui qui porte
    justement le retard — serait effacé à tous les démarrages. La seule
    source de vérité fiable est ``ScheduledTask.last_run_at``, déjà en base.
    """
    trigger = _parse_cron(cron_expression)
    if trigger is None:
        return None

    tz = ZoneInfo("Europe/Paris")
    now = _as_aware(now) or datetime.now(tz)
    if max_age is None:
        from app.config import get_settings as _gs
        max_age = timedelta(hours=_gs().scheduler_catchup_max_age_hours)

    floor = _as_aware(last_run_at) or _as_aware(created_at)
    horizon = now - max_age
    # Plancher EXCLUSIF : l'occurrence qui tombe pile à l'heure de la dernière
    # exécution est précisément celle qui a déjà tourné.
    cursor = max(floor + timedelta(seconds=1), horizon) if floor is not None else horizon

    latest: datetime | None = None
    for _ in range(_CATCHUP_SCAN_LIMIT):
        try:
            nxt = trigger.get_next_fire_time(None, cursor)
        except Exception as exc:  # trigger exotique — ne jamais bloquer le boot
            logger.warning("Catch-up scan aborted for '%s': %s", cron_expression, exc)
            return None
        if nxt is None or nxt > now:
            break
        latest = nxt
        cursor = nxt + timedelta(seconds=1)

    return latest.astimezone(tz) if latest is not None else None


def _parse_cron(expression: str) -> CronTrigger | DateTrigger | None:
    """Parse a schedule expression into an APScheduler trigger.

    Two forms:
      - **5-field cron** (recurring) : ``minute hour day month day_of_week``
        e.g. '0 8 * * 1-5' (weekdays 8am), '30 9 * * *' (daily 9:30).
      - **One-shot** (J2) : ``@once <ISO8601>``
        e.g. '@once 2026-05-14T08:00'. Fires exactly once on that date
        (DateTrigger), then the task is auto-deleted by ``_execute_task``.
        A naïve datetime is interpreted as Europe/Paris.

    Before J2, a "one-shot" was expressed as a day+month cron
    (e.g. '0 8 14 5 *') which silently **re-fired every year** — the bug
    this form fixes.
    """
    expr = (expression or "").strip()
    if _is_oneshot(expr):
        iso = expr[len(_ONCE_PREFIX):].strip()
        try:
            run_date = datetime.fromisoformat(iso)
            if run_date.tzinfo is None:
                run_date = run_date.replace(tzinfo=ZoneInfo("Europe/Paris"))
            return DateTrigger(run_date=run_date, timezone="Europe/Paris")
        except Exception as exc:
            logger.warning("Failed to parse one-shot '%s': %s", expression, exc)
            return None
    try:
        parts = expr.split()
        if len(parts) == 5:
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone="Europe/Paris",
            )
        else:
            logger.warning("Invalid cron expression: %s", expression)
            return None
    except Exception as exc:
        logger.warning("Failed to parse cron '%s': %s", expression, exc)
        return None


async def _delete_oneshot(task_id: str) -> None:
    """Remove a one-shot task after it has run (DateTrigger fires once;
    we also drop the DB row so it can't linger or re-fire on reboot).
    Best-effort."""
    try:
        unschedule_task(task_id)
        async with async_session() as db:
            t = (await db.execute(
                select(ScheduledTask).where(ScheduledTask.id == task_id)
            )).scalar_one_or_none()
            if t is not None:
                await db.delete(t)
                await db.commit()
                logger.info("One-shot task %s auto-deleted after run", task_id)
    except Exception as exc:
        logger.warning("One-shot cleanup failed for %s: %s", task_id, exc)


def _schedule_catchup(scheduler: AsyncIOScheduler, task: ScheduledTask) -> bool:
    """Programme le rattrapage immédiat d'une occurrence manquée, s'il y en a.

    Renvoie ``True`` si un rattrapage a été programmé. Le job part dans
    quelques secondes (pas immédiatement) pour ne pas alourdir le démarrage,
    et il est **tracé** : le reproche de l'audit n'est pas seulement que
    l'occurrence saute, c'est qu'elle saute *en silence*.
    """
    missed = compute_catchup_run(
        task.cron_expression, task.last_run_at, created_at=task.created_at
    )
    if missed is None:
        return False
    scheduler.add_job(
        _execute_task,
        trigger=DateTrigger(
            run_date=datetime.now(ZoneInfo("Europe/Paris")) + timedelta(seconds=10),
            timezone="Europe/Paris",
        ),
        args=[task.id],
        id=f"catchup_{task.id}",
        replace_existing=True,
        name=f"[rattrapage] {task.name}",
    )
    logger.warning(
        "Rattrapage programmé pour '%s' — occurrence du %s manquée "
        "(dernière exécution : %s)",
        task.name,
        missed.isoformat(timespec="minutes"),
        task.last_run_at.isoformat(timespec="minutes") if task.last_run_at else "jamais",
    )
    return True


async def load_and_schedule_tasks() -> None:
    """Load all enabled tasks from DB and register them with APScheduler."""
    scheduler = get_scheduler()

    async with async_session() as db:
        result = await db.execute(
            select(ScheduledTask).where(ScheduledTask.enabled == True)
        )
        tasks = result.scalars().all()

    catchups = 0
    for task in tasks:
        trigger = _parse_cron(task.cron_expression)
        if trigger:
            scheduler.add_job(
                _execute_task,
                trigger=trigger,
                args=[task.id],
                id=f"task_{task.id}",
                replace_existing=True,
                name=task.name,
            )
            logger.info("Scheduled task '%s' (%s)", task.name, task.cron_expression)
            if _schedule_catchup(scheduler, task):
                catchups += 1

    if catchups:
        logger.warning(
            "Scheduler: %d occurrence(s) manquée(s) rattrapée(s) au démarrage",
            catchups,
        )

    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started with %d tasks", len(tasks))


def schedule_task(task: ScheduledTask) -> bool:
    """Add or update a single task in the running scheduler."""
    scheduler = get_scheduler()
    trigger = _parse_cron(task.cron_expression)
    if not trigger:
        return False

    scheduler.add_job(
        _execute_task,
        trigger=trigger,
        args=[task.id],
        id=f"task_{task.id}",
        replace_existing=True,
        name=task.name,
    )
    return True


def unschedule_task(task_id: str) -> None:
    """Remove a task from the running scheduler."""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(f"task_{task_id}")
    except Exception:
        pass  # Job may not exist


async def stop_scheduler() -> None:
    """Shutdown the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
