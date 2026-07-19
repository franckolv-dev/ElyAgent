# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_heartbeat.py
# @brief      Mission heartbeat — periodic tick of due missions
# =============================================================================
"""Mission heartbeat — periodic tick of due missions.

Runs as an APScheduler interval job (every `HEARTBEAT_INTERVAL_SECONDS`,
default 30 s). On each beat :

  1. Query all missions whose `next_tick_at` ≤ now AND status ∈ {running, planning}
  2. For each due mission :
     a. Check budget guards (iterations, tokens, deadline) — fail mission if over
     b. Compile mission graph + checkpointer
     c. Invoke ONE iteration (Plan → Act → Eval → maybe Replan)
     d. If `done` flag set → complete mission + notify channel(s)
     e. If `failed` flag set → fail mission + notify
     f. Otherwise → schedule next tick at now + tick_interval_seconds

Concurrency (B-3, revue 2026-06-10) : les ticks sont dispatchés en tâches
de fond bornées par un sémaphore global (``MISSION_TICK_CONCURRENCY``,
défaut 3) avec un garde-fou ``_in_flight`` par mission — jamais deux ticks
simultanés de la même mission (le SqliteSaver reste cohérent ; ses
écritures se sérialisent sur sa connexion unique). Avant ce changement,
les missions étaient traitées séquentiellement sous un lock global : la
mission lente d'un user (tick de 3 min) bloquait les missions de TOUS les
autres, et le beat suivant était sauté tant que le précédent tournait.
L'ordre de dispatch est round-robin par user (équité inter-utilisateurs).

Notifications : when a mission terminates, we attempt to push the result
via the channel that originated it (source_ref → conversation_id /
telegram chat / whatsapp self-chat). Phase 4.3 implements the actual
sending — for now we log + persist to the conversation if applicable.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Default 30 s — fast enough for "feels live" missions, slow enough to
# leave room for inference + tool execution to finish before the next beat
HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("MISSION_HEARTBEAT_SECONDS", "30"))

# Hard cap on missions processed per beat — avoid pathological scenarios
# where dozens of missions queue up and starve the event loop
MAX_MISSIONS_PER_BEAT = int(os.environ.get("MISSION_MAX_PER_BEAT", "5"))

# B-3 — parallélisme global des ticks (toutes missions confondues)
MISSION_TICK_CONCURRENCY = max(1, int(os.environ.get("MISSION_TICK_CONCURRENCY", "3")))
_tick_semaphore = asyncio.Semaphore(MISSION_TICK_CONCURRENCY)

# Garde-fou par mission : ajout SYNCHRONE au dispatch (atomique sur la
# loop) → deux beats ne peuvent jamais ticker la même mission en même
# temps, même si un tick dure plus longtemps que l'intervalle de beat.
_in_flight: set[str] = set()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _tick_one_mission(mission_id: str, user_id: str, goal: str) -> dict:
    """Run exactly one iteration of the persistence loop for a mission."""
    from app.agent.missions.checkpointer import get_mission_checkpointer
    from app.agent.missions.graph import build_mission_graph

    cp = await get_mission_checkpointer()
    graph = build_mission_graph().compile(checkpointer=cp)
    state = {"mission_id": mission_id, "user_id": user_id, "goal": goal}
    config = {"configurable": {"thread_id": mission_id}}
    return await graph.ainvoke(state, config=config)


async def _notify_terminal(mission, kind: str, summary: str) -> None:
    """Send notifications when a mission terminates.

    `kind` is one of "completed" / "failed" / "aborted". Channels used :

    1. **Web UI** : a `[Missions] Notifications` conversation is auto-created
       per user, the message lands there → visible in sidebar history.
    2. **Telegram** (only if `source == 'channel'` and source_ref starts
       with `telegram:`) : DM the user back on the same chat that
       triggered the mission via `/mission`.
    3. **ntfy** (if `NTFY_URL` env var set) : push notification to the
       user's phone via ntfy.sh app.

    Errors in any one notification path are caught and logged — they
    must not block the others or the heartbeat loop.
    """
    emoji = {"completed": "✅", "failed": "❌", "aborted": "🛑"}.get(kind, "ℹ️")
    # Cycle PII missions (2026-06-12) — ceinture défensive : l'invariant
    # garantit que summary/goal sont déjà en clair (dé-anonymisés à la
    # sortie des nodes), mais une notification est le PIRE endroit pour
    # découvrir un placeholder résiduel. deanonymize = no-op si tout va bien.
    try:
        from app.agent.missions.pii import mission_filter
        summary = mission_filter(mission.id).deanonymize(summary or "")
    except Exception:  # noqa: BLE001 — la notification prime
        pass
    msg_content = (
        f"{emoji} **Mission « {mission.title} » {kind}**\n\n"
        f"{summary}\n\n"
        f"_Goal : {mission.goal[:200]}_"
    )

    # ── 1. Persist to web UI history ──
    try:
        from app.database import async_session
        from app.models.conversation import Conversation, Message
        from sqlalchemy import select
        async with async_session() as db:
            r = await db.execute(
                select(Conversation)
                .where(Conversation.user_id == mission.user_id)
                .where(Conversation.title.like("[Missions]%"))
                .limit(1)
            )
            conv = r.scalar_one_or_none()
            if not conv:
                conv = Conversation(user_id=mission.user_id, title="[Missions] Notifications")
                db.add(conv)
                await db.flush()
            db.add(Message(conversation_id=conv.id, role="assistant", content=msg_content))
            await db.commit()
        logger.info("Mission %s: notification persisted (%s)", mission.id, kind)
    except Exception as exc:
        logger.warning("Mission %s: web notification failed: %s", mission.id, exc)

    # ── 2. Telegram DM (if mission originated from Telegram) ──
    if mission.source == "channel" and mission.source_ref and mission.source_ref.startswith("telegram:"):
        try:
            tg_chat_id = int(mission.source_ref.split(":", 1)[1])
            from app.channels import telegram_bot as _tb
            if _tb._bot_app is not None:
                # parse_mode=None on purpose : the mission goal/title/summary
                # are user-controlled text. Markdown parsing would crash with
                # "Can't parse entities" on unmatched _ * [ ] characters
                # AND open an injection vector (user goal containing
                # `[hacked](https://evil.com)` would render as a link).
                await _tb._bot_app.bot.send_message(
                    chat_id=tg_chat_id,
                    text=msg_content,
                )
                logger.info("Mission %s: Telegram notification sent to %d", mission.id, tg_chat_id)
        except Exception as exc:
            logger.warning("Mission %s: Telegram notification failed: %s", mission.id, exc)

    # ── 3. ntfy push (if NTFY_URL configured globally) ──
    ntfy_url = os.environ.get("NTFY_URL")
    if ntfy_url:
        try:
            import httpx

            from app.services.ntfy_headers import ascii_header
            tag = {"completed": "white_check_mark", "failed": "x", "aborted": "no_entry"}.get(kind, "bell")
            priority = "high" if kind in {"failed", "completed"} else "default"
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(
                    ntfy_url,
                    headers={
                        # ascii_header : un titre de mission non-ASCII
                        # (« Veille IA — test mandat ») tuait le push.
                        "Title": ascii_header(f"Mission {kind} : {mission.title}")[:120],
                        "Tags": tag,
                        "Priority": priority,
                    },
                    content=summary[:500].encode("utf-8"),
                )
            logger.info("Mission %s: ntfy push sent", mission.id)
        except Exception as exc:
            logger.warning("Mission %s: ntfy push failed: %s", mission.id, exc)


def _interleave_by_user(missions: list) -> list:
    """Round-robin par user : [a1, a2, a3, b1] → [a1, b1, a2, a3].

    Sans ça, un user avec 5 missions dues monopolise tout le quota du
    beat (MAX_MISSIONS_PER_BEAT) et affame les missions des autres."""
    from collections import OrderedDict, deque

    buckets: "OrderedDict[str, deque]" = OrderedDict()
    for m in missions:
        buckets.setdefault(m.user_id, deque()).append(m)
    ordered: list = []
    while buckets:
        for uid in list(buckets):
            ordered.append(buckets[uid].popleft())
            if not buckets[uid]:
                del buckets[uid]
    return ordered


async def heartbeat_tick() -> None:
    """One iteration of the heartbeat. Called by APScheduler every N seconds.

    B-3 : le beat DISPATCHE puis rend la main — il n'attend plus la fin
    des ticks. Un tick lent n'empêche ni les autres missions de ce beat
    (gather borné par ``_tick_semaphore``) ni les beats suivants (la
    mission encore en vol est simplement sautée via ``_in_flight``).
    """
    from app.services import mission_service
    from app.services.background_tasks import spawn

    try:
        due = await mission_service.list_due_missions()
    except Exception as exc:
        logger.exception("Mission heartbeat: list_due_missions failed: %s", exc)
        return

    if not due:
        return

    dispatched = 0
    skipped_in_flight = 0
    for mission in _interleave_by_user(due):
        if dispatched >= MAX_MISSIONS_PER_BEAT:
            break
        if mission.id in _in_flight:
            skipped_in_flight += 1
            continue
        # Ajout SYNCHRONE (pas d'await entre le test et l'ajout) — deux
        # beats ne peuvent pas dispatcher la même mission.
        _in_flight.add(mission.id)
        spawn(_process_one_mission(mission), label=f"mission-tick-{mission.id}")
        dispatched += 1

    logger.info(
        "Mission heartbeat: %d due, %d dispatched, %d still in flight",
        len(due), dispatched, skipped_in_flight,
    )
    if len(due) - skipped_in_flight > MAX_MISSIONS_PER_BEAT:
        logger.info(
            "Mission heartbeat: %d more due mission(s) deferred to next beat",
            len(due) - skipped_in_flight - MAX_MISSIONS_PER_BEAT,
        )


async def _process_one_mission(mission) -> None:
    """Budget guard → one tick → decide what's next. One mission, owned
    ``_in_flight`` entry (released in the ``finally``)."""
    from app.services import mission_service

    mid = mission.id
    try:
        async with _tick_semaphore:
            # Budget guard before each tick — single source of truth for limits
            reason = await mission_service.check_budget(mid)
            if reason:
                logger.info("Mission %s: budget exhausted (%s) — failing", mid, reason)
                await mission_service.fail_mission(mid, reason)
                await _notify_terminal(mission, "failed", reason)
                return

            # A-6b — budget LLM quotidien du USER (distinct du budget de la
            # mission ci-dessus). On ne tue PAS la mission : un user
            # temporairement à sec ne doit pas perdre son travail — le tick
            # est reporté d'une heure.
            from app.services.budget_guard import check_user_budget
            user_budget_refusal = await check_user_budget(mission.user_id)
            if user_budget_refusal:
                logger.info(
                    "Mission %s: budget quotidien du user %s épuisé — tick "
                    "reporté d'une heure", mid, mission.user_id,
                )
                next_at = _utcnow() + timedelta(hours=1)
                from app.database import async_session
                from app.models.mission import Mission as _M
                from sqlalchemy import update
                async with async_session() as db:
                    await db.execute(
                        update(_M).where(_M.id == mid).values(next_tick_at=next_at)
                    )
                    await db.commit()
                return

            try:
                t0 = datetime.now()
                result = await _tick_one_mission(mid, mission.user_id, mission.goal)
                duration = (datetime.now() - t0).total_seconds()
                logger.info("Mission %s: tick done in %.1fs (iter=%s, done=%s)",
                            mid, duration, result.get("iteration"), result.get("done"))
            except Exception as exc:
                logger.exception("Mission %s: tick crashed: %s", mid, exc)
                await mission_service.fail_mission(mid, f"graph crashed: {exc}")
                await _notify_terminal(mission, "failed", f"Erreur d'exécution : {exc}")
                return

            # Decide what's next
            if result.get("done") and result.get("final_summary"):
                try:
                    completed = await mission_service.complete_mission(mid, result["final_summary"])
                    await _notify_terminal(completed, "completed", result["final_summary"])
                except ValueError:
                    pass  # already terminal (race)
            elif result.get("failed"):
                fr = result.get("failure_reason") or "Échec non spécifié"
                try:
                    failed = await mission_service.fail_mission(mid, fr)
                    await _notify_terminal(failed, "failed", fr)
                except ValueError:
                    pass
            else:
                # Mission still alive — make sure status reflects progress :
                # planning → running once a plan exists. This is purely
                # cosmetic for the UI but makes the badge meaningful.
                if mission.status == "planning" and (result.get("plan_version") or 0) > 0:
                    try:
                        await mission_service.mark_running(mid)
                    except ValueError:
                        pass

                # Schedule next tick. Default 60s if mission has no interval
                # set (single-shot missions still get re-ticked at 60s
                # cadence until they complete or fail).
                interval = mission.tick_interval_seconds or 60
                next_at = _utcnow() + timedelta(seconds=interval)
                from app.database import async_session
                from app.models.mission import Mission as _M
                from sqlalchemy import update
                async with async_session() as db:
                    await db.execute(
                        update(_M).where(_M.id == mid).values(next_tick_at=next_at)
                    )
                    await db.commit()
    finally:
        _in_flight.discard(mid)


async def schedule_first_tick(mission_id: str) -> None:
    """Set `next_tick_at` to NOW for a freshly-started mission, so the
    next heartbeat picks it up immediately instead of waiting tick_interval.

    Called from `start_mission` API endpoint. If the mission has no
    `tick_interval_seconds` set (single-shot), we still set next_tick_at
    so the heartbeat ticks it once; missions that complete on first tick
    won't get re-ticked because their status will be terminal.
    """
    from app.database import async_session
    from app.models.mission import Mission
    from sqlalchemy import update

    async with async_session() as db:
        await db.execute(
            update(Mission)
            .where(Mission.id == mission_id)
            .values(next_tick_at=_utcnow())
        )
        await db.commit()
    logger.info("Mission %s: next_tick_at = now (will fire on next heartbeat)", mission_id)
