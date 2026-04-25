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

Concurrency : we run missions sequentially per beat (simple, predictable).
A mission that takes longer than the heartbeat interval will just delay
the next beat — no overlap, no race conditions on the SqliteSaver
checkpointer.

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

# Process-wide lock so two overlapping beats never run the same mission twice
_beat_lock = asyncio.Lock()


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
            tag = {"completed": "white_check_mark", "failed": "x", "aborted": "no_entry"}.get(kind, "bell")
            priority = "high" if kind in {"failed", "completed"} else "default"
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(
                    ntfy_url,
                    headers={
                        "Title": f"Mission {kind} : {mission.title}"[:120],
                        "Tags": tag,
                        "Priority": priority,
                    },
                    content=summary[:500].encode("utf-8"),
                )
            logger.info("Mission %s: ntfy push sent", mission.id)
        except Exception as exc:
            logger.warning("Mission %s: ntfy push failed: %s", mission.id, exc)


async def heartbeat_tick() -> None:
    """One iteration of the heartbeat. Called by APScheduler every N seconds."""
    if _beat_lock.locked():
        # Previous beat still running (long mission tick). Skip this beat.
        logger.debug("Mission heartbeat: previous beat still running, skipping")
        return

    async with _beat_lock:
        from app.services import mission_service

        try:
            due = await mission_service.list_due_missions()
        except Exception as exc:
            logger.exception("Mission heartbeat: list_due_missions failed: %s", exc)
            return

        if not due:
            return

        logger.info("Mission heartbeat: %d due mission(s)", len(due))
        processed = 0

        for mission in due[:MAX_MISSIONS_PER_BEAT]:
            mid = mission.id

            # Budget guard before each tick — single source of truth for limits
            reason = await mission_service.check_budget(mid)
            if reason:
                logger.info("Mission %s: budget exhausted (%s) — failing", mid, reason)
                await mission_service.fail_mission(mid, reason)
                await _notify_terminal(mission, "failed", reason)
                continue

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
                processed += 1
                continue

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

            processed += 1

        if len(due) > MAX_MISSIONS_PER_BEAT:
            logger.info(
                "Mission heartbeat: %d more due mission(s) deferred to next beat",
                len(due) - MAX_MISSIONS_PER_BEAT,
            )


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
